/**
 * 探：打开 GK-001 第 4 页后，页面里的数据到底是什么。
 */
const BASE = process.argv[2] || 'http://127.0.0.1:8787/web/';
const PORT = 9223;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let ws, id = 0;
const pend = new Map();
function send(method, params = {}) {
  const mid = ++id;
  ws.send(JSON.stringify({ id: mid, method, params }));
  return new Promise((res, rej) => {
    pend.set(mid, { res, rej });
    setTimeout(() => { if (pend.has(mid)) { pend.delete(mid); rej(new Error('timeout ' + method)); } }, 15000);
  });
}
async function js(expr) {
  const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.exceptionDetails) return { __err: r.exceptionDetails.exception?.description || r.exceptionDetails.text };
  return r.result?.value;
}
async function until(expr, label, ms = 10000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { const v = await js(expr).catch(() => false); if (v) return true; await sleep(100); }
  throw new Error('timeout ' + label);
}

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
};
await send('Runtime.enable');
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1194, height: 834, deviceScaleFactor: 2, mobile: false });

await send('Page.navigate', { url: `${BASE}?t=${Date.now()}#/b/GK-001` });
await until('!!(window.__GK && window.__GK.state.book)', 'book');
await sleep(700);
console.log('打开后:', await js(`(() => { const s = window.__GK.state; return {id: s.book.id, page: s.page, pages: s.book.pageCount}; })()`));

await js('window.__GK.showPage(3)');
await sleep(600);
console.log('翻到 index 3 后:', await js(`(() => { const s = window.__GK.state, p = s.book.pages[s.page];
  return { page: s.page, audio: p.audio, times: p.wordTimes ? p.wordTimes.length : null,
           words: p.wordBoxes ? p.wordBoxes.words.length : null, text: p.text }; })()`));

console.log('点第 3 个词的落点:', await js(`(() => { const s = window.__GK.state, p = s.book.pages[s.page];
  const r = document.getElementById('pageImg').getBoundingClientRect();
  const b = p.wordBoxes.boxes[2];
  const x = r.left + (b[0]+b[2])/2*r.width, y = r.top + (b[1]+b[3])/2*r.height;
  return { x: Math.round(x), y: Math.round(y), snap: window.__GK.snap(x - r.left, y - r.top) }; })()`));
ws.close();
