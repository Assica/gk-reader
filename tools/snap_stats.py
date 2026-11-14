# -*- coding: utf-8 -*-
"""就近吸附之后的命中质量复算。

旧模型（矩形命中）的问题：
  - 窄词矩形只有 20–23px 宽，手指点上去会落到邻居；
  - 把高度撑到 44px 又会让相邻行重叠，重叠带由 DOM 后插入者胜出。

新模型（就近吸附）的判定：
  1. 词框内的点，必须解析到这个词（错词率 = 0）；
  2. 文字区内不得出现"点了没反应"的死区（只能落在句子兜底上）；
  3. 同一页任意点，只能解析到唯一一个词（不存在歧义带）。
"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
SNAP_R = 40
TEXT_FACTOR = 1.8
VIEWS = [(1142, "1194×834"), (972, "iPad 6 1024×768"), (1154, "iPad 11")]


def page_points(page, disp_w):
    """返回 [(k, px, py)] 采样点：每个词框内 5×5 网格 + 文字区内 20px 网格。"""
    boxes = page["wordBoxes"]["boxes"]
    disp_h = disp_w * page["h"] / page["w"]
    pts = []
    for k, (x0, y0, x1, y1) in enumerate(boxes):
        for i in range(5):
            for j in range(5):
                pts.append((k,
                            (x0 + (x1 - x0) * (i + 0.5) / 5) * disp_w,
                            (y0 + (y1 - y0) * (j + 0.5) / 5) * disp_h))
    return pts, boxes, disp_h


def resolve(px, py, centers, boxes, textbox, disp_w, disp_h):
    """与 web/app.js 的 nearestWord 同一套规则：先判词框，再就近吸附。"""
    hit, hitd = -1, 1e18
    if boxes:
        for k, (x0, y0, x1, y1) in enumerate(boxes):
            if x0 * disp_w <= px <= x1 * disp_w and y0 * disp_h <= py <= y1 * disp_h:
                dx = (x0 + x1) / 2 * disp_w - px
                dy = (y0 + y1) / 2 * disp_h - py
                d = dx * dx + dy * dy
                if d < hitd:
                    hitd, hit = d, k
        if hit >= 0:
            return hit
    best, bestd = -1, 1e18
    for k, cx, cy in centers:
        d = ((cx * disp_w - px) ** 2 + (cy * disp_h - py) ** 2) ** 0.5
        if d < bestd:
            bestd, best = d, k
    if best < 0:
        return -1
    limit = SNAP_R
    if textbox:
        m = 16
        if (textbox[0] * disp_w - m <= px <= textbox[2] * disp_w + m and
                textbox[1] * disp_h - m <= py <= textbox[3] * disp_h + m):
            limit = SNAP_R * TEXT_FACTOR
    return best if bestd <= limit else -1


def main():
    for disp_w, label in VIEWS:
        box_total = box_wrong = 0
        worst = []
        dead = 0
        text_pts = 0
        nearest_gap = []
        for b in books:
            data = json.loads((LIB / "books" / f"{b['id']:02d}.json").read_text(encoding="utf-8"))
            for p in data["pages"]:
                if not p.get("wordBoxes"):
                    continue
                pts, boxes, disp_h = page_points(p, disp_w)
                centers = [(k, (x0 + x1) / 2, (y0 + y1) / 2) for k, (x0, y0, x1, y1) in enumerate(boxes)]
                for k, px, py in pts:
                    box_total += 1
                    got = resolve(px, py, centers, boxes, p.get("textBox"), disp_w, disp_h)
                    if got != k:
                        box_wrong += 1
                        if len(worst) < 5:
                            worst.append((b["id"], p["n"], k, got))
                # 词间最近距离（衡量 Voronoi 内切半径）
                for i, (k, cx, cy) in enumerate(centers):
                    dmin = min(((cx - c2x) ** 2 + (cy - c2y) ** 2) ** 0.5
                               for j, (_, c2x, c2y) in enumerate(centers) if j != i) if len(centers) > 1 else 1
                    nearest_gap.append(dmin * disp_w / 2)
                # 文字区死区：网格采样，落在文字区却吸附不到任何词
                tb = p.get("textBox")
                if tb:
                    for i in range(11):
                        for j in range(11):
                            px = (tb[0] + (tb[2] - tb[0]) * i / 10) * disp_w
                            py = (tb[1] + (tb[3] - tb[1]) * j / 10) * disp_h
                            text_pts += 1
                            got = resolve(px, py, centers, boxes, tb, disp_w, disp_h)
                            if got < 0:
                                dead += 1
        nearest_gap.sort()
        print(f"\n[{label}] 图宽 {disp_w}px")
        print(f"  词框内采样点误命中: {box_wrong}/{box_total} ({box_wrong/max(box_total,1):.3%})"
              + (f"  例: {worst}" if worst else ""))
        print(f"  文字区死区: {dead}/{text_pts} ({dead/max(text_pts,1):.3%})")
        print(f"  有效命中半径（到最近词中心的一半）中位数 {nearest_gap[len(nearest_gap)//2]:.1f}px, "
              f"最小 {nearest_gap[0]:.1f}px, <20px 占比 "
              f"{sum(1 for g in nearest_gap if g < 20)/len(nearest_gap):.1%}")


if __name__ == "__main__":
    main()
