from PIL import Image, ImageDraw, ImageFont
import math

# Canvas 512x512
S = 512
img = Image.new('RGB', (S, S), '#009c3b')
draw = ImageDraw.Draw(img)

# Background: Brazil flag colors - green top, yellow middle, blue bottom
for y in range(S):
    # gradient green -> yellow -> blue
    if y < S*0.45:
        t = y / (S*0.45)
        r = int(0 + (255-0)*t)
        g = int(156 + (223-156)*t)
        b = int(59 + (0-59)*t)
    elif y < S*0.55:
        r, g, b = 255, 223, 0
    else:
        t = (y - S*0.55) / (S*0.45)
        r = int(255 + (0-255)*t)
        g = int(223 + (39-223)*t)
        b = int(0 + (118-0)*t)
    draw.line([(0,y),(S,y)], fill=(r,g,b))

# Draw a circle mask (avatar is circular)
mask = Image.new('L', (S,S), 0)
mask_draw = ImageDraw.Draw(mask)
mask_draw.ellipse([0,0,S,S], fill=255)

# Apply circular mask
img.putalpha(mask)

# Now draw the student on the image
# Face (skin tone - Brazilian)
skin = (222, 184, 135)
# Head - circle
head_center = (S//2, S//2 - 20)
head_r = 130
draw.ellipse([head_center[0]-head_r, head_center[1]-head_r, head_center[0]+head_r, head_center[1]+head_r], fill=skin)

# Hair (dark brown/black)
hair = (40, 30, 25)
# Hair top
draw.ellipse([head_center[0]-head_r, head_center[1]-head_r-10, head_center[0]+head_r, head_center[1]+head_r*0.3], fill=hair)
# Hair sides
draw.ellipse([head_center[0]-head_r-8, head_center[1]-head_r*0.5, head_center[0]-head_r*0.5, head_center[1]+head_r*0.7], fill=hair)
draw.ellipse([head_center[0]+head_r*0.5, head_center[1]-head_r*0.5, head_center[0]+head_r+8, head_center[1]+head_r*0.7], fill=hair)

# Eyes
eye_color = (60, 40, 30)
eye_y = head_center[1] - 10
eye_l = head_center[0] - 45
eye_r = head_center[0] + 45
draw.ellipse([eye_l-18, eye_y-12, eye_l+18, eye_y+12], fill=(255,255,255))
draw.ellipse([eye_r-18, eye_y-12, eye_r+18, eye_y+12], fill=(255,255,255))
draw.ellipse([eye_l-8, eye_y-8, eye_l+8, eye_y+8], fill=eye_color)
draw.ellipse([eye_r-8, eye_y-8, eye_r+8, eye_y+8], fill=eye_color)
# Eye highlights
draw.ellipse([eye_l-3, eye_y-5, eye_l+3, eye_y+1], fill=(255,255,255))
draw.ellipse([eye_r-3, eye_y-5, eye_r+3, eye_y+1], fill=(255,255,255))

# Eyebrows
draw.arc([eye_l-22, eye_y-28, eye_l+22, eye_y-8], 180, 360, fill=hair, width=6)
draw.arc([eye_r-22, eye_y-28, eye_r+22, eye_y-8], 180, 360, fill=hair, width=6)

# Nose
draw.arc([head_center[0]-8, head_center[1]+5, head_center[0]+8, head_center[1]+35], 0, 180, fill=(190,150,110), width=4)

# Smile
draw.arc([head_center[0]-35, head_center[1]+25, head_center[0]+35, head_center[1]+65], 20, 160, fill=(150,90,60), width=6)

# Glasses (student look)
glass_color = (30, 30, 30)
draw.ellipse([eye_l-24, eye_y-16, eye_l+24, eye_y+16], outline=glass_color, width=5)
draw.ellipse([eye_r-24, eye_y-16, eye_r+24, eye_y+16], outline=glass_color, width=5)
draw.line([(eye_l+24, eye_y), (eye_r-24, eye_y)], fill=glass_color, width=5)

# Graduation cap (student)
cap_color = (20, 20, 60)
# Cap board
draw.polygon([(head_center[0]-150, head_center[1]-head_r-20), (head_center[0]+150, head_center[1]-head_r-20), (head_center[0]+110, head_center[1]-head_r-55), (head_center[0]-110, head_center[1]-head_r-55)], fill=cap_color)
# Cap top (mortarboard)
draw.polygon([(head_center[0]-160, head_center[1]-head_r-55), (head_center[0]+160, head_center[1]-head_r-55), (head_center[0]+120, head_center[1]-head_r-90), (head_center[0]-120, head_center[1]-head_r-90)], fill=cap_color)
# Tassel
draw.line([(head_center[0]+120, head_center[1]-head_r-90), (head_center[0]+150, head_center[1]-head_r-40)], fill=(255,223,0), width=6)
draw.ellipse([head_center[0]+140, head_center[1]-head_r-45, head_center[0]+160, head_center[1]-head_r-25], fill=(255,223,0))

# Save as PNG
img.save('/Users/p.n.sajganov/.local/share/bitrix24-cowork/cowork/8a10b35ecf8a5851/brazil-news-bot/boris_avatar.png')
print("Avatar saved: boris_avatar.png")
print("Size:", img.size)
