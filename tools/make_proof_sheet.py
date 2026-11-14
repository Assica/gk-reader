# -*- coding: utf-8 -*-
"""Contact sheet proving what one generated book contains: pages + sentences + audio times."""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
FZ = Path(r"C:\Windows\Fonts")
CN, LAT, LATB = "msyh.ttc", "segoeui.ttf", "segoeuib.ttf"

book_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
b = json.loads((LIB / "books" / f"{book_id:02d}.json").read_text(encoding="utf-8"))

COLS, ROWS = 2, 4
TW, TH = 760, 340
PAD, CAP = 22, 96
W = COLS * (TW + PAD) + PAD
H = 150 + ROWS * (TH + CAP + PAD) + PAD
sheet = Image.new("RGB", (W, H), (250, 246, 240))
d = ImageDraw.Draw(sheet)

d.text((PAD + 8, 34), f'{b["id"]:02d}  {b["title"]}', font=ImageFont.truetype(str(FZ / LATB), 44), fill=(40, 34, 30))
d.text((PAD + 10, 92),
       f'Level {b["level"]}   ·   {b["pageCount"]} pages   ·   {b["duration"]}s audio   ·   alignment: {b["alignMethod"]}',
       font=ImageFont.truetype(str(FZ / CN), 24), fill=(140, 128, 118))

for i, p in enumerate(b["pages"]):
    cx = PAD + (i % COLS) * (TW + PAD)
    cy = 150 + (i // COLS) * (TH + CAP + PAD)
    im = Image.open(LIB / p["image"]).convert("RGB")
    im.thumbnail((TW, TH), Image.LANCZOS)
    sheet.paste(im, (cx, cy))
    d.rectangle([cx, cy, cx + im.width, cy + im.height], outline=(226, 216, 206))
    a, e = p["audio"]
    d.text((cx + 4, cy + TH + 8), p["text"], font=ImageFont.truetype(str(FZ / LATB), 26), fill=(40, 34, 30))
    d.text((cx + 4, cy + TH + 46), f'p{p["n"]}   audio {a:.2f}s – {e:.2f}s   ({e-a:.2f}s)',
           font=ImageFont.truetype(str(FZ / CN), 21), fill=(232, 118, 86))

out = Path(r"E:\apple app\docs\library-book-01.png")
sheet.save(out)
print("saved", out, sheet.size)
