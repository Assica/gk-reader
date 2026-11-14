/**
 * 定位 closeBook / 播放失效：在真实页面里点返回，抓异常与状态。
 * 用法: node tools/probe-back.mjs [baseUrl]
 */
const BASE = process.argv[2] || 'http://127.0.0.1:8787/web/';
const PORT = 9223;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let ws, id = 0;
const pend = new Map();
const errs = [];

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
async function until(expr, label, ms = 8000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const v = await js(expr).catch(() => false);
    if (v) return true;
    await sleep(100);
  }
  throw new Error('timeout ' + label);
}

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) {
    const { res, rej } = pend.get(m.id);
    pend.delete(m.id);
    m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
  } else if (m.method === 'Runtime.exceptionThrown') {
    errs.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text);
  }
};
await send('Runtime.enable');
await send('Page.enable');

await send('Page.navigate', { url: `${BASE}?p=${Date.now()}#/b/1` });
await until('!!(window.__GK && window.__GK.state.book)', 'book');
await sleep(600);

console.log('btnBack.onclick 类型:', await js('typeof document.getElementById("btnBack").onclick'));
console.log('打开后 book:', await js('window.__GK.state.book && window.__GK.state.book.id'));
console.log('audio.src 前缀:', await js('(window.__GK.audio.currentSrc || "").slice(0, 12)'));

const r = await js(`(() => {
  try {
    document.getElementById('btnBack').click();
    return { threw: null };
  } catch (e) { return { threw: String(e && e.stack || e) }; }
})()`);
console.log('点击返回:', JSON.stringify(r));
await sleep(400);
console.log('点击后 book:', await js('window.__GK.state.book === null ? "null" : (window.__GK.state.book && window.__GK.state.book.id)'));
console.log('shelf 隐藏:', await js('document.getElementById("shelf").classList.contains("hidden")'));
console.log('reader 隐藏:', await js('document.getElementById("reader").classList.contains("hidden")'));
console.log('hash:', await js('location.hash'));
console.log('页面异常:', errs.length ? errs : '无');
ws.close();
