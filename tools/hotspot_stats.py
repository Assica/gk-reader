# -*- coding: utf-8 -*-
"""复算 text 热区几何：按 web/app.js 的 layoutOverlay 逻辑，逐页统计宽度与重叠。

对应 JS：
  medH   = 词框高度中位数
  分行    = 纵向中心差 > medH*0.65 换行
  横向    = 与左邻居取中线，与右邻居取中线（行首/行尾各留 0.004 余量）
  纵向    = 中心不变，高度 max(44px, 词高 + 0.02)
"""
import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]


def rects(page, disp_w):
    boxes = page["wordBoxes"]["boxes"]
    n = len(boxes)
    hs = sorted(b[3] - b[1] for b in boxes)
    med = hs[n // 2] or 0.05
    order = sorted(range(n), key=lambda k: boxes[k][1] + boxes[k][3])
    lines = []
    for k in order:
        cy = (boxes[k][1] + boxes[k][3]) / 2
        if lines and abs(lines[-1]["cy"] - cy) <= med * 0.65:
            lines[-1]["items"].append(k)
            lines[-1]["cy"] = (lines[-1]["cy"] * (len(lines[-1]["items"]) - 1) + cy) / len(lines[-1]["items"])
        else:
            lines.append({"cy": cy, "items": [k]})
    # 图片显示尺寸：宽度固定，高度按页面比例
    pw, ph = page["w"], page["h"]
    disp_h = disp_w * ph / pw
    out = []
    for ln in lines:
        ln["items"].sort(key=lambda k: boxes[k][0])
        for i, k in enumerate(ln["items"]):
            x0, y0, x1, y1 = boxes[k]
            prev = boxes[ln["items"][i - 1]] if i > 0 else None
            nxt = boxes[ln["items"][i + 1]] if i < len(ln["items"]) - 1 else None
            L = max(0.0, (prev[2] + x0) / 2 if prev else x0 - 0.004)
            R = min(1.0, (x1 + nxt[0]) / 2 if nxt else x1 + 0.004)
            bh = max(44 / disp_h, (y1 - y0) + 0.02)
            cy = (y0 + y1) / 2
            T = max(0.0, cy - bh / 2)
            B = min(1.0, max(T + 0.01, cy + bh / 2))
            out.append({"k": k, "x": L * disp_w, "y": T * disp_h,
                        "w": max(8, (R - L) * disp_w), "h": (B - T) * disp_h})
    return out, disp_h


def stats(disp_w, label):
    total = narrow44 = narrow30 = 0
    narrowest = (999, None)
    pages_overlap = 0
    pages_with_boxes = 0
    worst = (0, None)
    for b in books:
        data = json.loads((LIB / "books" / f"{b['id']:02d}.json").read_text(encoding="utf-8"))
        for p in data["pages"]:
            if not p.get("wordBoxes"):
                continue
            pages_with_boxes += 1
            rs, _ = rects(p, disp_w)
            total += len(rs)
            for r in rs:
                if r["w"] < 44:
                    narrow44 += 1
                if r["w"] < 30:
                    narrow30 += 1
                if r["w"] < narrowest[0]:
                    narrowest = (r["w"], f'{b["id"]:02d} p{p["n"]} word#{r["k"]}')
            hit = 0
            for i in range(len(rs)):
                for j in range(i + 1, len(rs)):
                    a, c = rs[i], rs[j]
                    ox = min(a["x"] + a["w"], c["x"] + c["w"]) - max(a["x"], c["x"])
                    oy = min(a["y"] + a["h"], c["y"] + c["h"]) - max(a["y"], c["y"])
                    if ox > 0.5 and oy > 0.5:
                        hit += 1
                        if ox * oy > worst[0]:
                            worst = (ox * oy, f'{b["id"]:02d} p{p["n"]}')
            if hit:
                pages_overlap += 1
    print(f"\n[{label}] 图宽 {disp_w}px")
    print(f"  有词框的页: {pages_with_boxes}   词框总数: {total}")
    print(f"  宽度 <44px: {narrow44} ({narrow44/total:.1%})   <30px: {narrow30} ({narrow30/total:.1%})")
    print(f"  最窄: {narrowest[0]:.1f}px @ {narrowest[1]}")
    print(f"  存在热区重叠的页: {pages_overlap}/{pages_with_boxes} ({pages_overlap/pages_with_boxes:.1%})")
    print(f"  最大重叠面积: {worst[0]:.0f} px² @ {worst[1]}")


stats(1142, "iPad 1194×834")
stats(972, "iPad 6 1024×768")
stats(1180 * 0.978, "iPad 11 1180×820")
