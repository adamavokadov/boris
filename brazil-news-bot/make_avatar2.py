from PIL import Image, ImageDraw, ImageFont

S = 512
img = Image.new('RGB', (S, S), '#87CEEB')  # sky blue background
draw = ImageDraw.Draw(img)

# --- Background: Sao Paulo city skyline at dusk ---
# Sky gradient (warm sunset)
for y in range(S):
    t = y / S
    r = int(255 - 120*t)
    g = int(180 - 60*t)
    b = int(120 - 40*t)
    draw.line([(0,y),(S,y)], fill=(r,g,b))

# Sun
draw.ellipse([S*0.55, S*0.15, S*0.75, S*0.35], fill=(255, 220, 120))

# City skyline (buildings)
import random
random.seed(42)
building_colors = [(60,60,80), (70,70,90), (50,50,70), (80,80,100), (65,65,85)]
x = 0
while x < S:
    w = random.randint(30, 70)
    h = random.randint(80, 220)
    y = S - h
    color = random.choice(building_colors)
    draw.rectangle([x, y, x+w, S], fill=color)
    # windows
    for wy in range(y+10, S-10, 18):
        for wx in range(x+6, x+w-6, 14):
            if random.random() > 0.5:
                draw.rectangle([wx, wy, wx+6, wy+8], fill=(255, 220, 150))
    x += w + 5

# --- Foreground: student portrait (bust) ---
# Body/shirt
shirt = (30, 80, 150)  # blue shirt
draw.rounded_rectangle([S*0.15, S*0.55, S*0.85, S*1.1], radius=40, fill=shirt)

# Neck
neck = (222, 184, 135)
draw.rectangle([S*0.44, S*0.42, S*0.56, S*0.58], fill=neck)

# Head
head_cx, head_cy = S*0.5, S*0.30
head_r = 105
draw.ellipse([head_cx-head_r, head_cy-head_r, head_cx+head_r, head_cy+head_r], fill=neck)

# Hair (dark, slightly wavy)
hair = (35, 25, 20)
draw.ellipse([head_cx-head_r-5, head_cy-head_r-15, head_cx+head_r+5, head_cy-head_r*0.2], fill=hair)
# hair sides
draw.ellipse([head_cx-head_r-10, head_cy-head_r*0.4, head_cx-head_r*0.4, head_cy+head_r*0.5], fill=hair)
draw.ellipse([head_cx+head_r*0.4, head_cy-head_r*0.4, head_cx+head_r+10, head_cy+head_r*0.5], fill=hair)

# Ears
draw.ellipse([head_cx-head_r-12, head_cy-20, head_cx-head_r+15, head_cy+25], fill=neck)
draw.ellipse([head_cx+head_r-15, head_cy-20, head_cx+head_r+12, head_cy+25], fill=neck)

# Eyes
eye_y = head_cy - 5
eye_l = head_cx - 38
eye_r = head_cx + 38
# whites
draw.ellipse([eye_l-16, eye_y-11, eye_l+16, eye_y+11], fill=(255,255,255))
draw.ellipse([eye_r-16, eye_y-11, eye_r+16, eye_y+11], fill=(255,255,255))
# irises (brown)
draw.ellipse([eye_l-7, eye_y-7, eye_l+7, eye_y+7], fill=(80, 55, 35))
draw.ellipse([eye_r-7, eye_y-7, eye_r+7, eye_y+7], fill=(80, 55, 35))
# pupils
draw.ellipse([eye_l-3, eye_y-3, eye_l+3, eye_y+3], fill=(20,15,10))
draw.ellipse([eye_r-3, eye_y-3, eye_r+3, eye_y+3], fill=(20,15,10))
# highlights
draw.ellipse([eye_l-2, eye_y-4, eye_l+2, eye_y-1], fill=(255,255,255))
draw.ellipse([eye_r-2, eye_y-4, eye_r+2, eye_y-1], fill=(255,255,255))

# Eyebrows
draw.arc([eye_l-20, eye_y-26, eye_l+20, eye_y-8], 180, 360, fill=hair, width=5)
draw.arc([eye_r-20, eye_y-26, eye_r+20, eye_y-8], 180, 360, fill=hair, width=5)

# Nose
draw.arc([head_cx-7, head_cy+8, head_cx+7, head_cy+38], 0, 180, fill=(190,150,110), width=4)

# Mouth (slight smile)
draw.arc([head_cx-28, head_cy+28, head_cx+28, head_cy+62], 20, 160, fill=(150,90,60), width=5)

# --- Coffee cup in hand (bottom right) ---
cup_x, cup_y = S*0.72, S*0.62
# cup body
draw.rounded_rectangle([cup_x-35, cup_y-30, cup_x+35, cup_y+30], radius=15, fill=(255,255,255), outline=(200,200,200), width=3)
# coffee
draw.ellipse([cup_x-30, cup_y-30, cup_x+30, cup_y-10], fill=(90, 60, 30))
# steam
draw.arc([cup_x-15, cup_y-55, cup_x-5, cup_y-30], 180, 360, fill=(255,255,255), width=3)
draw.arc([cup_x+5, cup_y-60, cup_x+15, cup_y-35], 180, 360, fill=(255,255,255), width=3)
# cup handle
draw.arc([cup_x+35, cup_y-20, cup_x+60, cup_y+20], 270, 90, fill=(255,255,255), width=5)

# Hand holding cup
hand = (222, 184, 135)
draw.ellipse([cup_x-15, cup_y+15, cup_x+15, cup_y+45], fill=hand)

# --- Circular mask ---
mask = Image.new('L', (S,S), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.ellipse([0,0,S,S], fill=255)
img.putalpha(mask)

img.save('/Users/p.n.sajganov/.local/share/bitrix24-cowork/cowork/8a10b35ecf8a5851/brazil-news-bot/boris_avatar2.png')
print("Avatar v2 saved")
import os
print("Size:", os.path.getsize('/Users/p.n.sajganov/.local/share/bitrix24-cowork/cowork/8a10b35ecf8a5851/brazil-news-bot/boris_avatar2.png'), "bytes")
