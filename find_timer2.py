"""Standalone timer reader - save timer crops for visual inspection."""
import cv2, numpy as np, json

video = cv2.VideoCapture("twitch_data/breeze_full.mp4")
w = int(video.get(cv2.CAP_PROP_FRAME_WIDTH))

# Save timer crops at known game states
# Breeze round timers: 1:40 (100s) at round start, 0:30 buy phase
# Frame 1200 = 40s into VOD. Breeze starts at 924s. So 1200-924=276s into the map.
# 276 / ~100s per round ≈ round 3 mid-round

frames_to_check = {
    924: "map_start",
    960: "buy_phase?",   # 1s after map start
    1050: "round1?",     # ~4s in
    1200: "round?",      # 9s in
    3600: "round?",
    7200: "round?",
    14400: "round?",
    28800: "round?",
    43200: "round?",
}

for fi_str, label in frames_to_check.items():
    fi = int(fi_str)
    video.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ret, frame = video.read()
    if not ret:
        continue
    
    # Save top-center region (timer area)
    timer_crop = frame[0:30, w//2-80:w//2+80]
    cv2.imwrite(f"timer_crop_{fi}.png", timer_crop)
    
    # Also save a wider view for context
    context = frame[0:60, w//2-150:w//2+150]
    cv2.imwrite(f"timer_context_{fi}.png", context)
    
    # Analyze the timer region
    gray = cv2.cvtColor(timer_crop, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    # Count white pixels per column
    col_sum = th.sum(axis=0) / 255
    
    # Find digit regions (columns with white pixels)
    in_digit = False
    digits = []
    start = 0
    for i, v in enumerate(col_sum):
        if v > 0 and not in_digit:
            start = i
            in_digit = True
        elif v == 0 and in_digit:
            digits.append((start, i))
            in_digit = False
    if in_digit:
        digits.append((start, len(col_sum)))
    
    # Filter small regions (noise)
    digits = [(s, e) for s, e in digits if e - s >= 3]
    
    print(f"Frame {fi} ({label}): timer region {len(digits)} potential digits/chars")
    for s, e in digits:
        print(f"  x={s}-{e} width={e-s}")

video.release()
print("\nSaved timer crops: timer_crop_*.png, timer_context_*.png")
