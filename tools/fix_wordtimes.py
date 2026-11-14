# -*- coding: utf-8 -*-
"""补全 wordTimes 里的 null，并校验；不可信的页直接丢掉 wordTimes（回落到读整句）。

    python tools/fix_wordtimes.py            # 补 null + 校验
    python tools/fix_wordtimes.py --check    # 只看统计
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")


def _task(args):
    jf_str, check = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    filled = dropped = 0

    for p in book["pages"]:
        ts = p.get("wordTimes")
        if not ts:
            continue
        dur = (p["audio"][1] - p["audio"][0]) if p.get("audio") else None

        # 1) 补 null：用左右邻居插值，最短 0.12s，最长不超过空隙
        for i, t in enumerate(ts):
            if t is not None and t[0] is not None:
                continue
            lo = next((ts[j][1] for j in range(i - 1, -1, -1) if ts[j]), None)
            hi = next((ts[j][0] for j in range(i + 1, len(ts)) if ts[j]), None)
            a = lo if lo is not None else 0.0
            b = hi if hi is not None else (a + 0.2)
            if b - a < 0.12:
                b = a + 0.12
            ts[i] = [round(a, 3), round(b, 3)]
            filled += 1

        # 2) 校验：长度对、不越界、单调、单跨度合理
        n = len(p["wordBoxes"]["words"]) if p.get("wordBoxes") else len(p["text"].split())
        bad = (
            len(ts) != n
            or any(t is None for t in ts)
            or (dur is not None and any(not (0 <= t[0] < t[1] <= dur + 0.02) for t in ts))
            or any(ts[i][1] > ts[i + 1][0] + 1e-6 for i in range(len(ts) - 1))
            or (dur is not None and any(t[1] - t[0] > max(0.6, 0.55 * dur) for t in ts))
        )
        if bad:
            p.pop("wordTimes", None)
            dropped += 1

    if not check and (filled or dropped):
        jf.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, f"filled={filled} dropped={dropped}", (filled, dropped)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    tasks = [(b["id"], (str(LIB / "books" / b["series"] / f'{b["no"]:03d}.json'), args.check))
             for b in books]
    jobs = args.jobs or default_jobs()
    print(f"共 {len(tasks)} 本，{jobs} 进程{'（check）' if args.check else ''}", flush=True)
    res = run_tasks(tasks, _task, jobs)
    filled = sum(p[0] for _, ok, _, p in res if ok and p)
    dropped = sum(p[1] for _, ok, _, p in res if ok and p)
    print(f"\n补全 {filled} 个词，丢弃 {dropped} 页的逐词时间戳")


if __name__ == "__main__":
    main()
