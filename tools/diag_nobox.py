# -*- coding: utf-8 -*-
"""给"没有词框"的页分类，找出失败模式，而不是靠猜。

    python tools/diag_nobox.py
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import pypdfium2 as pdfium  # noqa: E402
from pypdf import PdfReader  # noqa: E402
import build_library as B  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
SRC = {
    "GK": Path(r"E:\apple app\02、GK 有声绘本PDF 70"),
    "G1": Path(r"E:\apple app\1、G1 有声PDF110本"),
}


def _norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def main():
    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    kinds = Counter()
    samples = {}
    total = 0

    for b in books:
        jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
        book = json.loads(jf.read_text(encoding="utf-8"))
        bad = [p for p in book["pages"] if not p.get("wordBoxes")]
        if not bad:
            continue
        cands = [p for p in SRC[b["series"]].glob("*.pdf")
                 if "(" not in p.stem and p.stem.split()[0].lstrip("C G").endswith(f'{b["no"]:03d}')]
        cands = [p for p in cands if B.num_from(p.stem) == b["no"]]
        if not cands:
            continue
        try:
            doc = pdfium.PdfDocument(str(cands[0]))
            reader = PdfReader(str(cands[0]))
        except Exception:  # noqa: BLE001
            continue

        for p in bad:
            total += 1
            idx = p["n"] - 1
            page = doc[idx]
            cx0, cy0, cx1, cy1 = page.get_cropbox()
            runs = B.word_boxes(page.get_textpage(), cx0, cy0, cx1 - cx0, cy1 - cy0)
            text = (p.get("text") or "").strip()
            if not runs:
                k = "A 视觉层没有任何文字（矢量字/纯图）"
            elif not text:
                k = "B 文字为空"
            elif not p.get("textBox"):
                k = "C 有文字但整句都没匹配上"
            else:
                k = "D 匹配到整句但词级合并不出来"
            kinds[k] += 1
            if k not in samples:
                samples[k] = {
                    "book": b["id"], "n": p["n"], "runs": len(runs),
                    "text": text[:70], "runs_head": " ".join(r["w"] for r in runs)[:70],
                    "has_textbox": bool(p.get("textBox")),
                }
        doc.close()

    print(f"无词框页合计 {total}")
    for k, v in kinds.most_common():
        print(f"  {k}: {v}")
    print("\n样本：")
    for k, s in samples.items():
        print(f"\n{k}")
        print(f"  {s}")
    (LIB.parent / ".work" / "nobox-kinds.json").write_text(
        json.dumps({"kinds": dict(kinds), "samples": samples}, ensure_ascii=False, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
