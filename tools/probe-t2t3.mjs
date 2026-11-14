/**
 * 复刻 T1→T2→T3：真实指针点书架卡片开书，再点返回，看是否回到书架。
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
  while (Date.now() - t0 < ms) { if (await js(expr).catch(() => false)) return true; await sleep(100); }
  throw new Error('timeout ' + label);
}
async function clickAt(x, y) {
  await send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y, button: 'none' });
  await send('Input.dispatchMouseEvent', { type: 'mousePressed', x, y, button: 'left', clickCount: 1 });
  await send('Input.dispatchMouseEvent', { type: 'mouseReleased', x, y, button: 'left', clickCount: 1 });
}

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pend.has(m.id)) { const { res, rej } = pend.get(m.id); pend.delete(m.id); m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result); }
  else if (m.method === 'Runtime.exceptionThrown') errs.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text);
};
await send('Runtime.enable');
await send('Page.enable');
await send('Emulation.setDeviceMetricsOverride', { width: 1194, height: 834, deviceScaleFactor: 2, mobile: false });

// T1
await send('Page.navigate', { url: BASE });
await until('window.__GK_READY__ === true', 'ready');
await js('localStorage.clear()');
await sleep(300);
console.log('打开前 hash =', JSON.stringify(await js('location.hash')), '| cards =', await js('document.querySelectorAll("#grid .card").length'));

// T2
const r = await js(`(() => { const c = document.querySelectorAll('#grid .card')[0];
  const b = c.getBoundingClientRect(); return {x: b.left + b.width/2, y: b.top + b.height/2}; })()`);
await clickAt(r.x, r.y);
await until('!!window.__GK.state.book', 'book opened');
console.log('T2 后 book =', await js('window.__GK.state.book && window.__GK.state.book.id'),
            '| hash =', JSON.stringify(await js('location.hash')));
await sleep(400);

// T3
await js('document.getElementById("btnBack").click()');
await sleep(400);
console.log('T3 后 book =', await js('window.__GK.state.book === null ? "null" : (window.__GK.state.book && window.__GK.state.book.id)'));
console.log('  shelf hidden =', await js('document.getElementById("shelf").classList.contains("hidden")'));
console.log('  reader hidden =', await js('document.getElementById("reader").classList.contains("hidden")'));
console.log('  hash =', JSON.stringify(await js('location.hash')));
console.log('页面异常:', errs.length ? errs : '无');
ws.close();
