"""Simple timer reader using template matching on digit crops."""
import cv2, numpy as np, os

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
w = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))

# Timer bbox: center of screen, top 22px
# From analysis: timer digits are at x=59-101 in the 160px crop
# So in full frame: x = w//2 - 80 + 59 = w//2 - 21, width = 42
TIMER_X = w//2 - 25
TIMER_Y = 0
TIMER_W = 50
TIMER_H = 22

def read_timer_simple(frame):
    """Read timer using connected components."""
    crop = frame[TIMER_Y:TIMER_Y+TIMER_H, TIMER_X:TIMER_X+TIMER_W]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    
    # Threshold - timer digits are bright on dark
    _, th = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
    
    # Find connected components
    num, labels, stats, centroids = cv2.connectedComponentsWithStats(th, connectivity=8)
    
    # Get bounding boxes, sorted by x
    bboxes = []
    for i in range(1, num):  # skip background
        x, y, bw, bh, area = stats[i]
        if area < 5:
            continue
        bboxes.append((x, y, bw, bh, area))
    bboxes.sort(key=lambda b: b[0])
    
    return bboxes, crop, th

# Read timer from several frames and compare
print("Timer analysis:")
for fi in [924, 1050, 1200, 1800, 2400, 3000, 3600, 4200, 4800, 5400, 7200, 10800, 14400, 21600, 28800, 36000, 43200, 50400, 57600, 64800, 70000]:
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    
    bboxes, crop, th = read_timer_simple(frame)
    
    # Try to classify digits by width pattern
    # Timer format: "M:SS" = digit, colon, digit, digit
    # Colon is narrower than digits
    widths = [b[2] for b in bboxes]
    
    # Save first few for visual inspection
    if fi in [924, 3600, 7200, 14400, 28800]:
        cv2.imwrite(f"timer_{fi}.png", crop)
        cv2.imwrite(f"timer_th_{fi}.png", th)
    
    print(f"  Frame {fi:>5} ({fi/30:6.1f}s): {len(bboxes)} components, widths={widths}")

video.release()
