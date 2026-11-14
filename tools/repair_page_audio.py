# -*- coding: utf-8 -*-
"""按"文字长度占比"把音频段分配到页，修 pages[].audio。

原算法按页数取连续窗口，前提是"一页一段"。G1 的页里常有 2 句
（"The rooster wakes up. Cock-a-doodle-doo!"），一段切出来就是 16 段 / 8 页，
窗口法会整体错位。

这里改用比例分配：
  1. 每页权重 = 该页文字的字符数（近似朗读时长）
  2. 把"语音总长"按权重切成 N 段边界
  3. 逐个音频段，按其中点落在哪一段，归给对应页
  4. 每页的时间区间 = 该页第一段的起点 ~ 最后一段的终点

不重新渲染、不重新转码，只改 book.json。

    python tools/repair_page_audio.py            # 全量
    python tools/repair_page_audio.py --dry-run  # 只看统计
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")


def assign(segs, pages):
    """把 segs 分组成 n 页，每页 k 段（k 自动选）。

    G1 的页常含 2 句（"The rooster wakes up. Cock-a-doodle-doo!"），一段对应一页
    会把 16 段硬塞进 8 页，整体错位。这里试 k=1..4，取"页时长最规整"的那种；
    多余的段（片头/片尾）从头部或尾部丢掉，也按规整度选。
    """
    import statistics
    n = len(pages)
    if n == 0 or not segs:
        return None, None

    best = None
    for k in (1, 2, 3, 4):
        need = k * n
        extra = len(segs) - need
        if not (0 <= extra <= 4):
            continue
        for head in range(0, extra + 1):
            cand = segs[head:head + need]
            groups = [[cand[i * k][0], cand[(i + 1) * k - 1][1]] for i in range(n)]
            d = [b - a for a, b in groups]
            if min(d) <= 0:
                continue
            disp = statistics.pstdev(d) / (sum(d) / len(d))
            key = (round(disp, 4), extra, k)
            if best is None or key < best[0]:
                best = (key, groups, k, head)
    if best is None:
        return None, None
    return best[1], {"k": best[2], "head": best[3], "disp": best[0][0]}


def dispersion(mapping):
    import statistics
    d = [max(0.01, b - a) for a, b in mapping]
    m = sum(d) / len(d)
    return statistics.pstdev(d) / m if m else 9.9


def score(segs, pages, mapping):
    """质量分：页文字长度与页音频时长的相关性（越大越好）。"""
    import math
    xs = [len((p.get("text") or "").strip()) for p in pages]
    ys = [max(0.01, b - a) for a, b in mapping]
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def _task(args):
    jf_str, dry = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    segs = book.get("segments") or []
    pages = book["pages"]
    if len(segs) < len(pages):
        return True, f"段数不足 {len(segs)}<{len(pages)}", None

    mapping, how = assign(segs, pages)
    if mapping is None:
        return True, f"无合适分组 segs={len(segs)} pages={len(pages)}", None

    old = [p.get("audio") for p in pages]
    q_new = 1 - dispersion(mapping)
    q_old = 1 - dispersion([tuple(x) for x in old]) if all(old) else -1

    if not dry:
        for p, rng in zip(pages, mapping):
            p["audio"] = rng
        book["alignMethod"] = f"group{how['k']}"
        book["alignQuality"] = round(q_new, 3)
        jf.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, f"k={how['k']} segs={len(segs)} q {q_old:.2f}→{q_new:.2f}", q_new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--series", default="")
    args = ap.parse_args()

    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    tasks = []
    for b in books:
        if args.series and b["series"] != args.series:
            continue
        jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
        tasks.append((b["id"], (str(jf), args.dry_run)))

    print(f"共 {len(tasks)} 本，{args.jobs or default_jobs()} 进程{'（dry-run）' if args.dry_run else ''}",
          flush=True)
    res = run_tasks(tasks, _task, args.jobs or default_jobs())
    bad = [(k, i) for k, ok, i, _ in res if not ok]
    scores = [p for _, ok, _, p in res if ok and p is not None]
    if scores:
        scores.sort()
        print(f"\n相关性: 中位 {scores[len(scores)//2]:.2f}  最低 {scores[0]:.2f}  "
              f"<0.5 的有 {sum(1 for s in scores if s < 0.5)} 本")
    if bad:
        print(f"失败 {len(bad)}: {bad[:8]}")


if __name__ == "__main__":
    main()
