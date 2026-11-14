# -*- coding: utf-8 -*-
"""全库审计：把"结构合法但内容错"的整类问题一次扫出来。

    python tools/audit_all.py            # 全量
    python tools/audit_all.py --jobs 10

检查项（都是测试套件抓不到的）：
  A 页图是否白图 / 尺寸是否与记录一致
  B 音频是否静音（用码率代理：静音 AAC 的 bytes/sec 明显偏低）
  C 文字是否可疑（印前批注、非 ASCII、超长、整书重复）
  D 结构一致性（manifest ↔ 磁盘、pageCount ↔ pages）
  E 逐词时间戳越界 / 覆盖
"""
import argparse
import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
BAD_TEXT = re.compile(r"interior art|Art:\s|Adjust|OVERALL:|\.indd|ISBN", re.I)


def image_stats(path: Path, size=64):
    """缩略到 64×64 后算亮度均值/标准差/纯白占比。白图 sd≈0。"""
    with Image.open(path) as im:
        im = im.convert("L").resize((size, size), Image.BOX)
        px = list(im.getdata())
    n = len(px)
    mean = sum(px) / n
    var = sum((p - mean) ** 2 for p in px) / n
    white = sum(1 for p in px if p > 245) / n
    return mean, var ** 0.5, white


def _task(args):
    jf_str = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    sid = book["id"]
    issues = []

    pages = book["pages"]
    if len(pages) != book["pageCount"]:
        issues.append(("STRUCT", sid, f'pageCount={book["pageCount"]} 实际={len(pages)}'))

    texts = []
    for p in pages:
        img = LIB / p["image"]
        if not img.exists():
            issues.append(("MISSING", sid, f'p{p["n"]} 缺页图'))
            continue
        try:
            mean, sd, white = image_stats(img)
            if sd < 8 or white > 0.97:
                issues.append(("BLANK_IMG", sid, f'p{p["n"]} sd={sd:.1f} white={white:.2f}'))
            with Image.open(img) as im:
                if abs(im.width - p["w"]) > 2 or abs(im.height - p["h"]) > 2:
                    issues.append(("SIZE", sid, f'p{p["n"]} 记录{p["w"]}x{p["h"]} 实际{im.width}x{im.height}'))
        except Exception as e:  # noqa: BLE001
            issues.append(("IMG_ERR", sid, f'p{p["n"]}: {e}'))

        t = (p.get("text") or "").strip()
        texts.append(t)
        if not t:
            issues.append(("NO_TEXT", sid, f'p{p["n"]} 无文字'))
        elif BAD_TEXT.search(t):
            issues.append(("BAD_TEXT", sid, f'p{p["n"]}: {t[:40]}'))
        elif len(t) > 200:
            issues.append(("LONG_TEXT", sid, f'p{p["n"]} {len(t)} 字'))
        elif re.search(r"[^\x00-\x7f]", t):
            issues.append(("NON_ASCII", sid, f'p{p["n"]}: {t[:40]}'))

        wt = p.get("wordTimes")
        if wt:
            dur = p["audio"][1] - p["audio"][0] if p.get("audio") else None
            nw = len(p["wordBoxes"]["words"]) if p.get("wordBoxes") else len(t.split())
            if len(wt) != nw:
                issues.append(("WT_LEN", sid, f'p{p["n"]} wordTimes={len(wt)} 词={nw}'))
            elif dur and any(not (0 <= a < b <= dur + 0.02) for a, b in wt):
                issues.append(("WT_RANGE", sid, f'p{p["n"]} 越界 dur={dur:.2f}'))

    # 整书重复文本
    dup = [t for t, c in Counter(x for x in texts if x).items() if c > 1]
    if dup:
        issues.append(("DUP_TEXT", sid, f'{len(dup)} 句重复，如 {dup[0][:30]}'))

    # 音频：静音代理 = 码率过低
    if book.get("audio") and book.get("duration"):
        ap = LIB / book["audio"]
        if not ap.exists():
            issues.append(("MISSING", sid, "缺音频"))
        else:
            bps = ap.stat().st_size / max(book["duration"], 0.1)
            if bps < 3000:
                issues.append(("SILENT", sid, f'{bps:.0f} B/s（静音嫌疑）'))

    return True, sid, issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    args = ap.parse_args()

    man = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))
    books = man["books"]
    tasks = [(b["id"], str(LIB / "books" / b["series"] / f'{b["no"]:03d}.json')) for b in books]
    jobs = args.jobs or default_jobs()
    print(f"审计 {len(tasks)} 本，{jobs} 进程", flush=True)
    res = run_tasks(tasks, _task, jobs)

    groups = defaultdict(list)
    for _, ok, _, issues in res:
        for kind, sid, detail in issues or []:
            groups[kind].append((sid, detail))

    print("\n=== 审计结果 ===")
    order = ["STRUCT", "MISSING", "BLANK_IMG", "SIZE", "IMG_ERR", "NO_TEXT",
             "BAD_TEXT", "LONG_TEXT", "NON_ASCII", "DUP_TEXT", "SILENT", "WT_LEN", "WT_RANGE"]
    total = 0
    for k in order:
        v = groups.get(k, [])
        total += len(v)
        flag = "✅" if not v else "⚠"
        print(f"{flag} {k:10} {len(v):4d}  {v[:3] if v else ''}")
    for k in groups:
        if k not in order:
            print(f"   {k:10} {len(groups[k]):4d}  {groups[k][:3]}")
    print(f"\n问题合计 {total} 项")

    (LIB.parent / ".work" / "audit-all.json").write_text(
        json.dumps({k: v for k, v in groups.items()}, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
