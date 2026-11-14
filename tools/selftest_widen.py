# -*- coding: utf-8 -*-
"""widen() 自检：随机造 span，断言输出严格单调、每段 >= min_dur、不越界。

    python tools/selftest_widen.py            # 200 组随机用例 + 边界用例
    python tools/selftest_widen.py --cases 500

只需要 numpy，不需要 onnxruntime（ctc_align 已把 ORT 改成懒加载）。
"""
import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ctc_align import widen  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

MIN_DUR = 0.12
TOL = 1e-9


def check(out, spans, clip_len, min_dur, label, require_min=True):
    """返回问题列表；空列表表示通过。"""
    bad = []
    if len(out) != len(spans):
        return [f"{label}: 长度 {len(out)} != {len(spans)}"]
    kept = [i for i, s in enumerate(spans) if s]
    for i, s in enumerate(spans):
        if not s:
            if out[i] is not None:
                bad.append(f"{label}: 第 {i} 段本来是 None，输出 {out[i]}")
            continue
        t = out[i]
        if t is None:
            bad.append(f"{label}: 第 {i} 段丢了")
            continue
        a, b = t
        if not (0.0 - TOL <= a < b <= clip_len + TOL):
            bad.append(f"{label}: 第 {i} 段 [{a}, {b}] 越界/非正 (clip={clip_len})")
        if require_min and b - a < min_dur - TOL:
            bad.append(f"{label}: 第 {i} 段时长 {b - a:.4f} < {min_dur}")
    for k in range(len(kept) - 1):
        i, j = kept[k], kept[k + 1]
        if out[i] is None or out[j] is None:
            continue
        if out[i][1] >= out[j][0]:
            bad.append(f"{label}: 第 {i}/{j} 段没有严格递增 "
                       f"[{out[i][0]}, {out[i][1]}] -> [{out[j][0]}, {out[j][1]}]")
    return bad


def random_case(rng, allow_missing=True):
    n = rng.randint(1, 20)
    spans = []
    t = rng.uniform(0.0, 0.2)
    for _ in range(n):
        d = rng.uniform(0.02, 0.4)
        spans.append([round(t, 3), round(t + d, 3)])
        t += d + rng.uniform(0.0, 0.15)
    if allow_missing:
        for i in range(n):
            if rng.random() < 0.15:
                spans[i] = None
    kept = sum(1 for s in spans if s)
    # 留足空间，保证 min_dur 一定可行
    need = kept * (MIN_DUR + 0.004) + max(kept - 1, 0) * 0.006
    clip_len = max(t + rng.uniform(0.1, 1.0), need + rng.uniform(0.05, 0.5))
    return spans, round(clip_len, 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20261114)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    problems = []
    for c in range(args.cases):
        spans, clip_len = random_case(rng)
        out = widen(spans, clip_len, min_dur=MIN_DUR)
        problems += check(out, spans, clip_len, MIN_DUR, f"随机#{c}")

    # 回归用例：老实现会在这一组上把 b0 推到 a1 之后
    spans = [[0.10, 0.12], [0.13, 0.15], [0.16, 0.40]]
    out = widen(spans, 1.0, min_dur=MIN_DUR)
    problems += check(out, spans, 1.0, MIN_DUR, "短词回归")
    if out[0][1] >= out[1][0]:
        problems.append(f"短词回归: 仍然重叠 {out}")

    # 极短 clip：装不下 min_dur 时也必须严格单调、正长度、落在区间内
    spans = [[i * 0.05, i * 0.05 + 0.04] for i in range(10)]
    out = widen(spans, 0.5, min_dur=MIN_DUR)
    problems += check(out, spans, 0.5, MIN_DUR, "极短clip", require_min=False)

    # 全 None / 空输入
    if widen([None, None], 1.0) != [None, None]:
        problems.append("全 None 输入没有被保留")
    if widen([], 1.0) != []:
        problems.append("空输入没有被保留")

    if problems:
        print(f"FAIL：{len(problems)} 个问题")
        for p in problems[:40]:
            print("  -", p)
        return 1
    print(f"PASS：{args.cases} 组随机 span + 3 组边界用例，"
          f"全部严格单调、每段 >= {MIN_DUR}s、落在 [0, clip_len] 内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
