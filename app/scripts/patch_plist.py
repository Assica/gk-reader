# -*- coding: utf-8 -*-
"""改 Info.plist：key 不存在就新建，存在就覆盖。

为什么不用 plutil：
  · `plutil -replace` 在 key 不存在时**报错退出**（Capacitor 7 模板里
    UIStatusBarHidden / UIRequiresFullScreen 就没有），会直接把 CI 构建搞挂；
  · `plutil` 只有 macOS 有，本地（Windows）没法验证，等于把风险全留给昂贵的 CI。

用标准库 plistlib，写完立刻读回来校验，任何一项不达标就非零退出。

    python app/scripts/patch_plist.py <Info.plist> '<json>'
"""
import json
import plistlib
import sys

LANDSCAPE = [
    "UIInterfaceOrientationLandscapeLeft",
    "UIInterfaceOrientationLandscapeRight",
]

DEFAULTS = {
    "UISupportedInterfaceOrientations": LANDSCAPE,
    "UISupportedInterfaceOrientations~ipad": LANDSCAPE,
    "UIStatusBarHidden": True,
    "UIViewControllerBasedStatusBarAppearance": False,
    "UIRequiresFullScreen": True,
    "NSMicrophoneUsageDescription":
        "跟读练习需要使用麦克风录音，录音只保存在这台 iPad 上，不会上传。",
}


def main():
    # Windows 控制台默认 GBK，打印 ✓ 会 UnicodeEncodeError（macOS 是 UTF-8 不会，
    # 但本地验证时必须能跑通，否则等于没验过）
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    if len(sys.argv) < 2:
        print("用法: patch_plist.py <Info.plist> [额外 JSON]")
        return 2
    path = sys.argv[1]
    want = dict(DEFAULTS)
    if len(sys.argv) > 2 and sys.argv[2].strip():
        want.update(json.loads(sys.argv[2]))

    with open(path, "rb") as f:
        data = plistlib.load(f)
    before = set(data)

    for k, v in want.items():
        data[k] = v

    with open(path, "wb") as f:
        plistlib.dump(data, f, sort_keys=True)

    # 读回来校验：写失败/格式坏了要立刻发现，而不是等到 Xcode 报错
    with open(path, "rb") as f:
        back = plistlib.load(f)

    bad = []
    for k, v in want.items():
        if back.get(k) != v:
            bad.append(f"{k}: 期望 {v!r} 实际 {back.get(k)!r}")
    if bad:
        print("✗ Info.plist 校验失败:")
        for b in bad:
            print("   ", b)
        return 1

    created = sorted(set(want) - before)
    replaced = sorted(set(want) & before)
    print(f"✓ Info.plist: 新建 {len(created)} 项, 覆盖 {len(replaced)} 项")
    if created:
        print("   新建:", ", ".join(created))
    return 0


if __name__ == "__main__":
    sys.exit(main())
