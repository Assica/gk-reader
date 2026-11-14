# -*- coding: utf-8 -*-
"""Vocabulary stats from the built library — feeds the mini-dictionary and word-audio plan."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]

tok = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")
forms = Counter()
n_sent = 0
n_tok = 0
per_book = {}
for b in books:
    data = json.loads((LIB / "books" / f"{b['id']:02d}.json").read_text(encoding="utf-8"))
    ws = []
    for p in data["pages"]:
        n_sent += 1
        ws += [w.lower() for w in tok.findall(p["text"])]
    forms.update(ws)
    n_tok += len(ws)
    per_book[b["id"]] = len(set(ws))

print(f"sentences: {n_sent}")
print(f"word tokens (读出来的词次): {n_tok}")
print(f"distinct word forms: {len(forms)}")
print(f"per book distinct: min={min(per_book.values())} median={sorted(per_book.values())[len(per_book)//2]} max={max(per_book.values())}")
print("\ntop 25:", ", ".join(f"{w}({c})" for w, c in forms.most_common(25)))
print("\nhapax (只出现一次的词):", sum(1 for c in forms.values() if c == 1))
print("\nlongest words:", ", ".join(sorted(forms, key=len, reverse=True)[:10]))

# a-f / h-n / o-z buckets for a 3-page dictionary
import string
buckets = {"a-f": 0, "g-m": 0, "n-t": 0, "u-z": 0}
for w in forms:
    c = w[0]
    if c <= "f":
        buckets["a-f"] += 1
    elif c <= "m":
        buckets["g-m"] += 1
    elif c <= "t":
        buckets["n-t"] += 1
    else:
        buckets["u-z"] += 1
print("\nby initial:", buckets)
