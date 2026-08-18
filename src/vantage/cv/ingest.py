"""Frame extraction for the minimap CV pipeline (Component 3, M1).

``FrameStream`` turns a downloaded VOD file into a lazy, pts-ordered
sequence of ``Frame`` objects at the configured fps and working height.
The pipeline consumes frames one at a time and never materialises a whole
match in memory.

Two pieces of orchestration live here:

* ``download_vod_section`` - uses yt-dlp (with ``--download-sections``) to
  grab exactly ``[start, start + duration]`` of a YouTube VOD, trimming a
  margin on either side so the map window is fully covered.
* ``FrameStream`` - streams decoded frames (BGR ndarray) from the local
  file via ffmpeg, resized to ``working_height``.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

from ..config import CvConfig


@dataclass
class Frame:
    index: int
    pts_s: float  # seconds from the start of the extracted window
    image: np.ndarray  # BGR, resized to working_height

    def save(self, path: Path) -> None:
        import cv2

        cv2.imwrite(str(path), self.image)


class FrameStream:
    """Decode a video file into resized BGR frames at a target fps.

    Uses ffmpeg as a subprocess feeding raw BGR frames over stdout, which
    avoids any OpenCV-bundled codec surprises and keeps pts deterministic
    (each raw frame is exactly ``1/fps`` apart in stream time).
    """

    def __init__(self, video_path: Path | str, cfg: CvConfig,
                 start_s: float = 0.0, duration_s: Optional[float] = None,
                 input_headers: Optional[dict[str, str]] = None):
        self.video_path = str(video_path)
        self.fps = cfg.fps
        self.height = cfg.working_height
        self.start_s = start_s
        self.duration_s = duration_s
        self.input_headers = input_headers
        self.ffmpeg = cfg.ffmpeg_bin
        if not self.ffmpeg:
            self.ffmpeg = cfg.resolve_ffmpeg()

    def _ffmpeg_args(self, width: int) -> list[str]:
        args = [self.ffmpeg, "-hide_banner", "-loglevel", "error"]
        # Remote inputs need a headers option (e.g. YouTube requires
        # cookies/user-agent on the stream URL) and fast range seek.
        if self.input_headers:
            headers = "\r\n".join(f"{k}: {v}" for k, v in self.input_headers.items())
            args += ["-headers", headers]
        args += ["-ss", f"{self.start_s:.3f}", "-i", self.video_path]
        if self.duration_s is not None:
            args += ["-t", f"{self.duration_s:.3f}"]
        args += ["-vf", f"fps={self.fps},scale=-2:{self.height}",
                 "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
        return args

    def __iter__(self) -> Iterator[Frame]:
        # Probe with OpenCV once to learn the source aspect ratio, then
        # delegate all actual decoding to ffmpeg for deterministic pts.
        # Remote URLs can't be opened by OpenCV, so assume 16:9 there.
        is_remote = str(self.video_path).startswith(("http://", "https://"))
        width = None if is_remote else self._probe_width()
        width = width if width else max(1, self.height * 16 // 9)
        proc = subprocess.Popen(
            self._ffmpeg_args(width),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        frame_bytes = width * self.height * 3
        index = 0
        try:
            while True:
                raw = proc.stdout.read(frame_bytes)
                if not raw or len(raw) < frame_bytes:
                    break
                image = np.frombuffer(raw[:frame_bytes], dtype=np.uint8).reshape(
                    (self.height, width, 3)
                )
                yield Frame(index=index, pts_s=index / self.fps, image=image.copy())
                index += 1
        finally:
            proc.stdout.close()
            proc.stderr.close()
            proc.wait(timeout=30)

    def _probe_width(self) -> int:
        import cv2

        cap = cv2.VideoCapture(self.video_path)
        try:
            if not cap.isOpened():
                raise RuntimeError(f"cannot open video: {self.video_path}")
            h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or self.height
            w = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or self.height * 16 // 9
            return max(1, int(round(w * self.height / max(1, h))))
        finally:
            cap.release()


def stream_vod_window(vod, cfg: CvConfig,
                      start_s: float | None = None,
                      duration_s: float | None = None,
                      attempts: int = 4,
                      ) -> tuple[ResolvedStream, Iterator[Frame]]:
    """Stream the frames of a VOD map window directly from the network.

    Resolves a playable stream with yt-dlp then hands the URL + auth headers
    to ffmpeg, which does HTTP range seeking to ``start_s`` for ``duration_s``
    seconds. Nothing is persisted to disk. Returns ``(stream, frames)`` where
    ``frames`` is a fresh iterator.

    YouTube signed URLs are occasionally 403 on seek; we retry with a fresh
    resolution up to ``attempts`` times before giving up.

    Map windows default to the VOD's ``start_s`` offset (the ``?t=`` value
    from VLR); pass explicit values to override.
    """
    s = float(start_s if start_s is not None else vod.start_s)
    last_err: Exception | None = None
    for _ in range(max(1, attempts)):
        stream = resolve_vod_stream(vod, cfg)
        frames = FrameStream(stream.url, cfg, start_s=s, duration_s=duration_s,
                             input_headers=stream.headers)
        probe = next(iter(frames), None)
        if probe is not None:
            return stream, iter(FrameStream(stream.url, cfg, start_s=s,
                                            duration_s=duration_s,
                                            input_headers=stream.headers))
        last_err = RuntimeError(f"stream {stream.height}p produced no frames")
    raise RuntimeError(f"could not stream {vod.url}: {last_err}") from last_err


@dataclass
class ResolvedStream:
    """A downloadable media stream for a VOD, resolved via yt-dlp."""
    url: str
    headers: dict[str, str]
    height: int
    ext: str
    protocol: str


def resolve_vod_stream(vod, cfg: CvConfig) -> ResolvedStream:
    """Resolve a VOD to a single playable stream URL without downloading.

    Falls back through player clients (web default, then android) until a
    stream with audio+video (or video-only, accepted for minimap work) is
    found. The returned URL is played directly by ffmpeg with HTTP range
    seeking, so we never download the whole (frequently day-long) VOD.

    Raises ``RuntimeError`` if no stream could be resolved.
    """
    import yt_dlp

    attempts: list[dict] = [
        {"format": "18", "extractor_args": {"youtube": {"player_client": ["android"]}}},
        {"format": "best"},
        {"format": "18"},
        {"extractor_args": {"youtube": {"player_client": ["android"]}}, "format": "best"},
    ]
    last_err: Exception | None = None
    for extra in attempts:
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 3,
            **extra,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(vod.url, download=False)
            if not info or info.get("_type") == "url":
                raise RuntimeError(f"could not resolve {vod.url}")
            fmt = _pick_format(info, prefer_av=True)
            # yt-dlp stores the playable URL under 'url' and frament headers.
            med_url = fmt.get("url") or info.get("url")
            if not med_url:
                continue
            headers = fmt.get("http_headers") or info.get("http_headers") or {}
            return ResolvedStream(
                url=med_url,
                headers=dict(headers),
                height=int(fmt.get("height") or 0),
                ext=fmt.get("ext") or info.get("ext") or "mp4",
                protocol=fmt.get("protocol") or "http",
            )
        except Exception as exc:
            last_err = exc
            continue
    raise RuntimeError(f"no playable stream for {vod.url}: {last_err}") from last_err


def _pick_format(info: dict, prefer_av: bool = True) -> dict | None:
    formats = info.get("formats") or [info]
    ranked = sorted(
        (f for f in formats if f.get("url") and f.get("vcodec", "none") != "none"),
        key=lambda f: (
            # av (has audio) first, then prefer smaller files (faster seek).
            not (prefer_av and f.get("acodec", "none") != "none"),
            -int(f.get("height") or 0) // 2,  # prefer lower height when hq off
        ),
    )
    return ranked[0] if ranked else None


def extract_map_window(video_path: Path | str, cfg: CvConfig,
                       start_s: float = 0.0,
                       duration_s: Optional[float] = None,
                       ) -> list[Frame]:
    """Convenience wrapper that materialises a map window into frames.

    For testing/calibration. Long matches should stream with ``FrameStream``
    directly to avoid holding thousands of frames in memory.
    """
    return list(FrameStream(video_path, cfg, start_s, duration_s))