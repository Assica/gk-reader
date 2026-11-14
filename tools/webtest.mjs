/**
 * 小书虫 GK 阅读器 —— 端到端测试（v2）
 *
 * v1 的教训：把"点词"改成"读整句"、把词框整体右移 40px、翻页不暂停旧音频，
 * v1 全部 41/41 通过。原因是它用 `.click()` 走 DOM 合成事件绕过命中测试，
 * 且只断言 currentTime 落进一个很宽的窗口。
 *
 * v2 的原则：
 *   1. 用 CDP `Input.dispatchMouseEvent` 发**真实指针**，坐标由数据算出来，
 *      而不是从被测元素自己身上读——否则元素整体错位也测不出来。
 *   2. 断言**声明的边界**（stopAt、clipEnd），不只是起点。
 *   3. 断言**状态**（paused / 高亮数量），不只看数字被赋值。
 *   4. 视口按 iPad 横屏 1194×834 / DPR2 模拟。
 *
 * 用法: node tools/webtest.mjs [baseUrl]
 */
const BASE = process.argv[2] || 'http://127.0.0.1:8787/web/';
const ORIGIN = new URL(BASE).origin;
const PORT = 9223;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws, msgId = 0;
const pending = new Map();
const pageErrors = [];
// 错误路径用的请求拦截规则：{ match: 'audio/', fail: true }
const fetchRules = [];

/* ───────────────── CDP 底座 ───────────────── */
function send(method, params = {}) {
  const id = ++msgId;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    setTimeout(() => {
      if (pending.has(id)) { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }
    }, 25000);
  });
}

async function js(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) {
    throw new Error('页面 JS 异常: ' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  }
  return r.result?.value;
}

async function until(expr, label, ms = 10000) {
  const t0 = Date.now();
  let lastErr = null;
  while (Date.now() - t0 < ms) {
    try { if (await js(expr)) return true; } catch (e) { lastErr = e; }
    await sleep(80);
  }
  throw new Error(`等待超时: ${label}${lastErr ? '（页面报错: ' + lastErr.message + '）' : ''}`);
}

async function connect() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch { /* 浏览器还没起来 */ }
    await sleep(250);
  }
  throw new Error(`连不上调试端口 ${PORT}`);
}

/** 真实指针点击（不是 element.click()） */
async function clickAt(x, y) {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' });
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
}

/* ───────────────── 断言 ───────────────── */
const results = [];
function record(id, name, ok, detail = '') {
  results.push({ id, name, ok, detail });
  console.log(`${ok ? '  ✅' : '  ❌'} ${id} ${name}${detail ? '\n       ' + detail : ''}`);
}
function eq(id, name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  record(id, name, ok, ok ? '' : `实际=${JSON.stringify(actual)} 期望=${JSON.stringify(expected)}`);
}
function near(id, name, actual, expected, tol) {
  const ok = typeof actual === 'number' && Math.abs(actual - expected) <= tol;
  record(id, name, ok, ok ? `${actual} ≈ ${expected}` : `实际=${actual} 期望≈${expected} (±${tol})`);
}
function truthy(id, name, v, detail = '') { record(id, name, !!v, detail); }

/* ───────────────── 页面探针 ───────────────── */
let seq = 0;
async function openBook(id, page = 0) {
  seq += 1;
  await js(`localStorage.setItem('gk-progress', JSON.stringify(${JSON.stringify({ [id]: page })}))`);
  // 页图偶发首载超时（网络/解码竞争），重载一次再说失败，避免整套 flaky
  for (let attempt = 0; attempt < 2; attempt += 1) {
    await send('Page.navigate', { url: `${BASE}?c=${seq}${attempt ? 'r' : ''}#/b/${id}` });
    await until(`!!(window.__GK && window.__GK.state.book && window.__GK.state.book.id === ${JSON.stringify(id)})`,
      `打开书 ${id}`, 12000);
    try {
      await until('document.getElementById("pageImg").naturalWidth > 0', '页图就绪', 6000);
      await sleep(400);
      return;
    } catch (e) {
      if (attempt === 1) throw e;
      console.log(`       [openBook] ${id} 页图首载超时，重载一次`);
    }
  }
}

async function gotoPage(n) {
  await js(`window.__GK.showPage(${n})`);
  await until('document.getElementById("pageImg").naturalWidth > 0', `第 ${n + 1} 页`);
  await sleep(400);
}

/** 当前页的实现无关快照：文字、词框、时间戳、图片在视口里的位置 */
const snap = () => js(`(() => {
  const s = window.__GK.state, b = s.book, p = b.pages[s.page];
  const r = document.getElementById('pageImg').getBoundingClientRect();
  const a = window.__GK.audio;
  return {
    book: b.id, page: s.page, pageCount: b.pageCount,
    text: p.text,
    clip: p.audio,
    words: p.wordBoxes ? p.wordBoxes.words : p.text.split(/\\s+/).filter(Boolean),
    boxes: p.wordBoxes ? p.wordBoxes.boxes : null,
    times: p.wordTimes || null,
    img: { x: r.left, y: r.top, w: r.width, h: r.height },
    stopAt: s.stopAt,
    paused: a.paused,
    t: +a.currentTime.toFixed(3),
    rate: a.playbackRate,
    lit: [...document.querySelectorAll('.hit.word.lit')].map((n) => +n.dataset.k),
    on: [...document.querySelectorAll('.sentence .w.on')].map((n) => +n.dataset.k),
    autoRun: s.autoRun,
    audioFile: s.audioFile,
  };
})()`);

/** 词的视觉中心（用数据坐标算，不看被测元素的 rect —— 元素错位也要能测出来） */
function wordCenter(s, k) {
  const b = s.boxes[k];
  return { x: s.img.x + ((b[0] + b[2]) / 2) * s.img.w, y: s.img.y + ((b[1] + b[3]) / 2) * s.img.h };
}

const absWord = (s, k) => [s.clip[0] + s.times[k][0], s.clip[0] + s.times[k][1]];

async function waitPaused(ms = 4000) {
  await until('window.__GK.audio.paused === true', '音频停止', ms);
  return snap();
}

/** 从书架点卡片打开书（G1 的书 id 走不了 #/b/ 路由：app.js 的 route 正则只认 [A-Z]{2}，
 *  "G1-001" 里的 1 不是字母。这里走真实用户路径：书架卡片 → 阅读器。） */
async function openFromShelf(id, page = 0) {
  seq += 1;
  await send('Page.navigate', { url: `${BASE}?s=${seq}` });
  await until('window.__GK_READY__ === true', '书架就绪', 12000);
  await until('!document.getElementById("shelf").classList.contains("hidden")', '书架可见', 8000);
  const r = await js(`(() => { const c = document.querySelector('#grid .card[data-id="${id}"]');
    if (!c) return null; c.scrollIntoView({block:'center'}); const b = c.getBoundingClientRect();
    return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
  if (!r) throw new Error(`书架找不到 ${id} 的卡片`);
  await sleep(150);
  await clickAt(r.x, r.y);
  await until(`!!(window.__GK.state.book && window.__GK.state.book.id === ${JSON.stringify(id)})`, `打开书 ${id}`, 12000);
  await sleep(250);
  if (page) {
    await js(`window.__GK.showPage(${page})`);
    await until('document.getElementById("pageImg").naturalWidth > 0', `第 ${page + 1} 页`, 8000);
    await sleep(300);
  }
}

/** 等当前书的音频可播（G1 新增用例用，避免点词时音频还没加载完） */
async function waitAudio(expected, ms = 15000) {
  await until(`window.__GK.state.audioFile === ${JSON.stringify(expected)} && window.__GK.audio.readyState >= 1`, '音频就绪', ms);
}

/** 运行时扫描 G1，找一页"有/无 wordTimes 且有 wordBoxes"的页（不写死书号，数据变了也不假绿） */
async function scanG1(needTimes, maxClip = Infinity) {
  const man = await (await fetch(`${ORIGIN}/library/manifest.json`)).json();
  for (const b of man.books.filter((x) => x.series === 'G1')) {
    const doc = await (await fetch(`${ORIGIN}/library/books/G1/${String(b.no).padStart(3, '0')}.json`)).json();
    for (let i = 0; i < doc.pages.length; i++) {
      const p = doc.pages[i];
      if (!p.wordBoxes) continue;
      if (p.audio && p.audio[1] - p.audio[0] > maxClip) continue;
      const has = Array.isArray(p.wordTimes) && p.wordTimes.length === p.wordBoxes.words.length;
      // needTimes=false 时必须是"真的没有 wordTimes"；长度不匹配的页不算——
      // 那种页 snap().times 仍有值，会让前置检查误判（曾经就卡在这）
      if (needTimes) {
        if (has) return { b, doc, i, p };
      } else if (!p.wordTimes) {
        return { b, doc, i, p };
      }
    }
  }
  return null;
}

/* ───────────────── 用例 ───────────────── */
const CASES = [
  ['T1', '书架与视口（iPad 横屏尺度）', async () => {
    await send('Page.navigate', { url: `${BASE}?t=${Date.now()}` });
    await until('window.__GK_READY__ === true', '书架就绪');
    const vp = await js('({w: innerWidth, h: innerHeight, dpr: devicePixelRatio})');
    eq('T1.1', '全部 180 本（GK 70 + G1 110）', await js('document.querySelectorAll("#grid .card").length'), 180);
    truthy('T1.2', '视口按 iPad 横屏模拟（宽 ≥ 1024）', vp.w >= 1024, JSON.stringify(vp));
  }],

  ['T2', '真实点击书架卡片能开书', async () => {
    const r = await js(`(() => { const c = document.querySelectorAll('#grid .card')[0];
      const b = c.getBoundingClientRect(); return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
    await clickAt(r.x, r.y);
    await until('!!window.__GK.state.book', '卡片点击打开书籍', 8000);
    await sleep(300);
    eq('T2.1', '打开的是 GK 第 1 本', await js('window.__GK.state.book.id'), 'GK-001');
    eq('T2.2', '阅读器已显示', await js('document.getElementById("reader").classList.contains("hidden")'), false);
  }],

  ['T3', '返回书架', async () => {
    await js('document.getElementById("btnBack").click()');
    await sleep(300);
    eq('T3.1', '回到书架', await js('document.getElementById("shelf").classList.contains("hidden")'), false);
    eq('T3.2', '书籍已卸载', await js('window.__GK.state.book'), null);
    eq('T3.3', 'hash 已清空', await js('location.hash'), '');
  }],

  ['T4', '点击落点解析：就近吸附（D1/D2 的修法）', async () => {
    await openBook('GK-001', 0);
    await gotoPage(3);
    const s = await snap();

    eq('T4.1', '吸附候选数 = 词数量', await js('[...window.__GK.state.wordCenters].length'), s.words.length);

    // 词中心必须落在自己的调试描边里（渲染正确性，不是命中依据）
    const geo = await js(`(() => {
      const r = document.getElementById('overlay').getBoundingClientRect();
      return [...document.querySelectorAll('.hit.word')].map(n => {
        const b = n.getBoundingClientRect();
        return { k: +n.dataset.k, x: b.left - r.left, y: b.top - r.top, w: b.width, h: b.height };
      });
    })()`);
    const missed = geo.filter((g) => {
      const c = wordCenter(s, g.k);
      const relX = c.x - s.img.x;
      const relY = c.y - s.img.y;
      return relX < g.x - 0.5 || relX > g.x + g.w + 0.5 || relY < g.y - 0.5 || relY > g.y + g.h + 0.5;
    }).map((g) => g.k);
    eq('T4.2', '每个词的视觉中心都在自己的调试热区内', missed, []);

    // 核心：以词中心为圆心、在"到最近邻一半"以内，任何方向都必须解析到这个词
    const wrong = [];
    for (let k = 0; k < s.words.length; k++) {
      const c = wordCenter(s, k);
      let nearest = Infinity;
      for (let j = 0; j < s.words.length; j++) {
        if (j === k) continue;
        const o = wordCenter(s, j);
        nearest = Math.min(nearest, Math.hypot(o.x - c.x, o.y - c.y));
      }
      const safe = Math.max(3, Math.min(18, nearest * 0.45));
      for (const [dx, dy] of [[0, 0], [safe, 0], [-safe, 0], [0, safe], [0, -safe],
        [safe * 0.7, safe * 0.7], [-safe * 0.7, safe * 0.7],
        [safe * 0.7, -safe * 0.7], [-safe * 0.7, -safe * 0.7]]) {
        const got = await js(`window.__GK.snap(${(c.x - s.img.x + dx).toFixed(2)}, ${(c.y - s.img.y + dy).toFixed(2)})`);
        if (got !== k) wrong.push([k, s.words[k], +got, dx.toFixed(1), dy.toFixed(1)]);
      }
    }
    eq('T4.3', '每个词在其 Voronoi 内切圆内（任意方向）都吸附到自己', wrong, []);

    // 两词中点：必须落到更近的那个（说明不存在"重叠带由后插入者胜出"）
    const tie = [];
    for (let k = 0; k + 1 < s.words.length; k++) {
      const a = wordCenter(s, k);
      const b = wordCenter(s, k + 1);
      if (Math.abs(a.y - b.y) > 4) continue;          // 只测同一行
      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      const left = await js(`window.__GK.snap(${(mx - 2 - s.img.x).toFixed(2)}, ${(my - s.img.y).toFixed(2)})`);
      const right = await js(`window.__GK.snap(${(mx + 2 - s.img.x).toFixed(2)}, ${(my - s.img.y).toFixed(2)})`);
      if (left !== k || right !== k + 1) tie.push([k, s.words[k], left, right]);
    }
    eq('T4.4', '相邻两词中点左侧命中左词、右侧命中右词', tie, []);

    // 远离文字的地方不得误吸
    const far = await js(`window.__GK.snap(${s.img.w - 20}, ${s.img.h - 20})`);
    eq('T4.5', '画面右下角（远离文字）不吸附任何词', far, -1);

    // 窄词专项：61 号书第 4 页（全库最窄词所在页），点它必须命中它
    await openBook('GK-061', 0);
    const s61 = await snap();
    if (!s61.boxes) { record('T4.6', '最窄词专项', false, '61 号书该页没有词框'); return; }
    const narrow = s61.words.map((w, k) => ({ w, k, bw: (s61.boxes[k][2] - s61.boxes[k][0]) * s61.img.w }))
      .sort((a, b) => a.bw - b.bw)[0];
    const c61 = wordCenter(s61, narrow.k);
    const got61 = await js(`window.__GK.snap(${(c61.x - s61.img.x).toFixed(2)}, ${(c61.y - s61.img.y).toFixed(2)})`);
    eq('T4.6', `最窄词 "${narrow.w}"（${narrow.bw.toFixed(1)}px 宽）点中心仍命中自己`, got61, narrow.k);

    // —— 以下用**真实指针**验"用户点下去走的就是吸附"，不经过 __GK.snap ——
    // 期望值用独立神谕算：最近词中心（与实现无关）
    // 独立神谕：与实现同一套两级规则（框内优先 → 否则最近中心），但由测试自己算
    const oracle = (s, px, py) => {
      let hit = -1;
      let hd = Infinity;
      for (let k = 0; k < s.words.length; k++) {
        const b = s.boxes[k];
        if (px >= b[0] * s.img.w && px <= b[2] * s.img.w && py >= b[1] * s.img.h && py <= b[3] * s.img.h) {
          const cx = (b[0] + b[2]) / 2 * s.img.w;
          const cy = (b[1] + b[3]) / 2 * s.img.h;
          const d = Math.hypot(cx - px, cy - py);
          if (d < hd) { hd = d; hit = k; }
        }
      }
      if (hit >= 0) return { k: hit, d: hd, via: 'box' };
      let best = -1;
      let bd = Infinity;
      for (let k = 0; k < s.words.length; k++) {
        const b = s.boxes[k];
        const cx = (b[0] + b[2]) / 2 * s.img.w;
        const cy = (b[1] + b[3]) / 2 * s.img.h;
        const d = Math.hypot(cx - px, cy - py);
        if (d < bd) { bd = d; best = k; }
      }
      return { k: best, d: bd, via: 'nearest' };
    };
    const inAnyBox = (s, px, py, m = 0) => s.boxes.some((b) =>
      px >= b[0] * s.img.w - m && px <= b[2] * s.img.w + m &&
      py >= b[1] * s.img.h - m && py <= b[3] * s.img.h + m);

    // T4.7：同一行相邻两词之间的空隙（词框外）——真实点击必须命中更近的那个词
    await openBook('GK-001', 0);
    await gotoPage(3);
    let s4 = await snap();
    if (!s4.boxes || !s4.times) {
      record('T4.7', '真实点击词间空隙 → 命中最近词', false, `上下文缺数据: book=${s4.book} page=${s4.page}`);
      record('T4.8', '真实点击跨行词对中点 → 命中最近词', false, '上下文缺数据');
      record('T4.9', '两行句子中间的空隙 → 命中最近词', false, '上下文缺数据');
      return;
    }
    const gapProbes = [];
    for (let k = 0; k + 1 < s4.words.length && gapProbes.length < 3; k++) {
      const a = s4.boxes[k];
      const b = s4.boxes[k + 1];
      if (Math.abs((a[1] + a[3]) - (b[1] + b[3])) > 0.01) continue;
      const gx = ((a[2] + b[0]) / 2) * s4.img.w;
      const gy = ((a[1] + a[3]) / 2) * s4.img.h;
      if (inAnyBox(s4, gx, gy, 2)) continue;
      gapProbes.push({ k, gx, gy, expect: oracle(s4, gx, gy).k });
    }
    const gapBad = [];
    truthy('T4.7a', '同行空隙探针数 > 0（防空集通过）', gapProbes.length > 0, `probes=${gapProbes.length}`);
    for (const pr of gapProbes) {
      if (pr.expect < 0) continue;
      await clickAt(pr.gx + s4.img.x, pr.gy + s4.img.y);
      await sleep(45);
      const m = await snap();
      const want = Math.round(absWord(s4, pr.expect)[1] * 100) / 100;
      const gotWord = Math.round((m.stopAt ?? -1) * 100) / 100;
      if (gotWord !== want) gapBad.push({ gap: pr.k, expect: pr.expect, want, got: gotWord });
    }
    eq('T4.7', '真实点击词间空隙 → 命中最近词（不是"后插入者胜出"）', gapBad, []);

    // T4.8 / T4.9：多行页（04 号书 p4，两行、有逐词时间戳）上的跨行场景
    await openBook('GK-004', 0);
    const s35 = await snap();
    const hs = (s35.boxes || []).map((b) => b[3] - b[1]).sort((a, b) => a - b);
    const medH = hs[Math.floor(hs.length / 2)] || 0.06;
    const cyOf = (k) => (s35.boxes[k][1] + s35.boxes[k][3]) / 2;

    const crossBad = [];
    const crossPairs = [];
    for (let i = 0; i < (s35.words || []).length; i++) {
      for (let j = i + 1; j < s35.words.length; j++) {
        if (Math.abs(cyOf(i) - cyOf(j)) <= medH * 0.8) continue;      // 同行，跳过
        // 以较近者为中心、朝另一行偏 35%，确保落在吸附半径内（确定性采样）
        const ci = { x: (s35.boxes[i][0] + s35.boxes[i][2]) / 2 * s35.img.w, y: cyOf(i) * s35.img.h };
        const cj = { x: (s35.boxes[j][0] + s35.boxes[j][2]) / 2 * s35.img.w, y: cyOf(j) * s35.img.h };
        const near = Math.hypot(ci.x - cj.x, ci.y - cj.y);
        const mx = ci.x + (cj.x - ci.x) * 0.35;
        const my = ci.y + (cj.y - ci.y) * 0.35;
        if (inAnyBox(s35, mx, my, 2)) continue;
        const ex = oracle(s35, mx, my);
        if (ex.k !== i) continue;                                      // 只取"较近者就是期望"的点
        crossPairs.push({ i, j, mx, my, expect: i, dist: near });
        if (crossPairs.length >= 2) break;
      }
      if (crossPairs.length >= 2) break;
    }
    truthy('T4.8a', '跨行词对探针数 > 0（防空集通过）', crossPairs.length > 0,
      `pairs=${crossPairs.length} medH=${medH.toFixed(4)}`);
    for (const pr of crossPairs) {
      await clickAt(pr.mx + s35.img.x, pr.my + s35.img.y);
      await sleep(45);
      const m = await snap();
      // 用"哪个词被点亮"判定命中的词——由 playWord 同步设置，不受播放时长影响
      if (JSON.stringify(m.lit) !== JSON.stringify([pr.expect])) {
        crossBad.push({ pair: [pr.i, pr.j], expect: pr.expect, lit: m.lit });
      }
    }
    eq('T4.8', '真实点击跨行点 → 点亮的是最近词', crossBad, []);

    // T4.9：两行之间的中点（比词对中点更靠两行正中）
    if (s35.boxes && s35.times && s35.boxes.length >= 6) {
      const r1 = s35.boxes[0];
      const r2 = s35.boxes[5];
      const mid = ((r1[1] + r1[3]) / 2 + (r2[1] + r2[3]) / 2) / 2 * s35.img.h;
      const mx = ((r1[0] + r1[2]) / 2) * s35.img.w;
      const want = oracle(s35, mx, mid).k;
      await clickAt(mx + s35.img.x, mid + s35.img.y);
      await sleep(45);
      const m = await snap();
      eq('T4.9', '多行页两行之间的空隙 → 命中最近词',
        Math.round((m.stopAt ?? -1) * 100) / 100, Math.round(absWord(s35, want)[1] * 100) / 100);
    } else {
      record('T4.9', '多行页两行之间的空隙 → 命中最近词', false,
        `04 号书数据不满足: boxes=${!!s35.boxes} times=${!!s35.times}`);
    }

  }],

  ['T5', '真实指针点每个词都命中该词，且播完停在词尾', async () => {
    await openBook('GK-001', 0);
    await gotoPage(3);
    const s0 = await snap();
    if (!s0.boxes || !s0.times) {
      record('T5', '真实指针点每个词都命中该词', false,
        `页面缺词框或时间戳: book=${s0.book} page=${s0.page}`);
      return;
    }
    const n = Math.min(s0.words.length, 5);
    for (let k = 0; k < n; k++) {
      const s = await snap();
      const c = wordCenter(s, k);
      await clickAt(c.x, c.y);
      // 短词（比如 cheese. 只有 0.22s）会在 sleep 里播完，所以先看 stopAt 这个"声明"
      await sleep(45);

      const mid = await snap();
      const [wa, wb] = absWord(s, k);
      eq(`T5.${k + 1}a`, `点"${s.words[k]}"→ stopAt 是这个词的终点（不是整句终点）`,
        Math.round(mid.stopAt * 100) / 100, Math.round(wb * 100) / 100);
      truthy(`T5.${k + 1}b`, `点"${s.words[k]}"→ 播放已启动`, mid.paused === false || mid.t >= wa - 0.05,
        `paused=${mid.paused} t=${mid.t}`);
      truthy(`T5.${k + 1}c`, `点"${s.words[k]}"→ 起点落在该词区间`, mid.t >= wa - 0.2 && mid.t <= wb + 0.05,
        `t=${mid.t} 词区间=[${wa.toFixed(2)}, ${wb.toFixed(2)}]`);
      eq(`T5.${k + 1}d`, `点"${s.words[k]}"→ 只有一个词高亮`, mid.on, [k]);
      eq(`T5.${k + 1}e`, `点"${s.words[k]}"→ 只有该词热区点亮`, mid.lit, [k]);

      const end = await waitPaused(3000);
      near(`T5.${k + 1}f`, `"${s.words[k]}"播完自动停在词尾`, end.t, wb, 0.18);
      eq(`T5.${k + 1}g`, `"${s.words[k]}"播完高亮清零`, [end.on, end.lit], [[], []]);
    }
  }],

  ['T6', '点"再读一遍"：整句播完停在句尾并清高亮', async () => {
    await gotoPage(5);
    const s = await snap();
    const btn = await js(`(() => { const b = document.getElementById('btnReplay').getBoundingClientRect();
      return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
    await clickAt(btn.x, btn.y);
    await sleep(120);
    const mid = await snap();
    truthy('T6.1', '整句播放中', mid.paused === false, `paused=${mid.paused}`);
    eq('T6.2', '整句的所有词都高亮', mid.on.length, s.words.length);
    near('T6.3', '停点声明为句尾', mid.stopAt, s.clip[1], 0.02);
    const end = await waitPaused(6000);
    near('T6.4', '停在句尾', end.t, s.clip[1], 0.2);
    eq('T6.5', '播完高亮清零', [end.on, end.lit], [[], []]);
  }],

  ['T7', '播放中翻页 → 旧音频必须停', async () => {
    await gotoPage(2);
    const s = await snap();
    const c = wordCenter(s, 1);
    await clickAt(c.x, c.y);
    await sleep(200);
    truthy('T7.1', '翻页前在播', (await snap()).paused === false, '');
    await js('document.getElementById("btnNext").click()');
    await sleep(220);
    const after = await snap();
    eq('T7.2', '翻页后音频已暂停', after.paused, true);
    eq('T7.3', '翻页后 stopAt 已清空', after.stopAt, null);
    const t1 = after.t;
    await sleep(400);
    near('T7.4', '翻页后 currentTime 不再前进', (await snap()).t, t1, 0.03);
    eq('T7.5', '翻页后高亮清零', [after.on, after.lit], [[], []]);
  }],

  ['T8', '语速：实际播放速率跟着变', async () => {
    const measure = async () => {
      const s = await snap();
      const btn = await js(`(() => { const b = document.getElementById('btnReplay').getBoundingClientRect();
        return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
      await clickAt(btn.x, btn.y);
      await until('window.__GK.audio.paused === false', '开始播放', 3000);
      await sleep(150);
      const t0 = (await snap()).t;
      await sleep(800);
      const t1 = (await snap()).t;
      await js('window.__GK.audio.pause()');
      await sleep(60);
      return t1 - t0;
    };
    const reloadAt = async (rate) => {
      await js(`localStorage.setItem('gk-rate','${rate}'); location.reload()`);
      await until('!!(window.__GK && window.__GK.state.book)', 'reload', 10000);
      await until('document.getElementById("pageImg").naturalWidth > 0', 'img');
      await gotoPage(1);
    };

    await reloadAt(1);
    const d1 = await measure();

    await reloadAt(0.75);
    eq('T8.1', '0.75× 已应用', (await snap()).rate, 0.75);
    const d075 = await measure();

    const ratio = Math.round((d075 / d1) * 100) / 100;
    near('T8.2', '0.75× 的实际推进约为 1× 的 75%', ratio, 0.75, 0.15);
  }],

  ['T9', '整本连播到底：页码严格递增、结束态正确', async () => {
    await openBook('GK-001', 0);
    await js('document.getElementById("btnPlay").click()');
    await sleep(300);
    truthy('T9.1', '连播中 autoRun=true', await js('window.__GK.state.autoRun'), '');
    const pc = (await snap()).pageCount;
    const seen = [];
    for (let i = 1; i < pc; i++) {
      await until(`window.__GK.state.page === ${i}`, `自动翻到第 ${i + 1} 页`, 9000);
      seen.push(i);
    }
    eq('T9.2', '页码逐页走完', seen, Array.from({ length: pc - 1 }, (_, i) => i + 1));
    await until('window.__GK.state.autoRun === false', '连播结束', 6000);
    eq('T9.3', '结束后 autoRun=false', await js('window.__GK.state.autoRun'), false);
    eq('T9.4', '结束提示存在', (await js('document.getElementById("toast").textContent')).includes('读完'), true);
    eq('T9.5', '停在最后一页（不循环）', await js('window.__GK.state.page'), pc - 1);
  }],

  ['T10', '快速连点不串词', async () => {
    await openBook('GK-001', 0);
    await gotoPage(3);
    const s = await snap();
    const centers = [0, 2, 4].map((k) => wordCenter(s, k));
    for (const c of centers) {
      await clickAt(c.x, c.y);
      await sleep(60);
    }
    await sleep(45);
    const mid = await snap();
    eq('T10.1', '最终只高亮最后一个词', mid.on, [4]);
    eq('T10.2', '停点属于最后一个词', Math.round(mid.stopAt * 100) / 100, Math.round(absWord(s, 4)[1] * 100) / 100);
    truthy('T10.3', '没有因为连点而串到后面的页', (await snap()).page, 3);
  }],

  // ── 以下 3 个用例补 G1 覆盖面（74 项只打了 GK 三本书；只增不减）──
  ['T12', 'G1：真实指针点词只读该词，播完停在词尾', async () => {
    const f = await scanG1(true, 20);
    if (!f) {
      record('T12', 'G1 点词只读该词', false, 'G1 找不到 wordTimes + wordBoxes 的页（数据缺失，不能靠 GK 通过代替）');
      return;
    }
    await openFromShelf(f.b.id, f.i);
    await waitAudio(f.b.audio);
    await sleep(350);
    const s = await snap();
    if (!s.times || !s.boxes) {
      record('T12', 'G1 点词只读该词', false, `${f.b.id} p${f.p.n} 打开后没有词框/时间戳`);
      return;
    }
    const dur = s.clip[1] - s.clip[0];
    // 优先选 0.12–1.2s 的普通词；避免 4s 这种 CTC 离群长词把用例拖慢
    let k = s.times.findIndex((t) => t[1] - t[0] >= 0.12 && t[1] - t[0] <= 1.2 && t[1] < dur - 0.1);
    if (k < 0) {
      let best = Infinity;
      s.times.forEach((t, i) => {
        const d = Math.abs(t[1] - t[0] - 0.6);
        if (t[1] < dur - 0.05 && d < best) { best = d; k = i; }
      });
    }
    if (k < 0) k = 0;
    const [wa, wb] = absWord(s, k);
    const c = wordCenter(s, k);
    await clickAt(c.x, c.y);
    await sleep(45);
    const mid = await snap();
    eq('T12.1', `G1 ${f.b.id} p${f.p.n} 点"${s.words[k]}"→ stopAt 是这个词的终点`,
      Math.round(mid.stopAt * 100) / 100, Math.round(wb * 100) / 100);
    truthy('T12.2', 'G1 点词→ 播放已启动', mid.paused === false || (mid.t >= wa - 0.05 && mid.t <= wb + 0.05),
      `paused=${mid.paused} t=${mid.t}`);
    eq('T12.3', 'G1 点词→ 只有一个词高亮', mid.on, [k]);
    eq('T12.4', 'G1 点词→ 只有该词热区点亮', mid.lit, [k]);
    truthy('T12.5', 'G1 点词的词段 ≥ 60ms（点下去听得到）', s.times[k][1] - s.times[k][0] >= 0.06,
      `词段=${((s.times[k][1] - s.times[k][0]) * 1000).toFixed(0)}ms`);
    const end = await waitPaused(Math.max(4000, (wb - wa) * 1000 + 2500));
    near('T12.6', 'G1 点词播完自动停在词尾', end.t, wb, 0.18);
  }],

  ['T13', 'G1：没有 wordTimes 的页点词回落读整句', async () => {
    let f = await scanG1(false, 20);
    let real = !!f;
    if (!f) {
      // 库里已经没有天然的"有词框但无 wordTimes"页（修复后覆盖率上来了），
      // 改成在浏览器里临时摘掉一页的 wordTimes，专门验证回落分支。
      f = await scanG1(true, 20);
      if (!f) {
        record('T13', 'G1 无 wordTimes 页回落整句', false, 'G1 找不到 wordBoxes 的页（数据缺失）');
        return;
      }
      await openFromShelf(f.b.id, f.i);
      await waitAudio(f.b.audio);
      // 关键：在当前页对象上摘掉 wordTimes 并重绘，随后**立刻**确认它真的没了
      // （之前多调了一次 openBook 会重新拉 json，把删除覆盖掉）
      for (let k = 0; k < 12; k += 1) {
        await js(`(() => { const s = window.__GK.state; delete s.book.pages[s.page].wordTimes; })()`);
        await js('window.__GK.showPage(window.__GK.state.page)');
        const still = await js('window.__GK.state.book.pages[window.__GK.state.page].wordTimes');
        if (!still) break;
        await sleep(150);
      }
      await sleep(300);
    } else {
      await openFromShelf(f.b.id, f.i);
      await waitAudio(f.b.audio);
      await sleep(450);          // 等页面稳定，否则 snap() 可能读到上一本书的状态
    }
    await sleep(350);
    let s = await snap();
    // 若页面仍带着 wordTimes（数据/缓存状态不一致），就地摘掉再重绘，
    // 让后续断言专注验证"没有时间戳时的回落行为"这一件事
    if (s.times) {
      await js('(() => { const st = window.__GK.state; delete st.book.pages[st.page].wordTimes; })()');
      await js('window.__GK.showPage(window.__GK.state.page)');
      await sleep(400);
      s = await snap();
    }
    if (!s.boxes) {
      record('T13', 'G1 无 wordTimes 页回落整句', false,
        `${f.b.id} p${f.p.n} 没有词框: words=${s.words.length}`);
      return;
    }
    truthy('T13.0', 'G1 使用真实无 wordTimes 页（不是临时删除）', real,
      real ? '' : '当前库所有 G1 有词框的页都有 wordTimes；本轮用浏览器内删除验证回落逻辑');
    const c = wordCenter(s, 0);
    await clickAt(c.x, c.y);
    await sleep(80);
    const mid = await snap();
    eq('T13.1', `G1 ${f.b.id} p${f.p.n} 点词→ 整句所有词高亮`, mid.on.length, s.words.length);
    near('T13.2', '停点声明为句尾', mid.stopAt ?? -1, s.clip[1], 0.02);
    eq('T13.3', '没有点亮单个词热区', mid.lit, []);
    truthy('T13.4', '整句播放已启动', mid.paused === false, `paused=${mid.paused}`);
  }],

  ['T14', 'G1：点"再读一遍"整句播完停在句尾', async () => {
    const f = await scanG1(true, 10);
    if (!f) {
      record('T14', 'G1 整句重播', false, 'G1 找不到 wordTimes + wordBoxes 的页（数据缺失）');
      return;
    }
    await openFromShelf(f.b.id, f.i);
    await waitAudio(f.b.audio);
    await sleep(350);
    const s = await snap();
    const btn = await js(`(() => { const b = document.getElementById('btnReplay').getBoundingClientRect();
      return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
    await clickAt(btn.x, btn.y);
    await sleep(120);
    const mid = await snap();
    truthy('T14.1', 'G1 整句播放中', mid.paused === false, `paused=${mid.paused}`);
    eq('T14.2', 'G1 整句的所有词都高亮', mid.on.length, s.words.length);
    near('T14.3', 'G1 停点声明为句尾', mid.stopAt ?? -1, s.clip[1], 0.02);
    const end = await waitPaused(Math.max(8000, (s.clip[1] - s.clip[0]) * 1000 + 2500));
    near('T14.4', 'G1 停在句尾', end.t, s.clip[1], 0.2);
    eq('T14.5', 'G1 播完高亮清零', [end.on, end.lit], [[], []]);
  }],

  // ── 内容真实性：结构对 ≠ 内容对 ──────────────────────────
  // 事故：180 张封面全是白纸（构建裁错页），90 项断言全绿。
  // 原因：T1 只数卡片，没有任何断言看"图里有什么"。白图是合法图像，
  //       naturalWidth 也是真，所以只能读像素。
  ['T15', '内容真实性：封面不是白纸', async () => {
    await send('Page.navigate', { url: `${BASE}?t=${Date.now()}` });
    await until('window.__GK_READY__ === true', '书架就绪');

    const stat = await js(`(async () => {
      const imgs = [...document.querySelectorAll('#grid .card img')].slice(0, 24);
      await Promise.all(imgs.map((i) => (i.complete && i.naturalWidth)
        ? null
        : new Promise((r) => { i.onload = i.onerror = r; })));
      const out = [];
      for (const img of imgs) {
        const name = img.src.split('/').slice(-2).join('/');
        if (!img.naturalWidth) { out.push({ name, ok: false, why: '加载失败' }); continue; }
        const w = Math.min(64, img.naturalWidth);
        const h = Math.min(64, img.naturalHeight);
        const c = document.createElement('canvas');
        c.width = w; c.height = h;
        const g = c.getContext('2d');
        g.drawImage(img, 0, 0, w, h);
        const d = g.getImageData(0, 0, w, h).data;
        let sum = 0; let sum2 = 0; let n = 0; let whites = 0;
        for (let i = 0; i < d.length; i += 4) {
          const l = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
          sum += l; sum2 += l * l; n += 1;
          if (l > 245) whites += 1;
        }
        const mean = sum / n;
        const sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
        out.push({ name, mean: +mean.toFixed(1), sd: +sd.toFixed(1),
                   white: +(whites / n).toFixed(2),
                   ok: sd >= 12 && whites / n < 0.95 });
      }
      return out;
    })()`);

    const notLoaded = stat.filter((x) => x.why);
    eq('T15.1', '抽样封面全部加载成功', notLoaded, []);
    const blanks = stat.filter((x) => !x.ok && !x.why);
    eq('T15.2', '封面不是空白图（像素标准差 ≥12 且纯白占比 <95%）', blanks, []);
    truthy('T15.3', '抽样数量 ≥12（防空集通过）', stat.length >= 12, `n=${stat.length}`);
  }],

  ['T16', '内容真实性：页图不是白纸', async () => {
    const bad = [];
    let checked = 0;
    for (const id of ['GK-001', 'GK-035', 'G1-001']) {
      await openBook(id, 0);
      for (const idx of [0, 2, 4]) {
        if (idx > 0) await gotoPage(idx);
        const st = await js(`(() => {
          const img = document.getElementById('pageImg');
          if (!img.naturalWidth) return { why: '未加载' };
          const w = Math.min(64, img.naturalWidth);
          const h = Math.min(64, img.naturalHeight);
          const c = document.createElement('canvas');
          c.width = w; c.height = h;
          const g = c.getContext('2d');
          g.drawImage(img, 0, 0, w, h);
          const d = g.getImageData(0, 0, w, h).data;
          let sum = 0; let sum2 = 0; let n = 0; let whites = 0;
          for (let i = 0; i < d.length; i += 4) {
            const l = d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114;
            sum += l; sum2 += l * l; n += 1;
            if (l > 245) whites += 1;
          }
          const mean = sum / n;
          const sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean));
          return { mean: +mean.toFixed(1), sd: +sd.toFixed(1), white: +(whites / n).toFixed(2),
                   ok: sd >= 10 && whites / n < 0.97 };
        })()`);
        checked += 1;
        if (!st.ok) bad.push({ book: id, page: idx + 1, ...st });
      }
    }
    truthy('T16.1', '页图抽样 ≥6 张', checked >= 6, `n=${checked}`);
    eq('T16.2', '页图不是空白图', bad, []);
  }],

  // ── 错误路径：数据坏了不能白屏、不能崩 ──────────────────
  ['T17', '错误路径：音频 404 时降级但不崩', async () => {
    await send('Fetch.enable', { patterns: [{ urlPattern: '*.m4a', requestStage: 'Request' }] });
    fetchRules.push({ match: '.m4a', fail: true });
    try {
      await openBook('GK-001', 0);
      await until('window.__GK.state.audioFile === null', '音频被标记为不可用', 10000);
      eq('T17.1', '音频加载失败时 audioFile 置空', await js('window.__GK.state.audioFile'), null);
      const toastText = await js('(document.querySelector(".toast") || {}).textContent || ""');
      truthy('T17.2', '给出了失败提示', /失败|打不开|音频/.test(toastText), `toast="${toastText}"`);
      await gotoPage(2);
      eq('T17.3', '音频失败仍能正常翻页', await js('window.__GK.state.page'), 2);
      truthy('T17.4', '页图仍然渲染', await js('document.getElementById("pageImg").naturalWidth > 0'), true);
    } finally {
      fetchRules.length = 0;
      await send('Fetch.disable');
    }
  }],

  ['T18', '错误路径：book.json 404 时提示且不塞半截数据', async () => {
    await send('Fetch.enable', { patterns: [{ urlPattern: '*/books/*', requestStage: 'Request' }] });
    fetchRules.push({ match: '/books/', fail: true });
    try {
      await send('Page.navigate', { url: `${BASE}?c=err1#/b/GK-002` });
      // #toast 是常驻元素，必须等文案非空，否则会读到上一次的空串
      await until('(document.getElementById("toast")?.textContent || "").trim().length > 0',
        '出现提示', 10000);
      const txt = await js('document.getElementById("toast").textContent');
      truthy('T18.1', '提示文案说明打不开', /打不开|失败/.test(txt), `toast="${txt}"`);
      eq('T18.2', '没有把半截书写进状态', await js('window.__GK.state.book'), null);
      truthy('T18.3', '书架仍在（没有白屏）', await js('!document.getElementById("shelf").classList.contains("hidden")'), true);
    } finally {
      fetchRules.length = 0;
      await send('Fetch.disable');
    }
  }],

  ['T19', '修复后的批注页：文字已恢复，点词读该词', async () => {
    await openBook('GK-045', 0);
    // GK-045 p4 原文夹着印前批注（OVERALL: interior art...），修复后应按字号剔掉批注、
    // 恢复出正文 "Look at hat. My hat is big."。旧断言"该页文字为空"已作废。
    const txt = await js('window.__GK.state.book.pages[window.__GK.state.page].text');
    truthy('T19.1', '批注页的正文被恢复（不再是空）', (txt || '').length > 0, `text="${txt}"`);
    truthy('T19.2', '恢复的文字里没有印前批注', !/interior art|Art page|OVERALL:|Adjust/i.test(txt),
      `text="${txt}"`);
    const s = await snap();
    truthy('T19.3', '该页有词框（图上可以点词）', !!s.boxes && s.words.length >= 3,
      `words=${s.words.length} boxes=${!!s.boxes}`);
    if (s.boxes && s.times) {
      const c = wordCenter(s, 0);
      await clickAt(c.x, c.y);
      await sleep(80);
      const mid = await snap();
      eq('T19.4', '点第一个词只点亮它', mid.lit, [0]);
    }
  }],

  ['T20', '真重启（重新加载页面）后回到上次那一页', async () => {
    await openBook('G1-002', 0);
    await gotoPage(4);
    const before = await js('window.__GK.state.page');
    eq('T20.1', '翻到第 5 页', before, 4);
    // 整页重新加载 = 模拟杀进程后重开，只靠 localStorage 恢复
    await send('Page.navigate', { url: `${BASE}?restart=${Date.now()}#/b/G1-002` });
    await until('!!(window.__GK && window.__GK.state.book)', '重启后重新打开书', 12000);
    await sleep(700);
    eq('T20.2', '重启后仍是同一本书', await js('window.__GK.state.book.id'), 'G1-002');
    eq('T20.3', '重启后回到上次那一页', await js('window.__GK.state.page'), before);
  }],

  // 需要看页面异常，放最后
  ['T11', '全程无未捕获异常', async () => {
    eq('T11.1', '没有页面异常', pageErrors.slice(0, 5), []);
  }],
];

/* ───────────────── 运行 ───────────────── */
async function main() {
  const url = await connect();
  ws = new WebSocket(url);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id);
      pending.delete(m.id);
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result);
    } else if (m.method === 'Runtime.exceptionThrown') {
      pageErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text);
    } else if (m.method === 'Fetch.requestPaused') {
      // 请求拦截：默认全部放行，指定 URL 片段命中时按 plan 处理（用来造 404）
      const url = m.params.request.url;
      const rule = fetchRules.find((r) => url.includes(r.match));
      if (rule && rule.fail) {
        send('Fetch.failRequest', { requestId: m.params.requestId, errorReason: 'Failed' }).catch(() => {});
      } else {
        send('Fetch.continueRequest', { requestId: m.params.requestId }).catch(() => {});
      }
    }
  };
  await send('Runtime.enable');
  await send('Page.enable');
  // 关缓存：库重建后，测试脚本 fetch 到的 book.json 和 App 取到的可能不是同一份，
  // 会导致"扫描说有/页面说没有"这类自相矛盾（曾经把 T13 卡死在这）
  await send('Network.enable');
  await send('Network.setCacheDisabled', { cacheDisabled: true });
  // iPad 11" 横屏 @2x
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1194, height: 834, deviceScaleFactor: 2, mobile: false,
  });
  await send('Page.navigate', { url: BASE });
  await until('document.readyState === "complete"', '初始加载');
  await js('localStorage.clear()');

  for (const [id, name, fn] of CASES) {
    const tr = await js(`(() => { const s = window.__GK && window.__GK.state;
      return s ? { book: s.book && s.book.id, page: s.page, hash: location.hash, url: location.search } : null; })()`).catch(() => null);
    console.log(`\n${id}  ${name}   [trace ${JSON.stringify(tr)}]`);
    try {
      await fn();
    } catch (e) {
      record(id, name, false, '用例抛错: ' + e.message + ' | ' + String(e.stack || '').split('\n').slice(1,3).join(' <- '));
    }
  }

  const failed = results.filter((r) => !r.ok);
  console.log('\n' + '─'.repeat(66));
  console.log(`共 ${results.length} 项断言，通过 ${results.length - failed.length}，失败 ${failed.length}`);
  // 机器可读的汇总行，供 mutation runner 解析
  console.log(`RESULT pass=${results.length - failed.length} fail=${failed.length} total=${results.length}`);
  if (failed.length) {
    console.log('\n失败项:');
    for (const f of failed) console.log(`  ❌ ${f.id} ${f.name}\n       ${f.detail}`);
    console.log('FAILID ' + failed.map((f) => f.id).join(' '));
  }
  ws.close();
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => { console.error('测试框架错误:', e.message); process.exit(2); });