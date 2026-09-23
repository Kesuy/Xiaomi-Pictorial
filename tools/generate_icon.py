from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "assets"
OUT.mkdir(parents=True, exist_ok=True)

SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Flat pictorial icon: blue tile + white photo frame + sun/mountains.
margin = 64
draw.rounded_rectangle(
    (margin, margin, SIZE - margin, SIZE - margin),
    radius=210,
    fill=(47, 111, 237, 255),
)

frame = (225, 230, SIZE - 225, 780)
draw.rounded_rectangle(
    frame,
    radius=88,
    outline=(255, 255, 255, 255),
    width=54,
)
draw.ellipse((620, 310, 770, 460), fill=(255, 205, 64, 255))
draw.polygon(
    [(250, 710), (445, 455), (635, 710)],
    fill=(74, 193, 130, 255),
)
draw.polygon(
    [(465, 720), (650, 505), (805, 720)],
    fill=(38, 165, 103, 255),
)
# Redraw the frame over the image shapes for a crisp small-size silhouette.
draw.rounded_rectangle(
    frame,
    radius=88,
    outline=(255, 255, 255, 255),
    width=54,
)

png_path = OUT / "app_icon.png"
ico_path = OUT / "app_icon.ico"
img.save(png_path)
img.save(
    ico_path,
    format="ICO",
    sizes=[
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (96, 96),
        (128, 128),
        (256, 256),
    ],
)

print(f"generated: {png_path} ({SIZE}x{SIZE})")
print(f"generated: {ico_path} (multi-resolution ICO)")
