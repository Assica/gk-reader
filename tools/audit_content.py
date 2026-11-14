# -*- coding: utf-8 -*-
"""内容级体检：100% 覆盖，不看体积看像素和波形。

监工的变异证明了三件事：
  · 把某张封面换成纯白 → 只有 T15 抽样到的那张会红，抽样外的照样绿
  · 把某页页图换成纯白 → 只有 T16 抽样到的那 9 页会红
  · 把一个音频换成等长静音 → **95 项断言全绿**，qa 也不报

所以内容正确性不能靠浏览器抽样，必须在资源侧全量扫。

    python tools/audit_content.py --jobs 8

检查：
  1. 全部 180 张封面 + 1442 张页图：亮度标准差 / 纯白占比（白图 sd≈0）
  2. 全部 180 条音频：解码成 16k 单声道后算 RMS 与峰值（静音 <-50 dBFS）
  3. 全部 1442 页文字：空、乱码、印前批注、超长
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import wave
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
LIB = Path(r"E:\apple app\library")
PS = str(Path(__file__).parent / "mf_transcode.ps1")
BAD_TEXT = re.compile(r"interior art|Art:\s|Adjust|OVERALL:|\.indd|ISBN", re.I)

SD_MIN_COVER = 12.0
SD_MIN_PAGE = 8.0
WHITE_MAX = 0.97
SILENT_DBFS = -50.0


def img_stat(path: Path, size=64):
    with Image.open(path) as im:
        im = im.convert("L").resize((size, size), Image.BOX)
        px = list(im.getdata())
    n = len(px)
    mean = sum(px) / n
    var = sum((p - mean) ** 2 for p in px) / n
    return mean, var ** 0.5, sum(1 for p in px if p > 245) / n


def audio_stat(src: Path, tmp: Path):
    wav = tmp / (src.stem + ".wav")
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS,
                    "-Source", str(src), "-Dest", str(wav), "-AsWav",
                    "-SampleRate", "16000", "-Channels", "1"],
                   capture_output=True, text=True, errors="ignore")
    if not wav.exists():
        return None
    with wave.open(str(wav), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    wav.unlink(missing_ok=True)
    if not len(x):
        return None
    rms = float(np.sqrt(np.mean(x ** 2)))
    peak = float(np.max(np.abs(x)))
    return (20 * np.log10(max(rms, 1e-9)), 20 * np.log10(max(peak, 1e-9)))


def _task(args):
    jf_str, tmp_str = args
    tmp = Path(tmp_str)
    book = json.loads(Path(jf_str).read_text(encoding="utf-8"))
    sid = book["id"]
    bad = []

    # 封面
    cv = LIB / book["cover"]
    if not cv.exists():
        bad.append(("COVER_MISSING", sid, book["cover"]))
    else:
        try:
            mean, sd, white = img_stat(cv)
            if sd < SD_MIN_COVER or white > WHITE_MAX:
                bad.append(("COVER_BLANK", sid, f"sd={sd:.1f} white={white:.2f}"))
        except Exception as e:  # noqa: BLE001
            bad.append(("COVER_ERR", sid, str(e)[:40]))

    # 页图 + 文字
    for p in book["pages"]:
        ip = LIB / p["image"]
        if not ip.exists():
            bad.append(("PAGE_MISSING", sid, f'p{p["n"]}'))
            continue
        try:
            mean, sd, white = img_stat(ip)
            if sd < SD_MIN_PAGE or white > WHITE_MAX:
                bad.append(("PAGE_BLANK", sid, f'p{p["n"]} sd={sd:.1f} white={white:.2f}'))
        except Exception as e:  # noqa: BLE001
            bad.append(("PAGE_ERR", sid, f'p{p["n"]} {str(e)[:30]}'))

        t = (p.get("text") or "").strip()
        if not t:
            bad.append(("NO_TEXT", sid, f'p{p["n"]}'))
        elif BAD_TEXT.search(t):
            bad.append(("BAD_TEXT", sid, f'p{p["n"]}: {t[:36]}'))
        elif re.search(r"[^\x00-\x7f]", t):
            bad.append(("NON_ASCII", sid, f'p{p["n"]}: {t[:36]}'))

    # 音频
    if book.get("audio"):
        ap = LIB / book["audio"]
        if not ap.exists():
            bad.append(("AUDIO_MISSING", sid, book["audio"]))
        else:
            st = audio_stat(ap, tmp)
            if st is None:
                bad.append(("AUDIO_ERR", sid, "解码失败"))
            else:
                rms_db, peak_db = st
                if rms_db < SILENT_DBFS or peak_db < -40:
                    bad.append(("AUDIO_SILENT", sid, f"rms={rms_db:.1f}dB peak={peak_db:.1f}dB"))

    return True, sid, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=0)
    args = ap.parse_args()

    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    tmp = Path(tempfile.mkdtemp(prefix="gk-audit-"))
    tasks = [(b["id"], str(LIB / "books" / b["series"] / f'{b["no"]:03d}.json')) for b in books]
    # tmp 目录按进程区分，避免并发解码撞名
    tasks = [(k, (v, str(tmp / f"w{abs(hash(k)) % 97}"))) for k, v in tasks]
    for i in range(97):
        (tmp / f"w{i}").mkdir(parents=True, exist_ok=True)

    jobs = args.jobs or default_jobs()
    print(f"全量内容体检 {len(tasks)} 本（封面 {len(tasks)} / 页图 1442 / 音频 {len(tasks)}），{jobs} 进程\n",
          flush=True)
    res = run_tasks(tasks, _task, jobs)

    groups = defaultdict(list)
    for _, ok, _, bad in res:
        for kind, sid, detail in bad or []:
            groups[kind].append((sid, detail))

    checks = [
        ("COVER_BLANK", "封面是空白图"),
        ("PAGE_BLANK", "页图是空白图"),
        ("AUDIO_SILENT", "音频是静音"),
        ("NO_TEXT", "页无文字"),
        ("BAD_TEXT", "印前批注/非正文"),
        ("NON_ASCII", "文字含乱码"),
        ("COVER_MISSING", "缺封面"), ("PAGE_MISSING", "缺页图"),
        ("AUDIO_MISSING", "缺音频"), ("COVER_ERR", "封面解码失败"),
        ("PAGE_ERR", "页图解码失败"), ("AUDIO_ERR", "音频解码失败"),
    ]
    print("=== 结果 ===")
    total = 0
    for k, label in checks:
        v = groups.get(k, [])
        total += len(v)
        print(f"{'✅' if not v else '⚠'} {label:14} {len(v):4d}  {v[:3] if v else ''}")
    print(f"\n问题合计 {total}")

    out = LIB.parent / ".work" / "audit-content.json"
    out.write_text(json.dumps(dict(groups), ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"明细 {out}")


if __name__ == "__main__":
    main()
