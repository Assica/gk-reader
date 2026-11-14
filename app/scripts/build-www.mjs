/**
 * 把 web/ 与 library/ 组装成 Capacitor 的 www/ 目录。
 *
 *   node app/scripts/build-www.mjs
 *
 * 产出（与 index.html 的相对路径探测兼容）：
 *   app/www/index.html · app.js · style.css
 *   app/www/library/...            manifest + 70 本书 + 560 张页图 + 70 段音频
 */
import { cpSync, existsSync, mkdirSync, rmSync, readdirSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';

const ROOT = resolve(import.meta.dirname, '..', '..');   // 仓库根
const SRC_WEB = join(ROOT, 'web');
const SRC_LIB = join(ROOT, 'library');
const OUT = join(ROOT, 'app', 'www');

if (!existsSync(SRC_WEB) || !existsSync(SRC_LIB)) {
  console.error('缺少 web/ 或 library/，先跑 tools/build_library.py');
  process.exit(1);
}

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

for (const f of ['index.html', 'app.js', 'style.css']) {
  cpSync(join(SRC_WEB, f), join(OUT, f));
}
cpSync(SRC_LIB, join(OUT, 'library'), { recursive: true });

function dirSize(dir) {
  let n = 0;
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, e.name);
    n += e.isDirectory() ? dirSize(p) : statSync(p).size;
  }
  return n;
}

const mb = (dirSize(OUT) / 1e6).toFixed(1);
console.log(`www 已生成: ${OUT}  (${mb} MB)`);
