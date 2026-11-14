# -*- coding: utf-8 -*-
"""探 G1/G2 的 PDF 结构：页数、版式、文字层，判断能否复用 GK 的流水线。"""
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"E:\apple app")

SETS = {
    "G1": (ROOT / "1、G1 有声PDF110本", r"^(\d{3})\s"),
    "G2": (ROOT / "2、G2 有声绘本PDF118", r"^(\d{3})\s"),
}


def dedupe(files):
    """同名 (1) 副本只留一份。"""
    uniq = {}
    for p in files:
        stem = re.sub(r"\(\d+\)$", "", p.stem).rstrip()
        if stem not in uniq:
            uniq[stem] = p
    return uniq


for key, (d, pat) in SETS.items():
    files = [p for p in sorted(d.glob("*.pdf")) if not re.search(r"\(\d+\)$", p.stem)]
    print(f"\n===== {key}: {len(files)} 本（去重后） =====")
    if not files:
        continue

    # 页数分布 + 是否每页有文字
    pages_dist = {}
    no_text = 0
    sizes = set()
    for p in files:
        try:
            r = PdfReader(str(p))
            n = len(r.pages)
            pages_dist[n] = pages_dist.get(n, 0) + 1
            for pg in r.pages:
                if not (pg.extract_text() or "").strip():
                    no_text += 1
        except Exception as e:  # noqa: BLE001
            print("  !! 解析失败", p.name, e)
    print("  页数分布:", dict(sorted(pages_dist.items())))
    print("  完全没有文字层的页数:", no_text)

    # 抽 3 本看每页文字
    for p in files[:2] + files[len(files) // 2: len(files) // 2 + 1]:
        r = PdfReader(str(p))
        print(f"\n  --- {p.name}  ({len(r.pages)} 页)")
        for i, pg in enumerate(r.pages):
            t = re.sub(r"\s+", " ", (pg.extract_text() or "")).strip()
            mb = pg.mediabox
            print(f"    p{i+1:2d} [{float(mb.width):.0f}x{float(mb.height):.0f}] {t[:70]!r}")
