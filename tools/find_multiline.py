# -*- coding: utf-8 -*-
"""找一页"多行 + 有词级时间戳"的样本，用于跨行空隙的真实点击用例。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]

found = []
for b in books:
    data = json.loads((LIB / "books" / f"{b['id']:02d}.json").read_text(encoding="utf-8"))
    for p in data["pages"]:
        if not p.get("wordBoxes") or not p.get("wordTimes"):
            continue
        boxes = p["wordBoxes"]["boxes"]
        cy = sorted({round((y0 + y1) / 2, 3) for (_, y0, _, y1) in boxes})
        # 行间距明显大于字高才算两行
        if len(cy) < 2:
            continue
        gap = cy[-1] - cy[0]
        h = max(y1 - y0 for (_, y0, _, y1) in boxes)
        if gap < h * 1.3:
            continue
        found.append((b["id"], p["n"], len(boxes), round(gap, 3), round(h, 3)))

print("多行且有逐词时间戳的页：", len(found))
for row in found[:12]:
    print("  book %02d p%d  words=%d  lineGap=%.3f  h=%.3f" % row)
