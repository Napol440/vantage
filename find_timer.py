"""Find the round timer location on Sliggy's overlay."""
import sys
sys.path.insert(0, 'src')
import cv2
import numpy as np

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
MX, MY, MW, MH = 23, 29, 256, 242
h_frame = int(video.get(cv2.CAP_PROP_FRAME_HEIGHT))
w_frame = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))
print(f"Frame size: {w_frame}x{h_frame}")

# Check the scoreboard/timer area at the top of the screen
# Valorant timer is typically at top center, shown as "1:40" etc.
for fi in [1200, 3600, 14400, 28800]:
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue

    # Scan top 40 pixels for bright text (timer digits)
    top_strip = frame[0:40, :, :]
    gray = cv2.cvtColor(top_strip, cv2.COLOR_BGR2GRAY)

    # Find bright regions (timer text is usually white/bright)
    for threshold in [180, 200, 220]:
        _, th = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        # Find horizontal extent of bright pixels
        col_sum = th.sum(axis=0)
        bright_cols = np.where(col_sum > 0)[0]
        if len(bright_cols) > 0:
            x_min, x_max = bright_cols[0], bright_cols[-1]
            print(f"  Frame {fi} thresh={threshold}: bright text at x={x_min}-{x_max}, width={x_max-x_min}")

    # Also look at specific known timer locations
    # On Sliggy's stream, the timer is usually in the top bar
    regions_to_check = [
        ("top-center", w_frame//2-50, 2, 100, 20),
        ("top-center-wide", w_frame//2-80, 0, 160, 30),
        ("above-minimap", MX, max(0,MY-25), MW, 25),
        ("right-of-minimap", MX+MW+5, MY, 60, 20),
        ("left-of-minimap", max(0,MX-70), MY, 65, 20),
        ("scoreboard-left", 300, 5, 80, 25),
        ("scoreboard-right", w_frame-380, 5, 80, 25),
    ]

    print(f"\nFrame {fi}:")
    for name, rx, ry, rw, rh in regions_to_check:
        rx2 = max(0, min(rx, w_frame-1))
        ry2 = max(0, min(ry, h_frame-1))
        rw2 = min(rw, w_frame - rx2)
        rh2 = min(rh, h_frame - ry2)
        if rw2 <= 0 or rh2 <= 0:
            continue
        crop = frame[ry2:ry2+rh2, rx2:rx2+rw2]
        if crop.size == 0:
            continue
        gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mean_val = gray_crop.mean()
        max_val = gray_crop.max()
        # Check if it looks like text (high contrast)
        contrast = max_val - gray_crop.min()
        print(f"  {name:20s} ({rx2},{ry2},{rw2},{rh2}): mean={mean_val:5.1f} max={max_val:3d} contrast={contrast:3d}")

video.release()
