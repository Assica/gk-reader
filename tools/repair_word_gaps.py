# -*- coding: utf-8 -*-
"""修 wordTimes 的相邻边界：门限要求严格单调（后词起点 > 前词终点）。

align_book 的 tighten 会把相邻词边界设成相等，被 fix_wordtimes 判 invalid。
这里给每个相邻对留 2 ms 间隙，并保证四舍五入后仍在 [0, 页时长] 内。

    python tools/repair_word_gaps.py --jobs 8
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LIB = Path(r"E:\apple app\library")
GAP = 0.002


def _task(args):
    jf_str, dry = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    fixed = 0
    for p in book["pages"]:
        ts = p.get("wordTimes")
        if not ts:
            continue
        dur = p["audio"][1] - p["audio"][0]
        for i in range(1, len(ts)):
            if ts[i] is None or ts[i - 1] is None:
                continue
            if ts[i][0] <= ts[i - 1][1]:
                ts[i][0] = round(ts[i - 1][1] + GAP, 3)
                fixed += 1
            if ts[i][1] <= ts[i][0]:
                ts[i][1] = round(min(dur, ts[i][0] + 0.06), 3)
                if ts[i][1] <= ts[i][0]:
                    ts[i][1] = round(ts[i][0] + 0.001, 3)
        # 末尾越界（四舍五入造成）收一下
        if ts[-1] and ts[-1][1] > dur:
            ts[-1][1] = round(dur, 3)
    if fixed and not dry:
        tmp = jf.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(jf)
    return True, f"fixed={fixed}", fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    tasks = [(b["id"], (str(LIB / "books" / b["series"] / f'{b["no"]:03d}.json'), args.dry_run))
             for b in books]
    jobs = args.jobs or default_jobs(8)
    res = run_tasks(tasks, _task, jobs)
    total = sum(p for _, ok, _, p in res if ok and p)
    print(f"\n共修 {total} 处相邻边界")


if __name__ == "__main__":
    main()
