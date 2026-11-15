# -*- coding: utf-8 -*-
"""给 Capacitor 生成的 Xcode 工程补一个**共享 scheme**。

为什么需要：Capacitor 的 ios 模板里 `.xcodeproj` 只有 project.pbxproj，
**不带任何 .xcscheme**。`xcodebuild -scheme App` 在 macOS runner 上大概率报
`The workspace named "App" does not contain a scheme named "App"`。

不用 ruby 的 `Xcodeproj::XCScheme.share_scheme`：那个 API 是**移动**已有 scheme，
工程里没有时它抛 ENOENT。

做法：从 pbxproj 里正则取出 PBXNativeTarget 的 UUID，直接写一份标准的
`App.xcodeproj/xcshareddata/xcschemes/App.xcscheme`。

    python app/scripts/make_scheme.py [工程目录，默认 app/ios/App]
"""
import re
import sys
from pathlib import Path

TARGET_NAME = "App"

SCHEME = """<?xml version="1.0" encoding="UTF-8"?>
<Scheme
   LastUpgradeVersion = "1500"
   version = "1.7">
   <BuildAction
      parallelizeBuildables = "YES"
      buildImplicitDependencies = "YES">
      <BuildActionEntries>
         <BuildActionEntry
            buildForTesting = "YES"
            buildForRunning = "YES"
            buildForProfiling = "YES"
            buildForArchiving = "YES"
            buildForAnalyzing = "YES">
            <BuildableReference
               BuildableIdentifier = "primary"
               BlueprintIdentifier = "{uuid}"
               BuildableName = "{name}.app"
               BlueprintName = "{name}"
               ReferencedContainer = "container:{name}.xcodeproj">
            </BuildableReference>
         </BuildActionEntry>
      </BuildActionEntries>
   </BuildAction>
   <TestAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      shouldUseLaunchSchemeArgsEnv = "YES">
      <Testables>
      </Testables>
   </TestAction>
   <LaunchAction
      buildConfiguration = "Debug"
      selectedDebuggerIdentifier = "Xcode.DebuggerFoundation.Debugger.LLDB"
      selectedLauncherIdentifier = "Xcode.DebuggerFoundation.Launcher.LLDB"
      launchStyle = "0"
      useCustomWorkingDirectory = "NO"
      ignoresPersistentStateOnLaunch = "NO"
      debugDocumentVersioning = "YES"
      debugServiceExtension = "internal"
      allowLocationSimulation = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{uuid}"
            BuildableName = "{name}.app"
            BlueprintName = "{name}"
            ReferencedContainer = "container:{name}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </LaunchAction>
   <ProfileAction
      buildConfiguration = "Release"
      shouldUseLaunchSchemeArgsEnv = "YES"
      savedToolIdentifier = ""
      useCustomWorkingDirectory = "NO"
      debugDocumentVersioning = "YES">
      <BuildableProductRunnable runnableDebuggingMode = "0">
         <BuildableReference
            BuildableIdentifier = "primary"
            BlueprintIdentifier = "{uuid}"
            BuildableName = "{name}.app"
            BlueprintName = "{name}"
            ReferencedContainer = "container:{name}.xcodeproj">
         </BuildableReference>
      </BuildableProductRunnable>
   </ProfileAction>
   <AnalyzeAction buildConfiguration = "Debug">
   </AnalyzeAction>
   <ArchiveAction
      buildConfiguration = "Release"
      revealArchiveInOrganizer = "YES">
   </ArchiveAction>
</Scheme>
"""


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    root = Path(sys.argv[1] if len(sys.argv) > 1 else "app/ios/App")
    pbx = root / f"{TARGET_NAME}.xcodeproj" / "project.pbxproj"
    if not pbx.exists():
        print(f"✗ 找不到 {pbx}")
        return 2

    text = pbx.read_text(encoding="utf-8", errors="ignore")
    # PBXNativeTarget 段里形如：  504EC3031FED79650016851F /* App */ = {
    m = re.search(
        r"([0-9A-F]{24})\s+/\*\s*" + TARGET_NAME + r"\s*\*/\s*=\s*\{\s*\n?\s*isa\s*=\s*PBXNativeTarget;",
        text,
    )
    if not m:
        print(f"✗ pbxproj 里找不到名为 {TARGET_NAME} 的 PBXNativeTarget")
        ids = re.findall(r"([0-9A-F]{24})\s+/\*\s*(\w+)\s*\*/\s*=\s*\{", text)[:10]
        print("  候选:", ids)
        return 3

    uuid = m.group(1)
    out_dir = root / f"{TARGET_NAME}.xcodeproj" / "xcshareddata" / "xcschemes"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{TARGET_NAME}.xcscheme"
    out.write_text(SCHEME.format(uuid=uuid, name=TARGET_NAME), encoding="utf-8")

    # 立刻自检：UUID 写进去了、XML 能解析
    import xml.etree.ElementTree as ET

    data = out.read_text(encoding="utf-8")
    if uuid not in data:
        print("✗ 写出的 scheme 里没有 target UUID")
        return 4
    ET.fromstring(data)
    print(f"✓ 写入共享 scheme: {out}")
    print(f"  target={TARGET_NAME} uuid={uuid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
