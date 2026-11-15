/* 小书虫 GK —— 阅读器
 *
 * 设计约束（为了能原样塞进 Capacitor/WKWebView）：
 *   1. 不依赖 HTTP Range  —— 音频取成 Blob 再播，WKWebView 里也能 seek
 *   2. 不依赖固定路径     —— 自动在 ./library/ 和 ../library/ 之间探测
 *   3. 不依赖构建工具     —— 纯 ES5+ 语法，直接丢进 www/ 就能跑
 */
const RATES = [0.75, 1, 1.25];
const $ = (id) => document.getElementById(id);
const noPad3 = (n) => String(n).padStart(3, '0');

let LIB = '../library/';           // 启动时探测后覆盖

const state = {
  manifest: [],
  series: [],
  book: null,
  page: 0,
  filter: 'all',
  autoRun: false,
  raf: 0,
  stopAt: null,
  rate: 1,
  audioFile: null,
};

const audio = new Audio();
audio.preload = 'auto';
let audioUrl = null;               // 当前书的 Blob URL
let audioReady = Promise.resolve();  // 音频就绪的 promise

/* ───────────────────── 小工具 ───────────────────── */
function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 1600);
}
const progress = () => { try { return JSON.parse(localStorage.getItem('gk-progress') || '{}'); } catch { return {}; } };
const saveProgress = (id, p) => { const o = progress(); o[id] = p; localStorage.setItem('gk-progress', JSON.stringify(o)); };

/* ───────────────────── 资源定位 ───────────────────── */
/** 开发时在 web/ 下（../library/），打包进 www/ 后是同级的 ./library/ */
async function resolveLib() {
  for (const base of ['../library/', 'library/']) {
    try {
      const r = await fetch(base + 'manifest.json');
      if (r.ok) return base;
    } catch { /* 试下一个 */ }
  }
  return null;
}

/* ───────────────────── 语速 ───────────────────── */
function applyRate() {
  audio.preservesPitch = true;
  audio.mozPreservesPitch = true;
  audio.webkitPreservesPitch = true;
  audio.playbackRate = state.rate;
  const b = $('btnRate');
  if (b) b.textContent = `${state.rate}×`;
}
function initRate() {
  const saved = parseFloat(localStorage.getItem('gk-rate'));
  state.rate = RATES.includes(saved) ? saved : 1;
  applyRate();
}

/* ───────────────────── 书架 ───────────────────── */
function renderTabs() {
  const keys = ['all', ...state.series.map((s) => s.key)];
  const el = $('tabs');
  el.innerHTML = keys.map((k) => {
    const n = k === 'all' ? state.manifest.length
      : state.manifest.filter((b) => b.series === k).length;
    const label = k === 'all' ? '全部' : (state.series.find((s) => s.key === k) || {}).label || k;
    return `<button class="tab ${k === state.filter ? 'on' : ''}" data-l="${k}">${label}<i>${n}</i></button>`;
  }).join('');
  el.onclick = (e) => {
    const b = e.target.closest('.tab');
    if (!b) return;
    state.filter = b.dataset.l;
    renderTabs();
    renderGrid();
  };
}

function renderGrid() {
  const done = progress();
  const list = state.manifest.filter((b) => state.filter === 'all' || b.series === state.filter);
  $('grid').innerHTML = list.map((b) => `
    <div class="card" data-id="${b.id}">
      <img loading="lazy" src="${LIB}${b.cover}" alt="">
      <div class="cap"><span class="ttl">${b.no} ${b.title}</span>
        <em>· ${b.level}</em>${b.hasAudio === false ? ' <span class="mute">只看图</span>' : ''}${
        done[b.id] != null ? ' <span class="done">✓</span>' : ''}</div>
    </div>`).join('');
  $('grid').onclick = (e) => {
    const c = e.target.closest('.card');
    if (c) openBook(c.dataset.id);
  };
}

/* ───────────────────── 打开 / 关闭 ───────────────────── */
async function openBook(id) {
  const meta = state.manifest.find((b) => b.id === id);
  if (!meta) { toast('找不到这本书'); return; }
  // 注意：404 会拿到 Response，但断网/请求被拦会 reject —— 两种都要落到"打不开"
  const book = await fetch(`${LIB}books/${meta.series}/${noPad3(meta.no)}.json`)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  if (!book) { toast('这本书打不开'); return; }

  state.book = book;
  state.page = Math.min(Math.max(progress()[id] ?? 0, 0), book.pageCount - 1);

  $('rTitle').textContent = `${book.series} ${book.no} · ${book.title}`;
  $('dots').innerHTML = '<i></i>'.repeat(book.pageCount);
  $('shelf').classList.add('hidden');
  $('reader').classList.remove('hidden');
  $('btnPlay').disabled = book.hasAudio === false;
  $('btnReplay').disabled = book.hasAudio === false;

  showPage(state.page);

  if (book.hasAudio === false || !book.audio) {
    state.audioFile = null;
    audio.removeAttribute('src');
    return;
  }

  // 音频取成 Blob：不依赖服务器 Range，WKWebView 里同样可以 seek
  audioReady = (async () => {
    try {
      const res = await fetch(`${LIB}${book.audio}`);
      if (!res.ok) throw new Error(res.status);
      const blob = await res.blob();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      audioUrl = URL.createObjectURL(blob);
      state.audioFile = book.audio;
      audio.src = audioUrl;
      audio.load();
      applyRate();
    } catch (e) {
      toast('音频加载失败');
      state.audioFile = null;
    }
  })();
  await audioReady;
}

function closeBook() {
  stopAuto();
  state.book = null;
  if (audioUrl) { URL.revokeObjectURL(audioUrl); audioUrl = null; }
  audio.removeAttribute('src');
  $('reader').classList.add('hidden');
  $('shelf').classList.remove('hidden');
  renderGrid();
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
}

/* ───────────────────── 渲染一页 ───────────────────── */
function showPage(i, autoplay = false) {
  if (!state.book) return;
  stopPlayback();
  const p = state.book.pages[i];
  if (!p) return;
  state.page = i;
  saveProgress(state.book.id, i);

  $('rSub').textContent = `Level ${state.book.level} · 第 ${i + 1} / ${state.book.pageCount} 页`;
  [...$('dots').children].forEach((d, k) => d.classList.toggle('on', k === i));

  const words = pageWords(p);
  $('sentence').innerHTML = words.map((w, k) => `<span class="w" data-k="${k}">${w}</span>`).join(' ');

  const img = $('pageImg');
  // 图片 load 之后布局可能还要一两帧才稳定（首开会差 17px），所以连排两帧
  img.onload = () => requestAnimationFrame(() => {
    layoutOverlay(p);
    requestAnimationFrame(() => layoutOverlay(p));
  });
  // 页图加载失败时 onload 永不触发，overlay 就永远不布局 —— 表现为"点图没反应"。
  // 明确提示，别让它变成无声的坏页。
  img.onerror = () => {
    toast(`第 ${i + 1} 页图片加载失败`);
    console.warn('[GK] 页图加载失败', p.image);
  };
  img.src = `${LIB}${p.image}`;
  if (img.complete && img.naturalWidth) {
    requestAnimationFrame(() => {
      layoutOverlay(p);
      requestAnimationFrame(() => layoutOverlay(p));
    });
  }

  if (autoplay) playSentence();
}

function pageWords(p) {
  return p.wordBoxes ? p.wordBoxes.words : String(p.text || '').split(/\s+/).filter(Boolean);
}

/** 图层：句子框 + 逐词热区（视觉参考），点击由 handleTap 统一做"就近吸附"。
 *
 * 为什么改成吸附：
 *   - 词框宽度受邻居限制，窄词（如 "I"）只有 20–23px，达不到 44pt 的可点尺寸；
 *   - 把高度撑到 44px 又会让相邻两行在纵向重叠（1194 视口 37/544 页，iPad 6 上 112/544 页）；
 *   - 两条要求在矩形模型下互相冲突。改用"点到哪个词中心最近就是哪个词"后，
 *     每个词的有效命中区是它的 Voronoi 单元，既不会重叠，也不再受字宽限制。
 *   - 视觉矩形保留为调试参考（pointer-events: none），不参与命中。
 */
const SNAP_R = 40;             // 吸附半径（CSS px，约 9mm）

function layoutOverlay(p) {
  const img = $('pageImg');
  const stage = $('stage');
  const ov = $('overlay');
  ov.innerHTML = '';
  if (!img.naturalWidth) return;

  const ir = img.getBoundingClientRect();
  const sr = stage.getBoundingClientRect();
  ov.style.cssText = `left:${ir.left - sr.left}px;top:${ir.top - sr.top}px;width:${ir.width}px;height:${ir.height}px;`;
  const w = ir.width;
  const h = ir.height;

  if (p.textBox) {
    const [x0, y0, x1, y1] = p.textBox;
    const box = document.createElement('div');
    box.className = 'sent-box';
    box.style.cssText = `left:${x0 * w}px;top:${y0 * h}px;width:${(x1 - x0) * w}px;height:${(y1 - y0) * h}px;`;
    ov.appendChild(box);
  }

  state.wordCenters = [];
  state.textBox = p.textBox || null;
  state.wordBoxes = p.wordBoxes ? p.wordBoxes.boxes : null;
  if (p.wordBoxes) {
    p.wordBoxes.boxes.forEach((b, k) => {
      state.wordCenters.push({ k, x: (b[0] + b[2]) / 2, y: (b[1] + b[3]) / 2 });
    });
    // 调试描边（不参与命中）
    const heights = p.wordBoxes.boxes.map((b) => b[3] - b[1]).sort((a, b) => a - b);
    const medH = heights[Math.floor(heights.length / 2)] || 0.05;
    const order = p.wordBoxes.boxes.map((_, k) => k)
      .sort((a, bb) => (p.wordBoxes.boxes[a][1] + p.wordBoxes.boxes[a][3]) - (p.wordBoxes.boxes[bb][1] + p.wordBoxes.boxes[bb][3]));
    const lines = [];
    for (const k of order) {
      const bx = p.wordBoxes.boxes[k];
      const cy = (bx[1] + bx[3]) / 2;
      const last = lines[lines.length - 1];
      if (last && Math.abs(last.cy - cy) <= medH * 0.65) {
        last.items.push(k);
        last.cy = (last.cy * (last.items.length - 1) + cy) / last.items.length;
      } else {
        lines.push({ cy, items: [k] });
      }
    }
    for (const line of lines) {
      line.items.sort((a, bb) => p.wordBoxes.boxes[a][0] - p.wordBoxes.boxes[bb][0]);
      line.items.forEach((k, i) => {
        const [x0, y0, x1, y1] = p.wordBoxes.boxes[k];
        const prev = i > 0 ? p.wordBoxes.boxes[line.items[i - 1]] : null;
        const next = i < line.items.length - 1 ? p.wordBoxes.boxes[line.items[i + 1]] : null;
        const L = Math.max(0, prev ? (prev[2] + x0) / 2 : x0 - 0.004);
        const R = Math.min(1, next ? (x1 + next[0]) / 2 : x1 + 0.004);
        const d = document.createElement('div');
        d.className = 'hit word';
        d.dataset.k = k;
        d.style.cssText = `left:${L * w}px;top:${y0 * h}px;width:${Math.max(4, (R - L) * w)}px;height:${(y1 - y0) * h}px;`;
        ov.appendChild(d);
      });
    }
  }

  ov.onclick = handleTap;
}

/** 点到哪个词中心最近就播哪个词；不在吸附半径内则交给句子区，再不行就忽略。
 *  坐标以**图片当前矩形**为准，而不是 overlay 缓存下来的位置——
 *  图片刚加载完时布局可能还没稳定（实测首开会差 17px）。
 */
function handleTap(e) {
  if (!state.book) return;
  const p = state.book.pages[state.page];
  const img = $('pageImg');
  const r = img.getBoundingClientRect();
  const px = e.clientX - r.left;
  const py = e.clientY - r.top;

  const k = nearestWord(px, py, r.width, r.height);
  if (k >= 0) { playWord(k); return; }

  if (p.textBox) {
    const [x0, y0, x1, y1] = p.textBox;
    const m = 12;
    if (px >= x0 * r.width - m && px <= x1 * r.width + m &&
        py >= y0 * r.height - m && py <= y1 * r.height + m) {
      playSentence();
    }
  }
}

function nearestWord(px, py, w, h) {
  // 1) 落在某个词的文字框内 → 一定归这个词（宽词边缘也不会跑掉）
  const boxes = state.wordBoxes;
  if (boxes) {
    let hit = -1;
    let hitD = Infinity;
    for (let k = 0; k < boxes.length; k++) {
      const b = boxes[k];
      if (px >= b[0] * w && px <= b[2] * w && py >= b[1] * h && py <= b[3] * h) {
        const dx = ((b[0] + b[2]) / 2) * w - px;
        const dy = ((b[1] + b[3]) / 2) * h - py;
        const d = dx * dx + dy * dy;
        if (d < hitD) { hitD = d; hit = k; }
      }
    }
    if (hit >= 0) return hit;
  }

  // 2) 在词框之外 → 就近吸附（文字区内放宽半径，消除词间死区）
  let best = -1;
  let bestD = Infinity;
  for (const c of state.wordCenters || []) {
    const dx = c.x * w - px;
    const dy = c.y * h - py;
    const d = Math.sqrt(dx * dx + dy * dy);
    if (d < bestD) { bestD = d; best = c.k; }
  }
  if (best < 0) return -1;
  let limit = SNAP_R;
  const tb = state.textBox;
  if (tb) {
    const m = 16;
    if (px >= tb[0] * w - m && px <= tb[2] * w + m && py >= tb[1] * h - m && py <= tb[3] * h + m) {
      limit = SNAP_R * 1.8;
    }
  }
  return bestD <= limit ? best : -1;
}

/* ───────────────────── 播放 ───────────────────── */
function stopPlayback() {
  cancelAnimationFrame(state.raf);
  state.raf = 0;
  state.stopAt = null;
  audio.pause();
  clearHighlights();
  setPlayIcon(false);
}
function stopAuto() { state.autoRun = false; stopPlayback(); }

function clearHighlights() {
  document.querySelectorAll('.lit').forEach((n) => n.classList.remove('lit'));
  document.querySelectorAll('.sentence .w.on').forEach((n) => n.classList.remove('on'));
}

function setPlayIcon(on) {
  $('playIcon').innerHTML = on
    ? '<rect x="7" y="5" width="4.6" height="14" rx="1.6"/><rect x="13.4" y="5" width="4.6" height="14" rx="1.6"/>'
    : '<path d="M8 5 L19 12 L8 19 Z"/>';
}

/** 播放 [a,b]；结束（或被打断）时回调 done。 */
function playRange(a, b, done) {
  cancelAnimationFrame(state.raf);
  state.stopAt = b;
  audioReady.then(() => {
    if (state.stopAt !== b) return;                  // 期间又被别的点击打断
    const finish = () => {
      if (state.stopAt === null) return;
      audio.pause();
      state.stopAt = null;
      state.raf = 0;
      done && done();
    };
    const start = () => {
      applyRate();
      try { audio.currentTime = a; } catch { /* ignore */ }
      audio.play().catch(() => toast('再点一次试试'));
      state.raf = requestAnimationFrame(tick);
    };
    const tick = () => {
      if (state.stopAt === null) return;
      if (audio.currentTime >= state.stopAt || audio.ended) { finish(); return; }
      state.raf = requestAnimationFrame(tick);
    };
    // rAF 在 iOS 切后台/锁屏时会停摆，只靠它的话 stopAt 永远不触发，
    // 音频会把整本书播完。timeupdate 由媒体管线驱动，后台仍会来。
    audio.addEventListener('timeupdate', onTimeUpdate);
    function onTimeUpdate() {
      if (state.stopAt === null) { audio.removeEventListener('timeupdate', onTimeUpdate); return; }
      if (audio.currentTime >= state.stopAt || audio.ended) {
        audio.removeEventListener('timeupdate', onTimeUpdate);
        finish();
      }
    }
    if (audio.readyState >= 1) start();
    else audio.addEventListener('loadedmetadata', start, { once: true });
  });
}

// 切后台/锁屏时立刻停：既不打扰别人，也避免回来时状态错乱
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stopAuto();
  }
});

function playSentence() {
  if (!state.book) return;
  const p = state.book.pages[state.page];
  if (!p) return;
  cancelAnimationFrame(state.raf);
  state.stopAt = null;
  audio.pause();
  clearHighlights();

  document.querySelectorAll('.sentence .w').forEach((n) => n.classList.add('on'));
  const box = document.querySelector('.sent-box');
  if (box) box.classList.add('lit');

  playRange(p.audio[0], p.audio[1], () => {
    clearHighlights();
    if (!state.autoRun) return;
    const next = state.page + 1;
    if (next >= state.book.pageCount) {
      state.autoRun = false;
      setPlayIcon(false);
      toast('读完啦 🎉');
      return;
    }
    setTimeout(() => { if (state.autoRun) showPage(next, true); }, 480);
  });
}

function playWord(k) {
  if (!state.book) return;
  const p = state.book.pages[state.page];
  const n = pageWords(p).length;
  // 词级时间戳必须与当前页的词一一对应，否则回落到整句
  if (!p.wordTimes || p.wordTimes.length !== n || !p.wordTimes[k]) { playSentence(); return; }

  cancelAnimationFrame(state.raf);
  state.stopAt = null;
  audio.pause();
  clearHighlights();

  const base = p.audio[0];
  const chip = document.querySelector(`.sentence .w[data-k="${k}"]`);
  const hit = document.querySelector(`.hit.word[data-k="${k}"]`);
  if (chip) chip.classList.add('on');
  if (hit) hit.classList.add('lit');

  playRange(base + p.wordTimes[k][0], base + p.wordTimes[k][1], () => {
    if (chip) chip.classList.remove('on');
    if (hit) hit.classList.remove('lit');
  });
}

/* ───────────────────── 事件 ───────────────────── */
$('btnBack').onclick = closeBook;
$('btnPrev').onclick = () => { if (state.book && state.page > 0) showPage(state.page - 1); };
$('btnNext').onclick = () => { if (state.book && state.page < state.book.pageCount - 1) showPage(state.page + 1); };
$('btnReplay').onclick = () => { state.autoRun = false; playSentence(); };
$('sentence').onclick = (e) => {
  const w = e.target.closest('.w');
  if (w) playWord(+w.dataset.k); else playSentence();
};
$('btnRate').onclick = () => {
  const i = RATES.indexOf(state.rate);
  state.rate = RATES[(i + 1) % RATES.length];
  localStorage.setItem('gk-rate', String(state.rate));
  applyRate();
  toast(`语速 ${state.rate}×`);
};

$('btnPlay').onclick = () => {
  if (!state.book) return;
  if (state.autoRun) { stopAuto(); return; }
  state.autoRun = true;
  setPlayIcon(true);
  playSentence();
};

document.addEventListener('keydown', (e) => {
  if (!state.book || $('reader').classList.contains('hidden')) return;
  if (e.key === 'ArrowLeft') $('btnPrev').click();
  else if (e.key === 'ArrowRight') $('btnNext').click();
  else if (e.key === ' ') { e.preventDefault(); $('btnPlay').click(); }
  else if (e.key === 'Escape') closeBook();
});

window.addEventListener('resize', () => {
  if (state.book) layoutOverlay(state.book.pages[state.page]);
});

/* ───────────────────── 路由 ───────────────────── */
function route() {
  // 系列代号可能是 GK/G1/G2 —— 第二位是数字，所以用 [A-Z0-9]{2}
  const m = (location.hash || '').match(/^#\/b\/([A-Z0-9]{2}-\d{3})$/);
  if (!m) return;
  const id = m[1];
  if (!state.manifest.some((b) => b.id === id)) return;
  if (state.book && state.book.id === id) return;
  openBook(id);
}
window.addEventListener('hashchange', route);

/* ───────────────────── 启动 ───────────────────── */
window.__GK = {
  state, audio, showPage, playWord, playSentence, openBook, getLib: () => LIB,
  /** 测试用：把"点击坐标"解析成词序号（-1 表示没吸附到词） */
  snap: (px, py) => {
    const r = $('overlay').getBoundingClientRect();
    return nearestWord(px, py, r.width, r.height);
  },
  snapR: SNAP_R,
};

(async function boot() {
  if (new URLSearchParams(location.search).has('debug')) document.body.classList.add('debug');
  initRate();

  const base = await resolveLib();
  if (!base) {
    $('grid').innerHTML =
      '<p style="color:#968a7e;line-height:1.7">找不到 <code>library/</code>。<br>' +
      '请用 <code>python tools/serve.py</code> 打开本页面，不要直接双击 HTML。</p>';
    return;
  }
  LIB = base;

  try {
    const r = await fetch(`${LIB}manifest.json`);
    const data = await r.json();
  state.manifest = data.books;
  state.series = data.series || [];
  } catch {
    $('grid').innerHTML = '<p style="color:#968a7e">书架数据读取失败。</p>';
    return;
  }
  renderTabs();
  renderGrid();
  window.__GK_READY__ = true;
  route();
})();
