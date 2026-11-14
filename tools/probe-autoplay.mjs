/** 探：GK-001 连播为什么翻不到第 2 页。 */
const BASE = 'http://127.0.0.1:8787/web/';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const list = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const ws = new WebSocket(list.find((t) => t.type === 'page').webSocketDebuggerUrl);
await new Promise((r) => { ws.onopen = r; });
let id = 0; const pend = new Map();
ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.id && pend.has(m.id)) { pend.get(m.id)(m.result); pend.delete(m.id); } };
const send = (m, p = {}) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method: m, params: p })); });
const js = async (ex) => { const r = await send('Runtime.evaluate', { expression: ex, awaitPromise: true, returnByValue: true }); return r.result && r.result.value; };
await send('Runtime.enable'); await send('Page.enable');

const doc = await (await fetch(`${BASE.replace('/web/', '')}/library/books/GK/001.json?t=${Date.now()}`)).json();
console.log('页区间:', doc.pages.map((p) => `${p.n}:${p.audio ? p.audio.map((x) => x.toFixed(2)).join('-') : 'null'}`).join('  '));

await send('Page.navigate', { url: `${BASE}?t=${Date.now()}#/b/GK-001` });
await sleep(2500);
console.log('打开后:', await js(`(() => { const s = window.__GK.state; return { page: s.page, auto: s.autoRun,
  clip: s.book.pages[s.page].audio, dur: window.__GK.audio.duration, ready: window.__GK.audio.readyState }; })()`));

await js(`document.getElementById('btnPlay').click()`);
for (let i = 0; i < 8; i += 1) {
  await sleep(700);
  console.log(i, await js(`(() => { const s = window.__GK.state, a = window.__GK.audio;
    return { page: s.page, auto: s.autoRun, t: +a.currentTime.toFixed(2), paused: a.paused, stopAt: s.stopAt, ended: a.ended }; })()`));
}
ws.close();
