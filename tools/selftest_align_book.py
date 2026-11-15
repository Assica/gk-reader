# -*- coding: utf-8 -*-
"""align_book 自检：在临时副本上跑，验证 wordTimes 是页相对时间且不越界。

    python tools/selftest_align_book.py GK-001 G1-107
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import align_book as A  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LIB = Path(r"E:\apple app\library")


def check(bid: str) -> bool:
    s, n = bid.split("-")
    src = LIB / "books" / s / f"{int(n):03d}.json"
    tmp = Path(tempfile.mkdtemp(prefix="ab-check-"))
    dst = tmp / f"{bid}.json"
    shutil.copy2(src, dst)

    ok, info, demo = A._task((str(dst), False))
    d = json.loads(dst.read_text(encoding="utf-8"))
    bad = []
    for p in d["pages"]:
        dur = p["audio"][1] - p["audio"][0]
        times = p.get("wordTimes") or []
        if len(times) != len((p.get("wordBoxes") or {}).get("words", []) or p["text"].split()):
            bad.append((p["n"], "len", len(times)))
            continue
        for t in times:
            if t and (t[0] < -0.001 or t[1] > dur + 0.05):
                bad.append((p["n"], t, round(dur, 2)))
                break
    withwt = sum(1 for p in d["pages"] if p.get("wordTimes"))
    print(f"{bid}: {info}")
    print(f"    有词时间戳页 {withwt}/{len(d['pages'])} | 越界/长度不符 {len(bad)} {bad[:3]}")
    p0 = d["pages"][0]
    print(f"    p{p0['n']} audio={p0['audio']} 时长={p0['audio'][1]-p0['audio'][0]:.2f}s")
    print(f"    wordTimes 前 3: {(p0.get('wordTimes') or [])[:3]}")
    shutil.rmtree(tmp, ignore_errors=True)
    return ok and not bad


if __name__ == "__main__":
    ids = sys.argv[1:] or ["GK-001", "G1-107"]
    results = [check(i) for i in ids]
    print("\n通过" if all(results) else "\n有失败")
    sys.exit(0 if all(results) else 1)
