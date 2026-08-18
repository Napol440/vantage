"""Configuration loading (YAML) for the pipeline."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_CONFIG_NAME = "config.yaml"


@dataclass
class HttpConfig:
    base_url: str = "https://www.vlr.gg"
    rate_limit_seconds: float = 1.0
    timeout_seconds: int = 30
    user_agent: str = "vantage/0.1"
    retries: int = 3
    backoff_base_seconds: float = 1.0
    backoff_factor: float = 2.0
    retry_status_codes: List[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )


@dataclass
class PathsConfig:
    data_dir: str = "data"
    sqlite_path: str = "data/vantage.db"
    json_dir: str = "data/json"
    logs_dir: str = "logs"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "logs/vantage.log"
    to_file: bool = True


@dataclass
class TargetsConfig:
    team: Optional[str] = None
    event: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


@dataclass
class ScraperConfig:
    include_performance: bool = True
    include_economy: bool = True
    include_rosters: bool = True
    limit: int = 0
    refresh: bool = False


@dataclass
class RibConfig:
    enabled: bool = False
    base_url: str = "https://be-prod.rib.gg/v1"
    rate_limit_seconds: float = 2.0
    retries: int = 2
    backoff_base_seconds: float = 1.0
    backoff_factor: float = 2.0
    event_id: Optional[int] = None  # fetch series for this event
    team_id: Optional[int] = None   # fetch recent series for this team
    take: int = 50                  # page size for series/events
    fetch_details: bool = True      # also call matches/{id}/details (economy rounds)


@dataclass
class Config:
    http: HttpConfig = field(default_factory=HttpConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    targets: TargetsConfig = field(default_factory=TargetsConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    rib: RibConfig = field(default_factory=RibConfig)
    config_path: Optional[Path] = None
    root_dir: Path = field(default_factory=Path.cwd)

    @classmethod
    def from_file(cls, path: Optional[str | Path] = None) -> "Config":
        config_path = _find_config(path)
        raw: Dict[str, Any] = {}
        if config_path and config_path.exists():
            with open(config_path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}

        root_dir = (config_path.parent if config_path else Path.cwd()).resolve()
        cfg = cls(
            http=_build(raw.get("http", {}), HttpConfig),
            paths=_build(raw.get("paths", {}), PathsConfig),
            logging=_build(raw.get("logging", {}), LoggingConfig),
            targets=_build(raw.get("targets", {}), TargetsConfig),
            scraper=_build(raw.get("scraper", {}), ScraperConfig),
            rib=_build(raw.get("rib", {}), RibConfig),
            config_path=config_path,
            root_dir=root_dir,
        )
        cfg.paths = _resolve_paths(cfg.paths, root_dir)
        cfg.logging = _resolve_logging(cfg.logging, root_dir)
        return cfg

    def resolve(self, raw: str) -> str:
        return str(Path(raw).expanduser().resolve()) if raw else raw


def _find_config(path: Optional[str | Path]) -> Optional[Path]:
    if path:
        p = Path(path).expanduser()
        return p if p.exists() else None
    for candidate in (
        Path.cwd() / DEFAULT_CONFIG_NAME,
        Path(__file__).resolve().parents[2] / DEFAULT_CONFIG_NAME,
    ):
        if candidate.exists():
            return candidate
    return None


def _build(raw: Dict[str, Any], cls: Any) -> Any:
    known = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in raw.items() if k in known})


def _resolve_paths(paths: PathsConfig, root: Path) -> PathsConfig:
    for f in dataclasses.fields(paths):
        raw = getattr(paths, f.name)
        if not raw:
            continue
        p = Path(os.path.expandvars(str(raw)))
        if not p.is_absolute():
            p = root / p
        setattr(paths, f.name, str(p.resolve()))
    return paths


def _resolve_logging(logging_cfg: LoggingConfig, root: Path) -> LoggingConfig:
    if logging_cfg.file and not Path(logging_cfg.file).is_absolute():
        logging_cfg.file = str((root / logging_cfg.file).resolve())
    return logging_cfg


# =============================================================================
# CV pipeline config (Component 3)
# =============================================================================

def _env_or(key: str, default: str) -> str:
    return os.environ.get(key, default)


@dataclass
class CvConfig:
    """Full configuration for the CV pipeline."""

    production_profile: str = "vct_official"
    fps: int = 6
    working_height: int = 1080
    frames_dir: Path = field(default_factory=lambda: Path("data/frames"))
    scratch_dir: Path = field(default_factory=lambda: Path("data/scratch"))
    db_path: Path = field(default_factory=lambda: Path("data/vantage.db"))
    ffmpeg_bin: str = ""

    @classmethod
    def load(cls, path: Path | str | None = None) -> "CvConfig":
        """Load ``cv`` config from a YAML file, falling back to defaults."""
        defaults = cls()
        data: dict = {}
        if path is not None and Path(path).exists():
            with open(path, "r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
            data = raw.get("cv", {}) if isinstance(raw, dict) else {}

        cfg = cls(
            production_profile=str(data.get("production_profile", defaults.production_profile)),
            fps=int(data.get("fps", defaults.fps)),
            working_height=int(data.get("working_height", defaults.working_height)),
            frames_dir=Path(data.get("frames_dir", str(defaults.frames_dir))),
            scratch_dir=Path(data.get("scratch_dir", str(defaults.scratch_dir))),
            db_path=Path(data.get("db_path", str(defaults.db_path))),
            ffmpeg_bin=str(data.get("ffmpeg_bin", defaults.ffmpeg_bin)),
        )
        cfg.scratch_dir.mkdir(parents=True, exist_ok=True)
        cfg.frames_dir.mkdir(parents=True, exist_ok=True)
        cfg.resolve_ffmpeg()
        return cfg

    def resolve_ffmpeg(self) -> str:
        """Return an absolute ffmpeg path, resolving from imageio if unset."""
        if not self.ffmpeg_bin:
            from imageio_ffmpeg import get_ffmpeg_exe
            self.ffmpeg_bin = get_ffmpeg_exe()
        if not Path(self.ffmpeg_bin).is_absolute():
            self.ffmpeg_bin = str(Path(self.ffmpeg_bin).resolve())
        return self.ffmpeg_bin
