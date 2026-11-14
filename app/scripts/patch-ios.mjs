/**
 * 在 `npx cap add ios` 之后给原生工程打补丁。**必须在 macOS 上跑**（用到 plutil）。
 *
 *   node app/scripts/patch-ios.mjs
 *
 * 做的事：
 *   1. Info.plist：锁横屏、隐藏状态栏、全屏、加麦克风说明
 *   2. AppDelegate.swift：把 AVAudioSession 设成 .playback
 *      —— 不做这一步，iPad 侧边静音键一拨，App 就没声音
 *
 * 任何一步找不到锚点都会直接失败，不允许"静默产出一个坏包"。
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..');
const PLIST = join(ROOT, 'ios', 'App', 'App', 'Info.plist');
const DELEGATE = join(ROOT, 'ios', 'App', 'App', 'AppDelegate.swift');

const fail = (msg) => { console.error('✗ ' + msg); process.exit(1); };

/* ── 1. Info.plist ─────────────────────────────────────── */
if (!existsSync(PLIST)) fail(`找不到 ${PLIST}，先跑 npx cap add ios`);

const plist = (args) => execFileSync('plutil', args, { stdio: 'pipe' });

plist(['-replace', 'UISupportedInterfaceOrientations~ipad', '-json',
  '["UIInterfaceOrientationLandscapeLeft","UIInterfaceOrientationLandscapeRight"]', PLIST]);
plist(['-replace', 'UISupportedInterfaceOrientations', '-json',
  '["UIInterfaceOrientationLandscapeLeft","UIInterfaceOrientationLandscapeRight"]', PLIST]);
plist(['-replace', 'UIStatusBarHidden', '-bool', 'YES', PLIST]);
plist(['-replace', 'UIViewControllerBasedStatusBarAppearance', '-bool', 'NO', PLIST]);
plist(['-replace', 'UIRequiresFullScreen', '-bool', 'YES', PLIST]);
plist(['-replace', 'NSMicrophoneUsageDescription', '-string',
  '跟读练习需要使用麦克风录音，录音只保存在这台 iPad 上，不会上传。', PLIST]);

// 校验确实写进去了
const dump = execFileSync('plutil', ['-convert', 'json', '-o', '-', PLIST], { encoding: 'utf8' });
const info = JSON.parse(dump);
if (!Array.isArray(info['UISupportedInterfaceOrientations~ipad'])) fail('横屏配置没写进去');
if (info.UIStatusBarHidden !== true) fail('状态栏没隐藏');
console.log('✓ Info.plist：横屏锁定 / 状态栏隐藏 / 全屏 / 麦克风说明');

/* ── 2. AppDelegate：音频会话 ───────────────────────────── */
if (!existsSync(DELEGATE)) fail(`找不到 ${DELEGATE}`);
let src = readFileSync(DELEGATE, 'utf8');

if (!src.includes('import AVFoundation')) {
  src = src.replace('import Capacitor', 'import Capacitor\nimport AVFoundation');
  if (!src.includes('import AVFoundation')) fail('AppDelegate 里找不到 import Capacitor，无法插入 AVFoundation');
}

const ANCHOR = 'return super.application(application, didFinishLaunchingWithOptions: launchOptions)';
if (!src.includes(ANCHOR)) fail('AppDelegate 里找不到 didFinishLaunching 的 return 语句');
if (src.includes('AVAudioSession')) {
  console.log('✓ AppDelegate：音频会话已存在，跳过');
} else {
  const snippet = [
    '        // 关键：不设 .playback，iPad 侧边静音键一拨就没声音',
    '        do {',
    '            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default, options: [.duckOthers])',
    '            try AVAudioSession.sharedInstance().setActive(true)',
    '        } catch {',
    '            NSLog("[GK] AVAudioSession 设置失败: \\(error)")',
    '        }',
    '',
  ].join('\n');
  src = src.replace(ANCHOR, snippet + '        ' + ANCHOR);
  writeFileSync(DELEGATE, src, 'utf8');
  console.log('✓ AppDelegate：AVAudioSession 设为 .playback');
}

/* ── 3. 检查 Xcode 工程里的最低系统版本 ─────────────────── */
const pbx = join(ROOT, 'ios', 'App', 'App.xcodeproj', 'project.pbxproj');
if (existsSync(pbx)) {
  const p = readFileSync(pbx, 'utf8');
  const m = p.match(/IPHONEOS_DEPLOYMENT_TARGET = ([\d.]+);/);
  console.log(`✓ 最低系统版本: iOS ${m ? m[1] : '未知'}`);
}

console.log('\n原生补丁完成。下一步：cd ios/App && pod install');
