# -*- coding: utf-8 -*-
"""词框抽取自检：几个典型页面的期望输出。

    python tools/selftest_boxes.py
"""
import sys
from pathlib import Path

import pypdfium2 as pdfium
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).parent))
import build_library as B  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

CASES = [
    (r"E:\apple app\1、G1 有声PDF110本\001 Waking Up.pdf", 3, "G1-001 p4 拟声词在前"),
    (r"E:\apple app\02、GK 有声绘本PDF 70\01 At The Market.pdf", 3, "GK-001 p4 正常"),
    (r"E:\apple app\02、GK 有声绘本PDF 70\45 So Big.pdf", 3, "GK-045 p4 批注"),
    (r"E:\apple app\02、GK 有声绘本PDF 70\45 So Big.pdf", 4, "GK-045 p5 批注"),
    (r"E:\apple app\1、G1 有声PDF110本\080 Brave Taco.pdf", 3, "G1-080 p4 批注"),
    (r"E:\apple app\02、GK 有声绘本PDF 70\19 Playing Dress Up.pdf", 3, "GK-019 p4 拆词"),
    (r"E:\apple app\02、GK 有声绘本PDF 70\01 At The Market.pdf", 10, "GK-001 p11 末页"),
    (r"E:\apple app\1、G1 有声PDF110本\001 Waking Up.pdf", 10, "G1-001 p11 末页"),
]


def run():
    bad = 0
    for path, idx, label in CASES:
        doc = pdfium.PdfDocument(path)
        page = doc[idx]
        cx0, cy0, cx1, cy1 = page.get_cropbox()
        raw = PdfReader(path).pages[idx].extract_text() or ""
        text = B.clean_sentence(B.strip_annotation_lines(raw))
        runs = B.word_boxes(page.get_textpage(), cx0, cy0, cx1 - cx0, cy1 - cy0)
        kept = B.drop_annotation_runs(runs)
        if len(kept) != len(runs):
            text = " ".join(r["w"] for r in kept)
        chosen, pw = B.select_sentence(kept, text)
        ok = bool(pw and pw["words"])
        if not ok:
            bad += 1
        print(f"[{'OK ' if ok else 'FAIL'}] {label}")
        print(f"        text={text[:74]!r}")
        print(f"        words={pw['words'] if pw else None}")
        doc.close()
    print(f"\n{len(CASES) - bad}/{len(CASES)} 通过")
    return bad


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
