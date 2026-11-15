# -*- coding: utf-8 -*-
"""在 Windows 上模拟 CI 的关键步骤，尽量把失败提前暴露。

    python tools/preflight_ci.py

不模拟的部分：xcodebuild / pod install（需要 macOS）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(r"E:\apple app")
APP = ROOT / "app"
WF = ROOT / ".github" / "workflows" / "ios.yml"

ok_all = True


def check(name, cond, detail=""):
    global ok_all
    mark = "✅" if cond else "❌"
    print(f"{mark} {name}" + (f"  — {detail}" if detail else ""))
    if not cond:
        ok_all = False
    return cond


print("=== 1. 仓库文件 ===")
check("library/manifest.json 存在", (ROOT / "library/manifest.json").exists())
check("app/package-lock.json 存在", (APP / "package-lock.json").exists())
check("app/capacitor.config.json 存在", (APP / "capacitor.config.json").exists())
check("app/scripts/build-www.mjs 存在", (APP / "scripts/build-www.mjs").exists())
check("app/scripts/patch-ios.mjs 存在", (APP / "scripts/patch-ios.mjs").exists())
check("app/scripts/patch_plist.py 存在", (APP / "scripts/patch_plist.py").exists())

print("\n=== 2. package.json / lock 一致性 ===")
pkg = json.loads((APP / "package.json").read_text(encoding="utf-8"))
lock = json.loads((APP / "package-lock.json").read_text(encoding="utf-8"))
pk = lock.get("packages", {})
deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
missing = [d for d in deps if f"node_modules/{d}" not in pk]
check("所有依赖都在 lock 里", not missing, f"缺 {missing}" if missing else "")
# lock 里根包声明的依赖要和 package.json 一致（npm ci 会校验）
root_pkg = pk.get("", {})
declared = {**root_pkg.get("dependencies", {}), **root_pkg.get("devDependencies", {})}
check("lock 根包依赖 == package.json", declared == deps,
      "" if declared == deps else f"lock={sorted(declared)} pkg={sorted(deps)}")

print("\n=== 3. capacitor 配置 ===")
cfg = json.loads((APP / "capacitor.config.json").read_text(encoding="utf-8"))
check("webDir == www", cfg.get("webDir") == "www", cfg.get("webDir"))
check("appId 合法", bool(re.fullmatch(r"[A-Za-z][\w.]*", cfg.get("appId", ""))), cfg.get("appId"))

print("\n=== 4. www 产物 ===")
www = APP / "www"
if www.exists():
    check("www/index.html", (www / "index.html").exists())
    check("www/app.js", (www / "app.js").exists())
    check("www/style.css", (www / "style.css").exists())
    check("www/library/manifest.json", (www / "library" / "manifest.json").exists())
    size = sum(f.stat().st_size for f in www.rglob("*") if f.is_file()) / 1e6
    print(f"   www 体积 {size:.1f} MB")
else:
    check("www 已生成", False, "先跑 node scripts/build-www.mjs")

print("\n=== 5. workflow 静态检查 ===")
wf = WF.read_text(encoding="utf-8")
check("不再无条件 pod install", "pod install --repo-update\n            echo" not in wf or "if [ -f Podfile ]" in wf)
check("SPM / CocoaPods 分支存在", "if [ -f Podfile ]" in wf and "XCODE_TARGET=" in wf)
check("构建用 $XCODE_TARGET（不是写死 -workspace）", "-workspace App.xcworkspace \\" not in wf)
check("node 版本 22", "node-version: '22'" in wf)
check("有失败日志上传", "if: failure()" in wf)
check("产物路径一致", "app/ios/gk-reader-unsigned.ipa" in wf and "../gk-reader-unsigned.ipa" in wf)
# 所有 run 块里不能出现 Windows 盘符
bad_paths = re.findall(r"[A-Za-z]:\\\\|E:\\\\apple", wf)
check("workflow 里没有 Windows 绝对路径", not bad_paths, str(bad_paths[:3]))

print("\n=== 5b. CI 平台与步骤（监工抓到的坑）===")
check("runner 不是已退役的 macos-14", "runs-on: macos-14" not in wf,
      "macOS 14 镜像 2026-11-02 已退役，job 不会被接走")
check("runner 是 macos-15 或更新", "runs-on: macos-15" in wf or "runs-on: macos-26" in wf)
check("有 scheme 兜底步骤", "XCScheme.share_scheme" in wf or "recreate_user_schemes" in wf)
check("有图标生成步骤", "npm run assets" in wf)
check("assets 脚本用 = 形式传颜色",
      "--iconBackgroundColor=#" in (APP / "package.json").read_text(encoding="utf-8"),
      "带引号会被 Windows cmd 当成值的一部分")
check("timeout 不超过 45 分钟", "timeout-minutes: 45" in wf or "timeout-minutes: 40" in wf
      or "timeout-minutes: 35" in wf)
check("pod install 不再 --repo-update", "--repo-update" not in wf)

print("\n=== 5c. LFS 流量控制（每月 1 GB，约 4 次构建）===")
check("checkout 不再 lfs: true", "lfs: true" not in wf, "否则每次构建都拉 247 MB")
check("有 library 缓存", "actions/cache" in wf and "path: library" in wf)
check("缓存未命中才拉 LFS", "git lfs pull" in wf and "缓存未命中" in wf)
check("校验 manifest 不是 LFS 指针", "LFS 指针" in wf)
check("校验图标是真 PNG", "file app/resources/icon.png" in wf)

print("\n=== 6. 脚本里有没有 Windows 硬编码 ===")
for f in ["scripts/build-www.mjs", "scripts/patch-ios.mjs", "scripts/patch_plist.py"]:
    t = (APP / f).read_text(encoding="utf-8")
    hits = re.findall(r"[A-Za-z]:\\\\", t)
    check(f"{f} 无盘符硬编码", not hits, str(hits[:3]))

print("\n=== 7. iOS 模板现状（若已解压） ===")
ios = APP / "ios"
if ios.exists():
    check("AppDelegate.swift", (ios / "App/App/AppDelegate.swift").exists())
    check("Info.plist", (ios / "App/App/Info.plist").exists())
    ad = (ios / "App/App/AppDelegate.swift").read_text(encoding="utf-8", errors="replace")
    check("已插入 AVAudioSession", "AVAudioSession" in ad)
    check("已 import AVFoundation", "import AVFoundation" in ad)
    check("括号配平", ad.count("{") == ad.count("}"), f'{ad.count("{")}/{ad.count("}")}')
    import plistlib
    d = plistlib.load((ios / "App/App/Info.plist").open("rb"))
    check("横屏数组", d.get("UISupportedInterfaceOrientations") ==
          ["UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"])
    check("状态栏隐藏", d.get("UIStatusBarHidden") is True)
    check("全屏", d.get("UIRequiresFullScreen") is True)
else:
    print("   （app/ios 不存在，跳过；CI 上由 cap add ios 生成）")

print("\n=== 8. npm ci 能否解析（dry-run） ===")
try:
    r = subprocess.run("npm ci --dry-run --no-audit --no-fund", cwd=str(APP),
                       capture_output=True, text=True, shell=True, timeout=600, errors="replace")
    tail = (r.stdout or "").strip().splitlines()[-3:]
    check("npm ci --dry-run 通过", r.returncode == 0, " | ".join(tail))
except Exception as e:  # noqa: BLE001
    check("npm ci --dry-run 通过", False, str(e)[:100])

print("\n" + ("全部通过 ✅" if ok_all else "有失败项 ❌"))
sys.exit(0 if ok_all else 1)
