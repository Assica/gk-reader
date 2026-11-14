# -*- coding: utf-8 -*-
"""给每页补逐词时间戳（wav2vec2 CTC 强制对齐），多进程。

    python tools/align_library.py                 # 全量，默认 CPU-1 个进程
    python tools/align_library.py --series GK
    python tools/align_library.py --jobs 10
"""
import argparse
import json
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from ctc_align import align  # noqa: E402
from parallel import run_tasks, default_jobs  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(r"E:\apple app")
LIB = ROOT / "library"
WAV16 = ROOT / ".work" / "wav16"
PS = str(ROOT / "tools" / "mf_transcode.ps1")
WAV16.mkdir(parents=True, exist_ok=True)


def to_wav(src: Path, dst: Path) -> bool:
    if dst.exists() and dst.stat().st_size > 20000:
        return True
    subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", PS,
                    "-Source", str(src), "-Dest", str(dst), "-AsWav",
                    "-SampleRate", "16000", "-Channels", "1"],
                   capture_output=True, text=True, errors="ignore")
    return dst.exists() and dst.stat().st_size > 20000


def _task(args):
    """子进程：处理一本书的所有页。"""
    series, no, jf_str, audio_rel, wav_str = args
    jf = Path(jf_str)
    book = json.loads(jf.read_text(encoding="utf-8"))
    if not book.get("hasAudio") or not book.get("audio"):
        return True, "无音频，跳过", (0, 0)

    wav = Path(wav_str)
    if not to_wav(LIB / audio_rel, wav):
        return False, "wav 转换失败", (0, 0)

    with wave.open(str(wav), "rb") as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

    done = miss = 0
    for p in book["pages"]:
        if not p.get("audio"):
            continue
        a, b = p["audio"]
        clip = x[int(a * sr): int(b * sr)]
        if len(clip) < sr // 4:
            continue
        shown = p["wordBoxes"]["words"] if p.get("wordBoxes") else None
        n_show = len(shown) if shown else len(p["text"].split())
        spans = align(clip, p["text"])
        if not spans or len(spans) != n_show:
            p.pop("wordTimes", None)
            miss += 1
            continue
        p["wordTimes"] = spans
        done += 1

    jf.write_text(json.dumps(book, ensure_ascii=False, indent=1), encoding="utf-8")
    return True, f"words={done}/{book['pageCount']}", (done, miss)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", default="")
    ap.add_argument("--jobs", type=int, default=0)
    args = ap.parse_args()
    jobs = args.jobs or default_jobs()

    books = json.loads((LIB / "manifest.json").read_text(encoding="utf-8"))["books"]
    books = [b for b in books if (not args.series or b["series"] == args.series) and b.get("audio")]

    tasks = []
    for b in books:
        jf = LIB / "books" / b["series"] / f'{b["no"]:03d}.json'
        wav = WAV16 / f'{b["series"]}{b["no"]:03d}.wav'
        tasks.append((b["id"], (b["series"], b["no"], str(jf), b["audio"], str(wav))))

    print(f"共 {len(tasks)} 本，{jobs} 个进程并发", flush=True)
    results = run_tasks(tasks, _task, jobs)

    done = sum(p[0] for _, ok, _, p in results if ok and p)
    miss = sum(p[1] for _, ok, _, p in results if ok and p)
    bad = [(k, i) for k, ok, i, _ in results if not ok]
    print(f"\n有逐词时间戳的页: {done}   没有: {miss}")
    if bad:
        print(f"失败 {len(bad)}: {bad[:10]}")


if __name__ == "__main__":
    main()
