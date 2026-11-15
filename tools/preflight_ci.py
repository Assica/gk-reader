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

print("\n=== 5b. CI 平台与步骤（监工/专家抓到的坑）===")
check("runner 不是已退役的 macos-14", "runs-on: macos-14" not in wf,
      "macOS 14 镜像 2026-11-02 已退役，job 不会被接走")
check("runner 是 macos-15 或更新", "runs-on: macos-15" in wf or "runs-on: macos-26" in wf)
check("有共享 scheme 生成步骤", "make_scheme.py" in wf)
check("scheme 用 JSON 校验（不靠 grep \\s）", "-list -json" in wf)
check("图标改纯拷贝（不依赖 sharp）", "AppIcon-512@2x.png" in wf)
check("timeout 不超过 45 分钟", "timeout-minutes: 45" in wf or "timeout-minutes: 40" in wf)
check("pod install 不再 --repo-update", "--repo-update" not in wf)
check("artifact 保留 7 天（0.5 GB 配额）", "retention-days: 7" in wf)

print("\n=== 5c. library 从哪来（两种模式，按 workflow 实际写法判断）===")
uses_release = "releases/tags" in wf or "ASSET_URL" in wf
uses_lfs = "git lfs pull" in wf
check("library 取用方式明确（Release 附件 或 LFS）", uses_release or uses_lfs,
      f"release={uses_release} lfs={uses_lfs}")
check("checkout 不再 lfs: true（大文件不该每次拉）", "lfs: true" not in wf)
check("有 library 体积下限断言", 'LIB_MB" -ge 200' in wf)
check("有 public 体积下限断言", 'PUB_MB" -ge 240' in wf)
check("有 www 体积下限断言", 'WWW_MB" -ge 240' in wf)
check("有 manifest.json 存在性断言", "test -f library/manifest.json" in wf)
check("有书籍数断言", "-ge 180" in wf or ">= 180" in wf)
check("探针用 covers/*.jpg（不是 manifest.json）", "PROBE=library/covers/GK/001.jpg" in wf)

if uses_release:
    # Release 模式：必须先从仓库里删干净再解压，否则新旧文件混在一起；
    # 且私有仓库的附件只能走 API（浏览器直链要登录）。
    check("Release 模式：先清空再解压", re.search(r"rm -rf\s+library\s*&&\s*mkdir", wf) is not None,
          "否则旧文件会和新解压的混在一起")
    check("Release 模式：走 GitHub API 取附件", "api.github.com" in wf)
    check("Release 模式：tag 有变量", "LIBRARY_TAG" in wf)
    check("Release 模式：缺附件时明确报错", "找不到附件" in wf or "exit 1" in wf)
else:
    # LFS 模式：绝不能 rm -rf（manifest 与 books json 是普通 git 文件，删了 lfs pull 不恢复）
    bad_rm = [ln for ln in wf.splitlines() if re.match(r"\s*rm -rf\s+library\b", ln)]
    check("LFS 模式：没有真的执行 rm -rf library", not bad_rm, str(bad_rm[:2]))
    check("LFS 模式：有非 LFS 文件兜底 checkout",
          "test -f \"$f\" || git checkout" in wf or "test -f library/manifest.json || git checkout" in wf)

# 本地仓库状态要和模式一致：Release 模式下 library 不该再被 git 跟踪
tracked_lib = subprocess.run(["git", "ls-files", "library"], cwd=str(ROOT),
                             capture_output=True, text=True, errors="replace").stdout.strip()
if uses_release:
    check("Release 模式：library 已不在 git 里", not tracked_lib,
          f"仍跟踪 {len(tracked_lib.splitlines())} 个文件")
else:
    check("LFS 模式：library 在 git 里", bool(tracked_lib))

print("\n=== 5d. 依赖树跨平台安全 ===")
pkg_s = (APP / "package.json").read_text(encoding="utf-8")
check("已移除 @capacitor/assets（它带 sharp）", "@capacitor/assets" not in pkg_s)
lock_s = (APP / "package-lock.json").read_text(encoding="utf-8")
check("lock 里没有 sharp", '"node_modules/sharp"' not in lock_s)
check("lock 里没有带 install 脚本的包", '"hasInstallScript": true' not in lock_s)
check("verify_ipa.py 已就位", (ROOT / "tools" / "verify_ipa.py").exists())

print("\n=== 5e. app/www 是否是 web/ 的最新产物 ===")
# 本地跑过 cap sync 却没重建 www，会把旧 app.js 打进包（CI 会重建，本地不会）
www_js = APP / "www" / "app.js"
src_js = ROOT / "web" / "app.js"
if www_js.exists():
    import hashlib
    h1 = hashlib.sha256(www_js.read_bytes()).hexdigest()
    h2 = hashlib.sha256(src_js.read_bytes()).hexdigest()
    check("www/app.js 与 web/app.js 一致", h1 == h2,
          "不一致：本地打包会发旧代码，先跑 node scripts/build-www.mjs")
else:
    print("   （www 不存在，跳过）")

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
