# -*- coding: utf-8 -*-
"""Draw a waveform with the aligner's word boundaries — proof that a tap hits the word."""
import json
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"E:\apple app")
LIB = ROOT / "library"
WAV = ROOT / ".work" / "wav16"
FZ = Path(r"C:\Windows\Fonts")
CN = ImageFont.truetype(str(FZ / "msyh.ttc"), 20)
LATB = ImageFont.truetype(str(FZ / "segoeuib.ttf"), 26)
CNB = ImageFont.truetype(str(FZ / "msyhbd.ttc"), 22)


def panel(book_id, page_n, y0):
    book = json.loads((LIB / "books" / f"{book_id:02d}.json").read_text(encoding="utf-8"))
    p = next(x for x in book["pages"] if x["n"] == page_n)
    with wave.open(str(WAV / f"{book_id:02d}.wav"), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    a, b = p["audio"]
    clip = x[int(a * sr): int(b * sr)]
    dur = len(clip) / sr

    W, H = 1600, 190
    img = Image.new("RGB", (W, H), (253, 248, 242))
    d = ImageDraw.Draw(img)
    mid = 96
    # waveform
    cols = W - 80
    step = max(1, len(clip) // cols)
    for i in range(cols):
        seg = clip[i * step:(i + 1) * step]
        if not len(seg):
            break
        amp = float(np.abs(seg).max())
        h = int(amp * 70)
        d.line([(40 + i, mid - h), (40 + i, mid + h)], fill=(120, 100, 90))
    d.line([(40, mid), (40 + cols, mid)], fill=(200, 190, 180))

    words = p["wordBoxes"]["words"] if p["wordBoxes"] else p["text"].split()
    times = p.get("wordTimes") or []
    for word, (t0, t1) in zip(words, times):
        xa = 40 + int(t0 / dur * cols)
        xb = 40 + int(t1 / dur * cols)
        d.rectangle([xa, 14, xb, 178], outline=(232, 118, 86), width=2)
        label = word
        f = LATB if len(label) < 10 else ImageFont.truetype(str(FZ / "segoeui.ttf"), 18)
        tw = d.textlength(label, font=f)
        d.text((xa + max(0, (xb - xa - tw) / 2), 34), label, font=f, fill=(58, 46, 40))
        d.text((xa + 2, 156), f"{t0:.2f}–{t1:.2f}", font=CN, fill=(140, 128, 118))
    d.text((40, 4), f'{book_id:02d} {book["title"]} · p{page_n} · {p["text"]}', font=CN, fill=(58, 46, 40))
    return img


canvas = Image.new("RGB", (1600, 190 * 3 + 60), (255, 255, 255))
chosen = []
for bid in range(1, 71):
    if len(chosen) >= 3:
        break
    b = json.loads((LIB / "books" / f"{bid:02d}.json").read_text(encoding="utf-8"))
    p = next((x for x in b["pages"] if x.get("wordTimes")), None)
    if p:
        chosen.append((bid, p["n"]))
print("panels:", chosen)
for k, (bid, pn) in enumerate(chosen):
    canvas.paste(panel(bid, pn, 0), (0, 40 + k * (190 + 10)))
out = ROOT / "docs" / "word-alignment.png"
canvas.save(out)
print("saved", out, canvas.size)
