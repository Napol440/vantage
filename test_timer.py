"""Try to read the timer from the top-center region."""
import sys, cv2, numpy as np
sys.path.insert(0, 'src')
from vantage.cv.clock import read_timer

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
w = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))

# Timer is at top center - try different bbox sizes
# Based on the brightness analysis, the timer is around x=590-690, y=2-22
timer_bboxes = [
    (w//2-50, 2, 100, 18),
    (w//2-40, 0, 80, 20),
    (w//2-60, 0, 120, 25),
    (w//2-30, 3, 60, 15),
    (570, 0, 140, 22),
]

for fi in [1200, 3600, 7200, 14400, 28800, 43200, 70000]:
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    print(f"\nFrame {fi} ({fi/30:.0f}s):")
    for bbox in timer_bboxes:
        try:
            text = read_timer(frame, bbox)
            print(f"  bbox={bbox}: '{text}'")
        except Exception as e:
            print(f"  bbox={bbox}: error={e}")

video.release()
