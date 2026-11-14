# -*- coding: utf-8 -*-
"""逐词时间戳"体检 + 丢弃"：零插值，只保留真实 CTC 强制对齐的页。

    python tools/fix_wordtimes.py --jobs 10     # 校验并丢弃不合格页
    python tools/fix_wordtimes.py --check      # 只看统计，不写

规则（命中任意一条就删掉该页 wordTimes，整页回退成"读整句"）：
  1. 非句子文本（PDF 印前批注）：text 清空、wordBoxes 置 null、wordTimes 删除，
     页图保留（当无字页）；
  2. wordBoxes 为 null（图上没有逐词热区，wordTimes 没有意义）；
  3. wordTimes 长度 != 词数；
  4. 任何一个词的 span 是 null —— **不插值**，整页丢弃；
  5. 任何一个词的 span < 60ms（人耳分辨不出一个词）；
  6. 任何一个词的 span > 2s（正常英文词到不了 2s，超过就是把静音/别的话
     强行拉进这个词，点下去会放很久）；
  7. 整页词速 < 1 或 > 8 词/秒（文字和音频根本对不上，逐词对齐没有意义）；
  8. span 非正 / 越界 / 非严格递增。

本脚本**不做任何填充**：保留下来的每个数字都直接来自 tools/align_library.py 的
CTC 对齐输出。
"""
import argparse
import io
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")

MIN_SPAN = 0.060          # 人耳能分辨一个词的下限
MAX_SPAN = 2.000          # 正常英文单词的上限（再长就是把别的声音算进来了）
MIN_WPS = 1.0             # 整页词速下限（词/秒）
MAX_WPS = 8.0             # 整页词速上限（词/秒）
REASONS = ("null", "short", "long", "rate", "nobox", "nontext", "count", "missing", "invalid")

# PDF 印前批注（GK-045 p4/p5/p8、G1-080 p4 等）。只匹配明确的制作术语，
# 避免误伤正文里正常的 "art" / "please"。
NON_SENTENCE = re.compile(
    r"(interior\s+art"
    r"|art\s*page"
    r"|art\s*:"
    r"|final\s+illustrations?"
    r"|add\s+a\s+comma"
    r"|delete\s+ornate"
    r"|adjust\s+coat"
    r"|prepress"
    r"|please\s+enlarge"
    r"|overall\s*:)",
    re.I,
)


def is_non_sentence(text):
    return bool(NON_SENTENCE.search(text or ""))


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _span(t):
    """合法 span -> (a, b)；否则 None。"""
    if not isinstance(t, (list, tuple)) or len(t) != 2:
        return None
    a, b = t
    if not (_num(a) and _num(b)) or b <= a:
        return None
    return float(a), float(b)


def _check(page, dur):
    """返回 (reason, n)。reason 为 None 表示这一页可以保留。"""
    ts = page.get("wordTimes")
    n = len(page["wordBoxes"]["words"])
    if ts is None:
        return "missing", n
    if not isinstance(ts, list) or len(ts) != n:
        return "count", n
    if any(t is None for t in ts):
        return "null", n
    spans = [_span(t) for t in ts]
    if any(s is None for s in spans):
        return "invalid", n
    if any(b - a < MIN_SPAN - 1e-9 for a, b in spans):
        return "short", n
    if dur is not None and any(not (0 <= a < b <= dur + 1e-9) for a, b in spans):
        return "invalid", n
    if any(spans[i][1] >= spans[i + 1][0] for i in range(n - 1)):
        return "invalid", n
    if any(b - a > MAX_SPAN + 1e-9 for a, b in spans):
        return "long", n
    if dur is not None and dur > 0:
        wps = n / dur
        if wps < MIN_WPS - 1e-9 or wps > MAX_WPS + 1e-9:
            return "rate", n
    return None, n


def _task(args):
    jf_str, check = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    reasons = {k: 0 for k in REASONS}
    kept = total = 0
    changed = False
    for p in book["pages"]:
        total += 1
        if is_non_sentence(p.get("text")):
            if not check:
                p["text"] = ""
                p["wordBoxes"] = None
                p.pop("wordTimes", None)
                changed = True
            reasons["nontext"] += 1
            continue
        if not p.get("wordBoxes"):
            if p.get("wordTimes") is not None:
                p.pop("wordTimes", None)
                changed = True
            reasons["nobox"] += 1
            continue
        dur = (p["audio"][1] - p["audio"][0]) if p.get("audio") else None
        reason, _ = _check(p, dur)
        if reason:
            p.pop("wordTimes", None)
            reasons[reason] += 1
            changed = True
            continue
        kept += 1

    if not check and changed:
        with io.open(str(jf), "w", encoding="utf-8", newline="") as fh:
            json.dump(book, fh, ensure_ascii=False, indent=1)
    return True, " ".join(f"{k}={v}" for k, v in reasons.items() if v) + f" kept={kept}/{total}", (
        book.get("series"), kept, total, reasons)


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

    per = {}
    bad_books = []
    for key, ok, info, payload in res:
        if not ok or not payload:
            bad_books.append((key, info))
            continue
        series, kept, total, reasons = payload
        a = per.setdefault(series, {"kept": 0, "total": 0, "reasons": {k: 0 for k in REASONS}})
        a["kept"] += kept
        a["total"] += total
        for k, v in reasons.items():
            a["reasons"][k] += v

    print("\n按系列（保留页数 / 总页数，删除原因）：")
    for s in sorted(per):
        a = per[s]
        rs = "  ".join(f"{k}={v}" for k, v in a["reasons"].items() if v) or "无"
        print(f"  {s}: {a['kept']}/{a['total']} ({a['kept'] / max(a['total'], 1):.1%})   {rs}")
    keep = sum(a["kept"] for a in per.values())
    total = sum(a["total"] for a in per.values())
    reasons = {k: sum(a["reasons"][k] for a in per.values()) for k in REASONS}
    print(f"  全库: {keep}/{total} ({keep / max(total, 1):.1%})")
    print("删除原因合计: " + "  ".join(f"{k}={v}" for k, v in reasons.items() if v))
    if bad_books:
        print(f"失败 {len(bad_books)}: {bad_books[:10]}")


if __name__ == "__main__":
    main()
