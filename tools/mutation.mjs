/**
 * 变异测试 runner。
 *
 * 在 .work/mut/www 的副本上把功能一个个改坏，跑完整测试套件，
 * 看套件能不能发现。原文件全程不动（结束时校验哈希）。
 *
 *   node tools/mutation.mjs [baseUrl]
 */
import { readFileSync, writeFileSync, mkdirSync, copyFileSync, existsSync } from 'node:fs';
import { spawnSync, execSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const BASE = process.argv[2] || 'http://127.0.0.1:8790/';
const NODE = process.execPath;
const ROOT = 'E:\\apple app';
const SANDBOX = `${ROOT}\\.work\\mut\\www`;
const APP = `${SANDBOX}\\app.js`;
const SUITE = `${ROOT}\\tools\\webtest.mjs`;

// 自备沙箱：每次都同步三个前端文件，并把 library 以目录联接挂进来（不复制 93MB）
mkdirSync(SANDBOX, { recursive: true });
for (const f of ['index.html', 'app.js', 'style.css']) {
  copyFileSync(`${ROOT}\\web\\${f}`, `${SANDBOX}\\${f}`);
}
const LINK = `${SANDBOX}\\library`;
if (!existsSync(LINK)) {
  execSync(`cmd /c mklink /J "${LINK}" "${ROOT}\\library"`, { stdio: 'ignore' });
  console.log(`已把 library 挂进沙箱: ${LINK}`);
}

const ORIG = readFileSync(APP, 'utf8');
const HASH0 = createHash('sha256').update(ORIG).digest('hex');

const MUTATIONS = [
  {
    id: 'M2', name: '点词退化成读整句', expect: 'T5 系列应红',
    apply: (s) => s.replace('function playWord(k) {', 'function playWord(k) {\n  playSentence(); return;'),
  },
  {
    id: 'M3', name: '音频永不自动停止', expect: 'T5f / T6 应红',
    // 现在有两条停止路径（rAF 轮询 + timeupdate 兜底），只废掉一条不会改变行为，
    // 必须把公共出口 finishRange 打瘫才能模拟"永不停止"
    apply: (s) => s.replace('function finishRange() {', 'function finishRange() { return;'),
  },
  {
    id: 'M5', name: '词中心坐标整体右移 ≈40px（坐标错位）', expect: 'T4 真实命应红',
    apply: (s) => s.replace('x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2',
                            'x: (b[0] + b[2]) / 2 + 0.035, y: (b[1] + b[3]) / 2'),
  },
  {
    id: 'M7', name: '删掉 audio.play()（不出声）', expect: 'T5b / T6.1 应红',
    apply: (s) => s.replace(/audio\.play\(\)[^;]*;/, '/* play removed */;'),
  },
  {
    id: 'M8', name: '翻页时不暂停旧音频', expect: 'T7 应红',
    // 必须命中 stopPlayback 内部那一处；playSentence 里也有相同三行，
    // 按字面替换会打到无关代码上（实测因此漏检）
    apply: (s) => s.replace(/(function stopPlayback\(\) \{[\s\S]*?)audio\.pause\(\);/, '$1'),
  },
  {
    id: 'M15', name: '原生路径退回 fetch+res.ok（真机音频不可用的那个 bug）',
    expect: 'T21 应红',
    apply: (s) => s.replace(
      "const native = location.protocol === 'capacitor:' || window.__GK_FORCE_NATIVE === true;",
      'const native = false;'),
  },
  {
    id: 'M9', name: '语速只改按钮文字、不改实际速率', expect: 'T8 应红',
    apply: (s) => s.replace('audio.playbackRate = state.rate;', '/* rate not applied */'),
  },
  {
    id: 'M10', name: '连播到最后一页后循环回第 1 页', expect: 'T9.5 应红',
    apply: (s) => s.replace('if (next >= state.book.pageCount) {', 'if (next >= state.book.pageCount) {\n      showPage(0, true); state.autoRun = false; setPlayIcon(false); return;'),
  },
  {
    id: 'M11', name: '吸附半径置 0（点不中就什么事都不发生）', expect: 'T4.3 / T4.4 / T5 应红',
    apply: (s) => s.replace('const SNAP_R = 40;', 'const SNAP_R = 0;'),
  },
  {
    id: 'M12', name: '文字区不留更大吸附半径（词间出现死区）', expect: 'T4.4 应红',
    apply: (s) => s.replace('limit = SNAP_R * 1.8;', 'limit = SNAP_R;'),
  },
  {
    id: 'M13', name: '吸附距离算错（只按横向加权）', expect: 'T4.3 / T4.4 应红',
    apply: (s) => s.replace('const d = Math.sqrt(dx * dx + dy * dy);',
                            'const d = Math.abs(dx) * 0.001 + Math.abs(dy);'),
  },
  {
    id: 'M14', name: '真实点击路径退回矩形命中（只改 handleTap）', expect: 'T4.7 / T4.8 应红',
    apply: (s) => s.replace(
      'const k = nearestWord(px, py, r.width, r.height);',
      'const k = (() => { for (const el of document.querySelectorAll(".hit.word")) { const b = el.getBoundingClientRect(); if (e.clientX >= b.left && e.clientX <= b.right && e.clientY >= b.top && e.clientY <= b.bottom) return +el.dataset.k; } return -1; })();'),
  },
];

function runSuite() {
  const r = spawnSync(NODE, [SUITE, BASE], { encoding: 'utf8', timeout: 300000 });
  const out = (r.stdout || '') + (r.stderr || '');
  const m = /RESULT pass=(\d+) fail=(\d+) total=(\d+)/.exec(out);
  const ids = /FAILID (.+)/.exec(out);
  return {
    code: r.status,
    pass: m ? +m[1] : -1,
    fail: m ? +m[2] : -1,
    total: m ? +m[3] : -1,
    ids: ids ? ids[1].trim() : '',
    tail: out.split('\n').slice(-4).join(' | '),
  };
}

console.log('=== 基线 ===');
writeFileSync(APP, ORIG, 'utf8');
const base = runSuite();
console.log(`基线: ${base.pass}/${base.total} 通过, exit=${base.code}`);
if (base.fail !== 0) {
  console.log('基线不绿，先修基线。', base.tail);
  process.exit(1);
}

const rows = [];
for (const mu of MUTATIONS) {
  const mutated = mu.apply(ORIG);
  if (mutated === ORIG) {
    console.log(`\n${mu.id} ${mu.name}: 锚点没匹配上，跳过`);
    rows.push({ id: mu.id, name: mu.name, detected: 'ANCHOR-MISS', fail: '', ids: '' });
    continue;
  }
  writeFileSync(APP, mutated, 'utf8');
  process.stdout.write(`\n${mu.id} ${mu.name} ... `);
  const r = runSuite();
  const detected = r.fail > 0 || r.code !== 0;
  console.log(`${r.pass}/${r.total} 通过, 失败 ${r.fail}, exit=${r.code} → ${detected ? '✅ 检出' : '❌ 漏检'}`);
  if (r.ids) console.log(`    红的断言: ${r.ids}`);
  rows.push({ id: mu.id, name: mu.name, detected: detected ? 'YES' : 'NO', fail: r.fail, ids: r.ids, exit: r.code });
}

writeFileSync(APP, ORIG, 'utf8');
const HASH1 = createHash('sha256').update(readFileSync(APP, 'utf8')).digest('hex');
console.log('\n=== 汇总 ===');
for (const r of rows) {
  console.log(`${r.detected === 'YES' ? '✅' : '❌'} ${r.id.padEnd(4)} ${r.name.padEnd(30)} 失败 ${String(r.fail).padStart(2)}  ${r.ids || ''}`);
}
console.log(`\n副本已还原: ${HASH0 === HASH1 ? '哈希一致 ✅' : '哈希不一致 ❌'}`);
const missed = rows.filter((r) => r.detected !== 'YES');
process.exit(missed.length ? 1 : 0);
