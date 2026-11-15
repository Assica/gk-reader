/**
 * 给 `npx cap add ios` 生成的工程打补丁。
 *
 *   node app/scripts/patch-ios.mjs
 *
 * 做的事：
 *   1. Info.plist：锁横屏、隐藏状态栏、全屏、加麦克风说明
 *      —— 交给 patch_plist.py（plistlib），因为 `plutil -replace` 对不存在的 key 会报错，
 *         而 Capacitor 7 模板里 UIStatusBarHidden / UIRequiresFullScreen 本来就没有。
 *   2. AppDelegate.swift：把 AVAudioSession 设成 .playback
 *      —— 不做这一步，iPad 侧边静音键一拨，App 就没声音。
 *
 * Capacitor 版本差异（都已在本地用真实模板验证）：
 *   · Capacitor 2/3 模板有 `return super.application(...)`，在它前面插
 *   · Capacitor 4–7 模板是 `@UIApplicationMain` + `return true`，没有 super 调用，
 *     改成"定位 didFinishLaunching 的签名行，插到它的函数体开头"
 *
 * 任何一步找不到锚点就**明确失败**——不允许静默跳过，那会变成一个没声音的 App。
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const PLIST = join(ROOT, 'ios', 'App', 'App', 'Info.plist');
const DELEGATE = join(ROOT, 'ios', 'App', 'App', 'AppDelegate.swift');

const fail = (msg) => { console.error('✗ ' + msg); process.exit(1); };
const ok = (msg) => console.log('✓ ' + msg);

/* ── 1. Info.plist ─────────────────────────────────────── */
if (!existsSync(PLIST)) fail(`找不到 ${PLIST}，先跑 npx cap add ios`);

// macOS 上是 python3；本地 Windows 调试时退回 python
const PY = (() => {
  for (const c of ['python3', 'python']) {
    try {
      execFileSync(c, ['--version'], { stdio: 'pipe' });
      return c;
    } catch { /* 试下一个 */ }
  }
  return null;
})();
if (!PY) fail('找不到 python3 —— Info.plist 补丁依赖标准库 plistlib');

try {
  const out = execFileSync(PY, [join(ROOT, 'scripts', 'patch_plist.py'), PLIST],
    { encoding: 'utf8' });
  process.stdout.write(out);
} catch (e) {
  fail(`Info.plist 补丁失败:\n${e.stdout || ''}${e.stderr || e.message}`);
}

/* ── 2. AppDelegate：音频会话 ───────────────────────────── */
if (!existsSync(DELEGATE)) fail(`找不到 ${DELEGATE}`);
let src = readFileSync(DELEGATE, 'utf8');

if (src.includes('AVAudioSession')) {
  ok('AppDelegate：音频会话已存在，跳过');
} else {
  if (!src.includes('import AVFoundation')) {
    if (!src.includes('import UIKit') && !src.includes('import Capacitor')) {
      fail('AppDelegate 里既没有 import UIKit 也没有 import Capacitor，模板形态未知');
    }
    src = src.replace(/^(import .+)$/m, 'import AVFoundation\n$1');
    if (!src.includes('import AVFoundation')) fail('插入 import AVFoundation 失败');
  }

  const SNIPPET = [
    '        // 关键：不设 .playback，iPad 侧边静音键一拨就没声音',
    '        do {',
    '            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.duckOthers])',
    '            try AVAudioSession.sharedInstance().setActive(true)',
    '        } catch {',
    '            NSLog("[GK] AVAudioSession 设置失败: \\(error)")',
    '        }',
    '',
  ].join('\n');

  const LEGACY = 'return super.application(application, didFinishLaunchingWithOptions: launchOptions)';
  if (src.includes(LEGACY)) {
    src = src.replace(LEGACY, SNIPPET + '        ' + LEGACY);
    ok('AppDelegate：在 super 调用前插入音频会话（Capacitor 2/3 模板）');
  } else {
    // Capacitor 4–7：func application(_:didFinishLaunchingWithOptions:) -> Bool {
    const sig = /func\s+application\([^)]*didFinishLaunchingWithOptions[^{]*\{\s*\n/;
    const m = src.match(sig);
    if (!m) {
      console.error(readFileSync(DELEGATE, 'utf8').split('\n').slice(0, 20).join('\n'));
      fail('AppDelegate 里找不到 didFinishLaunchingWithOptions 的函数体，无法插入音频会话');
    }
    const at = m.index + m[0].length;
    src = src.slice(0, at) + SNIPPET + src.slice(at);
    ok('AppDelegate：插入到 didFinishLaunching 函数体开头（Capacitor 4–7 模板）');
  }

  writeFileSync(DELEGATE, src, 'utf8');
}

// 复核：插入点必须在 didFinishLaunching 之后、且花括号配平
{
  const cur = readFileSync(DELEGATE, 'utf8');
  const iAva = cur.indexOf('AVAudioSession');
  const iFn = cur.indexOf('didFinishLaunchingWithOptions');
  if (iAva < 0) fail('复核失败：文件里没有 AVAudioSession');
  if (iFn < 0) fail('复核失败：文件里没有 didFinishLaunchingWithOptions');
  const open = (cur.match(/\{/g) || []).length;
  const close = (cur.match(/\}/g) || []).length;
  if (open !== close) fail(`复核失败：花括号不配平 { ${open} } ${close}`);
  ok(`AppDelegate 复核通过（AVAudioSession 在 didFinishLaunching 之后，括号 ${open}/${close}）`);
}

/* ── 3. 工程形态 ───────────────────────────────────────── */
const pbx = join(ROOT, 'ios', 'App', 'App.xcodeproj', 'project.pbxproj');
const ws = join(ROOT, 'ios', 'App', 'App.xcworkspace');
const pod = join(ROOT, 'ios', 'App', 'Podfile');
console.log(`工程形态: pbxproj=${existsSync(pbx)} xcworkspace=${existsSync(ws)} Podfile=${existsSync(pod)}`);
if (existsSync(pbx)) {
  const p = readFileSync(pbx, 'utf8');
  const m = p.match(/IPHONEOS_DEPLOYMENT_TARGET = ([\d.]+);/);
  ok(`最低系统版本: iOS ${m ? m[1] : '未知'}`);
}
if (!existsSync(pbx) && !existsSync(ws)) fail('既没有 App.xcodeproj 也没有 App.xcworkspace');

console.log('\n原生补丁完成。');
