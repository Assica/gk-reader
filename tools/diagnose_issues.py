# -*- coding: utf-8 -*-
"""诊断四类数据问题，给出定量画像，作为修改方案的依据。

    python tools/diagnose_issues.py            # 全量统计 + 抽样明细
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
SRC = {
    "GK": Path(r"E:\apple app\02、GK 有声绘本PDF 70"),
    "G1": Path(r"E:\apple app\1、G1 有声PDF110本"),
}
SENT = re.compile(r"[.!?]+")


def sents(t):
    return [s for s in (x.strip() for x in SENT.split(t or "")) if s]


def main():
    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    long_pages, nobox_pages, dup_books = [], [], []
    no_text = []

    for b in books:
        jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
        book = json.loads(jf.read_text(encoding="utf-8"))
        texts = []
        for p in book["pages"]:
            t = (p.get("text") or "").strip()
            texts.append(t)
            if not t:
                no_text.append((b["id"], p["n"]))
                continue
            if len(t) > 200:
                long_pages.append({
                    "id": b["id"], "n": p["n"], "chars": len(t),
                    "words": len(t.split()), "sents": len(sents(t)),
                    "dur": (p["audio"][1] - p["audio"][0]) if p.get("audio") else None,
                    "head": t[:90],
                })
            if not p.get("wordBoxes"):
                nobox_pages.append({"id": b["id"], "n": p["n"], "chars": len(t),
                                    "head": t[:70]})
        dup = [t for t, c in Counter(x for x in texts if x).items() if c > 1]
        if dup:
            dup_books.append({"id": b["id"], "dups": [d[:60] for d in dup][:3],
                              "counts": [texts.count(d) for d in dup][:3]})

    print(f"总页 1442 | 超长页 {len(long_pages)} | 无词框页 {len(nobox_pages)} | "
          f"重复句书 {len(dup_books)} | 无字页 {len(no_text)}")

    print("\n=== A. 超长文字页 ===")
    if long_pages:
        c = Counter(x["sents"] for x in long_pages)
        print(f"  句数分布: {dict(sorted(c.items()))}")
        print(f"  字符数: 最小 {min(x['chars'] for x in long_pages)} "
              f"最大 {max(x['chars'] for x in long_pages)}")
        play = sum(1 for x in long_pages if re.search(r"The Play|Characters|Narrator", x["head"], re.I))
        print(f"  看起来是剧本页: {play}")
        for x in long_pages[:8]:
            print(f"    {x['id']} p{x['n']}  {x['chars']}字/{x['words']}词/{x['sents']}句 "
                  f"dur={x['dur']}  {x['head'][:70]!r}")

    print("\n=== B. 无词框页 ===")
    if nobox_pages:
        by_book = Counter(x["id"] for x in nobox_pages)
        print(f"  涉及 {len(by_book)} 本，最多的: {by_book.most_common(6)}")
        print(f"  字符数中位 {sorted(x['chars'] for x in nobox_pages)[len(nobox_pages)//2]}")
        for x in nobox_pages[:8]:
            print(f"    {x['id']} p{x['n']}  {x['chars']}字  {x['head']!r}")

    print("\n=== C. 重复句 ===")
    for x in dup_books[:6]:
        print(f"    {x['id']}  出现次数 {x['counts']}  {x['dups'][0]!r}")

    print("\n=== D. 无字页 ===")
    print(f"    {no_text}")

    out = Path(r"E:\apple app\.work") / "diagnose.json"
    out.write_text(json.dumps({"long": long_pages, "nobox": nobox_pages,
                               "dup": dup_books, "notext": no_text},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n明细 {out}")


if __name__ == "__main__":
    main()
