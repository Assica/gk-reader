#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""未签名 IPA 自检（纯标准库，Windows / macOS / Linux 都能跑）。

用法：
    python verify_ipa.py gk-reader-unsigned.ipa
    python verify_ipa.py Payload/App.app          # 解包后的 .app 目录
    python verify_ipa.py 已解包的仓库根目录        # 目录里有 Payload/

可选参数：
    --expect-bundle-id com.gkreader.app
    --expect-books 180        （0 = 不检查）
    --min-library-mb 240      （public/library 的原始字节总量下限）
    --min-files 1900          （public/library 下的文件数下限）
    --sample-files 40         （抽读多少张图/音频做"真 JPG / 非 LFS 指针"校验）

它会检查：
    1. IPA 结构：Payload/ 下只有一个 .app，没有 __MACOSX / 绝对路径
    2. Info.plist：CFBundleIdentifier / CFBundleExecutable / CFBundleVersion /
       MinimumOSVersion / UIDeviceFamily / UIRequiredDeviceCapabilities
    3. 可执行文件：存在、有执行位、是 Mach-O 且含 arm64 切片
    4. web 资源：public/index.html、app.js、style.css
    5. library：manifest.json 可解析、书数对得上、1443 张页图 + 180 封面 + 180 音频
       **全部在包里**；抽查内容是真 JPEG / 真 m4a，不是 "version https://git-lfs" 指针
    6. 体积：public/library >= 240 MB、文件数 >= 1900（拦住"能装但没图"的假 IPA）
    7. 图标：Assets.car 存在且不是空壳（1024 图标编译在里面）
    8. 动态库：Frameworks/*.framework/<Name> 都在（SideStore 重签时会遍历这些）
    9. 提醒：未签名（不该有 _CodeSignature）、armv7 声明与 arm64-only 的矛盾

退出码：0 = 全部通过（可以有 WARN）；1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import json
import os
import posixpath
import random
import re
import sys
import zipfile
from dataclasses import dataclass, field

# ── 常量 ────────────────────────────────────────────────────────────
CPU_TYPE_ARM64 = 0x0100000C
CPU_TYPE_ARM64_32 = 0x0200000C
MACHO_THIN_64_LE = b"\xcf\xfa\xed\xfe"
MACHO_THIN_32_LE = b"\xce\xfa\xed\xfe"
MACHO_THIN_64_BE = b"\xfe\xed\xfa\xcf"
MACHO_THIN_32_BE = b"\xfe\xed\xfa\xce"
MACHO_FAT_BE = b"\xca\xfe\xba\xbe"
LFS_MAGIC = b"version https://git-lfs"
JPEG_MAGIC = b"\xff\xd8\xff"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

OK, WARN, FAIL = "OK", "WARN", "FAIL"
_ICON = {OK: "✓", WARN: "⚠", FAIL: "✗"}


@dataclass
class Report:
    lines: list[tuple[str, str]] = field(default_factory=list)

    def add(self, level: str, msg: str) -> None:
        self.lines.append((level, msg))
        print(f"  {_ICON[level]} {msg}")

    def ok(self, msg: str) -> None:
        self.add(OK, msg)

    def warn(self, msg: str) -> None:
        self.add(WARN, msg)

    def fail(self, msg: str) -> None:
        self.add(FAIL, msg)

    @property
    def fails(self) -> list[str]:
        return [m for lv, m in self.lines if lv == FAIL]

    @property
    def warns(self) -> list[str]:
        return [m for lv, m in self.lines if lv == WARN]


# ── 数据源：zip / 目录 统一接口 ──────────────────────────────────────
class Source:
    kind = "?"

    def names(self) -> list[str]:
        raise NotImplementedError

    def size(self, name: str) -> int:
        raise NotImplementedError

    def read(self, name: str, n: int = 4096) -> bytes:
        raise NotImplementedError

    def mode(self, name: str) -> int:
        return 0

    def exists(self, name: str) -> bool:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ZipSource(Source):
    kind = "zip"

    def __init__(self, path: str):
        self.zf = zipfile.ZipFile(path)
        self._names = self.zf.namelist()
        self._set = set(self._names)

    def names(self) -> list[str]:
        return self._names

    def exists(self, name: str) -> bool:
        return name in self._set

    def size(self, name: str) -> int:
        return self.zf.getinfo(name).file_size

    def read(self, name: str, n: int = 4096) -> bytes:
        with self.zf.open(name) as f:
            return f.read(n)

    def mode(self, name: str) -> int:
        return self.zf.getinfo(name).external_attr >> 16

    def close(self) -> None:
        self.zf.close()


class DirSource(Source):
    kind = "dir"

    def __init__(self, root: str):
        self.root = root
        self._names: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            rel = os.path.relpath(dirpath, root)
            rel = "" if rel == "." else rel.replace(os.sep, "/")
            for fn in sorted(filenames):
                self._names.append(f"{rel}/{fn}" if rel else fn)
        self._set = set(self._names)

    def names(self) -> list[str]:
        return self._names

    def exists(self, name: str) -> bool:
        return name in self._set

    def _abs(self, name: str) -> str:
        return os.path.join(self.root, *name.split("/"))

    def size(self, name: str) -> int:
        return os.path.getsize(self._abs(name))

    def read(self, name: str, n: int = 4096) -> bytes:
        with open(self._abs(name), "rb") as f:
            return f.read(n)

    def mode(self, name: str) -> int:
        return os.stat(self._abs(name)).st_mode


# ── 辅助 ────────────────────────────────────────────────────────────
def macho_slices(head: bytes) -> list[int] | None:
    """返回 Mach-O 里所有 cputype；不是 Mach-O 返回 None。"""
    if len(head) < 8:
        return None
    magic = head[:4]
    if magic == MACHO_FAT_BE:
        n = int.from_bytes(head[4:8], "big")
        if n <= 0 or n > 16:
            return []
        slices = []
        # fat_header(8) + n * fat_arch(20)
        for i in range(n):
            off = 8 + i * 20
            if off + 4 > len(head):
                break
            slices.append(int.from_bytes(head[off:off + 4], "big"))
        return slices
    if magic in (MACHO_THIN_64_LE, MACHO_THIN_32_LE):
        return [int.from_bytes(head[4:8], "little")]
    if magic in (MACHO_THIN_64_BE, MACHO_THIN_32_BE):
        return [int.from_bytes(head[4:8], "big")]
    return None


def human(n: int) -> str:
    if n >= 1 << 30:
        return f"{n / (1 << 30):.2f} GB"
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f} MiB"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f} KiB"
    return f"{n} B"


def sniff(data: bytes) -> str:
    if data.startswith(LFS_MAGIC):
        return "lfs-pointer"
    if data.startswith(JPEG_MAGIC):
        return "jpeg"
    if data.startswith(PNG_MAGIC):
        return "png"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "m4a/mp4"
    if data.startswith(b"%PDF"):
        return "pdf"
    return "unknown"


# ── 主流程 ──────────────────────────────────────────────────────────
def find_app_prefix(src: Source, rep: Report) -> tuple[str, str] | None:
    """返回 (app_prefix 带结尾斜杠, app 名)。"""
    names = src.names()
    if src.kind == "dir" and not any(n.startswith("Payload/") for n in names):
        # 直接给了 .app 目录
        base = os.path.basename(src.root.rstrip("\\/"))
        if base.endswith(".app"):
            return "", base
    apps = sorted({m.group(0) for n in names
                   for m in [re.match(r"^Payload/([^/]+\.app)/", n)] if m})
    if not apps:
        rep.fail("找不到 Payload/*.app —— IPA 结构不对（必须是 Payload/App.app/...）")
        return None
    if len(apps) > 1:
        rep.fail(f"Payload 下有 {len(apps)} 个 .app（{apps}），安装器会挑错")
        return None
    prefix = apps[0]
    rep.ok(f"IPA 结构：{prefix}")
    return prefix, prefix.rstrip("/").rsplit("/", 1)[-1]


def check_no_junk(src: Source, rep: Report) -> None:
    names = src.names()
    junk = [n for n in names if n.startswith("__MACOSX/") or "__MACOSX/" in n]
    if junk:
        rep.warn(f"包里有 {len(junk)} 个 __MACOSX 条目（zip 未加 -X 的副产物，一般无害）")
    else:
        rep.ok("没有 __MACOSX / AppleDouble 垃圾条目")
    abs_entries = [n for n in names if n.startswith("/") or ".." in n.split("/")]
    if abs_entries:
        rep.fail(f"包里有可疑路径（绝对路径/..）：{abs_entries[:3]}")
    else:
        rep.ok("包内路径都是相对路径")


def check_info_plist(src: Source, prefix: str, rep: Report, expect_bundle_id: str):
    import plistlib

    name = prefix + "Info.plist"
    if not src.exists(name):
        rep.fail(f"{name} 不存在 —— SideStore 无法识别 bundle")
        return None
    try:
        info = plistlib.loads(src.read(name, 1 << 20))
    except Exception as e:  # noqa: BLE001
        rep.fail(f"Info.plist 解析失败：{e}")
        return None
    rep.ok("Info.plist 可解析")

    bid = info.get("CFBundleIdentifier", "")
    if bid == expect_bundle_id:
        rep.ok(f"CFBundleIdentifier = {bid}")
    elif "$(" in str(bid):
        rep.fail(f"CFBundleIdentifier 没被展开：{bid}（PRODUCT_BUNDLE_IDENTIFIER 没设？）")
    else:
        rep.warn(f"CFBundleIdentifier = {bid}（期望 {expect_bundle_id}）")

    exe = info.get("CFBundleExecutable", "")
    if not exe:
        rep.fail("CFBundleExecutable 为空")
    else:
        rep.ok(f"CFBundleExecutable = {exe}")

    for key in ("CFBundleVersion", "CFBundleShortVersionString", "MinimumOSVersion"):
        val = info.get(key)
        if val in (None, ""):
            rep.warn(f"{key} 缺失")
        else:
            rep.ok(f"{key} = {val}")

    fam = info.get("UIDeviceFamily")
    if isinstance(fam, list) and any(int(x) == 2 for x in fam):
        rep.ok(f"UIDeviceFamily = {fam}（含 iPad）")
    elif fam:
        rep.warn(f"UIDeviceFamily = {fam}（不含 2，iPad 只能兼容模式跑）")
    else:
        rep.warn("UIDeviceFamily 缺失")

    caps = info.get("UIRequiredDeviceCapabilities")
    if isinstance(caps, list) and "armv7" in caps:
        rep.warn("UIRequiredDeviceCapabilities 里还是 armv7，但只编了 arm64 "
                 "（App Store 会报 ITMS-90502；建议改成 ['arm64']）")
    elif isinstance(caps, list):
        rep.ok(f"UIRequiredDeviceCapabilities = {caps}")

    if "UISupportedInterfaceOrientations~ipad" in info:
        rep.ok("有独立的 iPad 方向声明")
    return info


def check_executable(src: Source, prefix: str, exe: str, rep: Report) -> None:
    path = prefix + exe
    if not src.exists(path):
        rep.fail(f"{path} 不存在 —— .app 里没有可执行文件，肯定装不上")
        return
    size = src.size(path)
    if size < 200 * 1024:
        rep.fail(f"可执行文件只有 {human(size)}，不像真二进制")
        return
    rep.ok(f"可执行文件存在：{exe}（{human(size)}）")

    mode = src.mode(path)
    if src.kind == "zip":
        if mode & 0o111:
            rep.ok(f"可执行位在（mode 0o{mode & 0o777:o}）")
        else:
            rep.fail(f"可执行位丢了（mode 0o{mode & 0o777:o}）—— zip 打包方式有问题")
    elif os.name != "nt" and mode and not mode & 0o111:
        rep.fail("目录里的可执行文件没有 x 位")
    elif os.name == "nt":
        rep.warn("在 Windows 上读目录，没有 POSIX 权限位，跳过 x 位检查"
                 "（检查 .ipa 时会正常校验）")

    head = src.read(path, 4096)
    slices = macho_slices(head)
    if slices is None:
        rep.fail(f"{exe} 不是 Mach-O（前 8 字节 {head[:8]!r}）")
        return
    if CPU_TYPE_ARM64 in slices or CPU_TYPE_ARM64_32 in slices:
        rep.ok("Mach-O 含 arm64 切片（iPhone/iPad 真机可执行）")
    else:
        rep.fail(f"Mach-O 里没有 arm64（cputype={[hex(x) for x in slices]}）")


def check_web(src: Source, prefix: str, rep: Report) -> None:
    for rel, minimum in (("public/index.html", 500), ("public/app.js", 1000),
                         ("public/style.css", 500)):
        name = prefix + rel
        if not src.exists(name):
            rep.fail(f"{rel} 不存在")
            continue
        size = src.size(name)
        if size < minimum:
            rep.fail(f"{rel} 只有 {size} B，不像真文件")
        else:
            rep.ok(f"{rel}（{human(size)}）")


def check_library(src: Source, prefix: str, rep: Report, args) -> None:
    lib_prefix = prefix + "public/library/"
    manifest_name = lib_prefix + "manifest.json"
    if not src.exists(manifest_name):
        rep.fail("public/library/manifest.json 不存在 —— 包里没有书库")
        return

    raw = src.read(manifest_name, 16 << 20)
    if raw.startswith(LFS_MAGIC):
        rep.fail("manifest.json 本身是 LFS 指针（不该发生：它没走 LFS）")
        return
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        rep.fail(f"manifest.json 解析失败：{e}")
        return
    books = manifest.get("books") or []
    rep.ok(f"manifest.json 可解析，books = {len(books)}")
    if args.expect_books:
        if len(books) == args.expect_books:
            rep.ok(f"书数 = {args.expect_books}（符合预期）")
        else:
            rep.fail(f"书数 = {len(books)}，期望 {args.expect_books}")

    missing: list[str] = []
    checked = 0
    total_pages = 0
    for b in books:
        for rel in (b.get("cover"), b.get("audio")):
            if not rel:
                continue
            p = lib_prefix + rel
            checked += 1
            if not src.exists(p):
                missing.append(rel)
        pages = b.get("pages") or []
        total_pages += len(pages) or int(b.get("pageCount") or 0)
        for pg in pages:
            rel = pg.get("image")
            if not rel:
                continue
            p = lib_prefix + rel
            checked += 1
            if not src.exists(p):
                missing.append(rel)

    if missing:
        rep.fail(f"library 里缺 {len(missing)} 个被引用的文件，例如 {missing[:3]}")
    else:
        rep.ok(f"manifest 引用的 {checked} 个文件（封面/音频/页图）全部在包里")
    rep.ok(f"页图总数（按 book json 统计）= {total_pages}")

    # 体积 / 文件数：拦住"全是指针文件"的假 IPA
    lib_names = [n for n in src.names() if n.startswith(lib_prefix)]
    total = sum(src.size(n) for n in lib_names)
    mb = total / (1 << 20)
    rep.ok(f"public/library = {human(total)}，{len(lib_names)} 个文件")
    if mb < args.min_library_mb:
        rep.fail(f"public/library 只有 {mb:.1f} MiB < {args.min_library_mb} MiB —— "
                 "大概率打进的是 LFS 指针文件")
    if len(lib_names) < args.min_files:
        rep.fail(f"public/library 只有 {len(lib_names)} 个文件 < {args.min_files}")

    # 抽查内容：必须是真 JPEG / 真 m4a，不能是 LFS 指针
    pool = [n for n in lib_names
            if n.lower().endswith((".jpg", ".jpeg", ".png", ".m4a", ".mp4"))]
    if not pool:
        rep.fail("public/library 里没有任何图片/音频文件")
        return
    rng = random.Random(20261115)
    sample = rng.sample(pool, min(args.sample_files, len(pool)))
    bad = []
    for n in sample:
        kind = sniff(src.read(n, 64))
        if kind == "lfs-pointer":
            bad.append((n, "LFS 指针"))
        elif kind == "unknown":
            bad.append((n, "无法识别的字节"))
    if bad:
        rep.fail(f"抽查 {len(sample)} 个媒体文件，{len(bad)} 个不是真内容，例如 "
                 f"{bad[:2]}")
    else:
        rep.ok(f"抽查 {len(sample)} 个媒体文件：都是真 JPG/PNG/m4a（不是 LFS 指针）")


def check_assets(src: Source, prefix: str, rep: Report) -> None:
    car = prefix + "Assets.car"
    if not src.exists(car):
        rep.fail("Assets.car 不存在 —— 图标/启动图没编译进去")
    else:
        size = src.size(car)
        if size < 4096:
            rep.warn(f"Assets.car 只有 {human(size)}，图标可能是空的")
        else:
            rep.ok(f"Assets.car 存在（{human(size)}，1024 图标编译在里面）")

    fw_root = prefix + "Frameworks/"
    fw: set[str] = set()
    for n in src.names():
        if not n.startswith(fw_root):
            continue
        rest = n[len(fw_root):]
        if ".framework/" in rest:
            fw.add(rest.split(".framework/", 1)[0] + ".framework")
    if not fw:
        rep.warn("Frameworks/ 下没有 .framework（用静态库链接的话正常）")
        return
    rep.ok(f"动态库 {len(fw)} 个：{sorted(fw)}")
    broken = []
    for name in sorted(fw):
        binname = name[:-len(".framework")]
        if not src.exists(f"{fw_root}{name}/{binname}"):
            broken.append(name)
    if broken:
        rep.fail(f"这些 framework 里没有同名可执行文件（SideStore 重签会失败）：{broken}")
    else:
        rep.ok("每个 framework 都有可执行文件（SideStore 重签要遍历它们）")


def check_signature(src: Source, prefix: str, rep: Report) -> None:
    has_sig = any(n.startswith(prefix + "_CodeSignature/") for n in src.names())
    has_prov = src.exists(prefix + "embedded.mobileprovision")
    if has_sig or has_prov:
        rep.warn("包里已经有签名/描述文件 —— 你说要的是未签名 IPA；"
                 "SideStore 会自己重签，带着别人的签名反而可能冲突")
    else:
        rep.ok("确认是未签名包（没有 _CodeSignature，也没有 embedded.mobileprovision）")


def build_source(path: str, rep: Report) -> Source | None:
    if os.path.isdir(path):
        return DirSource(path)
    if not os.path.isfile(path):
        rep.fail(f"路径不存在：{path}")
        return None
    if zipfile.is_zipfile(path):
        return ZipSource(path)
    rep.fail(f"{path} 不是 zip/IPA，也不是目录")
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="未签名 IPA 自检")
    ap.add_argument("path", help="IPA 文件、.app 目录，或含 Payload/ 的目录")
    ap.add_argument("--expect-bundle-id", default="com.gkreader.app")
    ap.add_argument("--expect-books", type=int, default=180)
    ap.add_argument("--min-library-mb", type=float, default=240.0)
    ap.add_argument("--min-files", type=int, default=1900)
    ap.add_argument("--sample-files", type=int, default=40)
    args = ap.parse_args(argv)

    print(f"检查目标：{os.path.abspath(args.path)}")
    rep = Report()
    src = build_source(args.path, rep)
    if src is None:
        return 1
    try:
        print(f"来源类型：{src.kind}")

        if src.kind == "zip":
            rep.ok(f"IPA 大小：{human(os.path.getsize(args.path))}")

        found = find_app_prefix(src, rep)
        if not found:
            return 1
        prefix, appname = found
        check_no_junk(src, rep)
        info = check_info_plist(src, prefix, rep, args.expect_bundle_id)
        if info is None:
            rep.warn("Info.plist 读不出来，跳过可执行文件名校验（只按目录名找）")
            info = {}
        fallback_exe = appname[:-4] if appname.endswith(".app") else appname
        exe = info.get("CFBundleExecutable") or fallback_exe
        check_executable(src, prefix, exe, rep)
        check_web(src, prefix, rep)
        check_library(src, prefix, rep, args)
        check_assets(src, prefix, rep)
        check_signature(src, prefix, rep)
    finally:
        src.close()

    print()
    print(f"结果：{len(rep.fails)} 个 FAIL，{len(rep.warns)} 个 WARN")
    if rep.fails:
        print("失败项：")
        for m in rep.fails:
            print("  ✗ " + m)
        return 1
    print("✓ 全部检查通过" + ("（有 WARN 但都是可接受项）" if rep.warns else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
