# -*- coding: utf-8 -*-
"""多进程执行小工具：给 build_library / align_library 共用。"""
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed


def default_jobs(cap: int = 12) -> int:
    """留一个核给系统，最多 12 个进程。"""
    n = os.cpu_count() or 4
    return max(1, min(cap, n - 1))


def run_tasks(tasks, worker, jobs: int, label: str = "", retries: int = 1):
    """并发跑 tasks，边跑边打印进度。

    tasks   : 可迭代的 (key, args) 二元组
    worker  : 模块级函数，接收 args，返回 (ok: bool, info: str, payload)
    返回    : [(key, ok, info, payload)]
    """
    tasks = list(tasks)
    total = len(tasks)
    if jobs <= 1:
        out = []
        t0 = time.time()
        for i, (key, args) in enumerate(tasks, 1):
            ok, info, payload = worker(args)
            out.append((key, ok, info, payload))
            _say(i, total, t0, key, ok, info, label)
        return out

    out = []
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        futures = {ex.submit(worker, args): (key, args) for key, args in tasks}
        for fut in as_completed(futures):
            key, args = futures[fut]
            try:
                ok, info, payload = fut.result()
            except Exception as e:  # noqa: BLE001
                ok, info, payload = False, f"{type(e).__name__}: {e}", None
                if retries > 0:
                    # 失败重试一次（转码偶发失败）
                    try:
                        ok, info, payload = worker(args)
                    except Exception as e2:  # noqa: BLE001
                        ok, info = False, f"{type(e2).__name__}: {e2}"
            done += 1
            out.append((key, ok, info, payload))
            _say(done, total, t0, key, ok, info, label)
    return out


def _say(i, total, t0, key, ok, info, label):
    el = time.time() - t0
    eta = (el / i) * (total - i)
    flag = "" if ok else "  ✗"
    sys.stdout.write(f"[{i:3d}/{total}] {el:5.0f}s ETA {eta/60:4.1f}min  "
                     f"{key}  {info}{flag}\n")
    sys.stdout.flush()
