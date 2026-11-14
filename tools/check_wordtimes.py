# -*- coding: utf-8 -*-
"""Validate wordTimes against each page's clip; drop the ones that cannot be right."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")

keep = drop = 0
reasons = {"count": 0, "bounds": 0, "order": 0, "long": 0}

for jf in sorted((LIB / "books").glob("*.json")):
    book = json.loads(jf.read_text(encoding="utf-8"))
    changed = False
    for p in book["pages"]:
        ts = p.get("wordTimes")
        if not ts:
            continue
        n = len(p["wordBoxes"]["words"]) if p.get("wordBoxes") else len(p["text"].split())
        dur = p["audio"][1] - p["audio"][0]
        bad = None
        if len(ts) != n:
            bad = "count"
        elif any(t is None or t[0] is None for t in ts):
            bad = "count"
        elif any(not (0 <= t[0] < t[1] <= dur + 0.02) for t in ts):
            bad = "bounds"
        elif any(ts[i][1] > ts[i + 1][0] + 1e-6 for i in range(len(ts) - 1)):
            bad = "order"
        elif any(t[1] - t[0] > max(0.6, 0.55 * dur) for t in ts):
            bad = "long"
        if bad:
            p.pop("wordTimes", None)
            reasons[bad] += 1
            drop += 1
            changed = True
        else:
            keep += 1
    if changed:
        jf.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"pages keeping wordTimes: {keep}   dropped: {drop}   {reasons}")
