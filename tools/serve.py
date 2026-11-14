# -*- coding: utf-8 -*-
"""静态文件服务器，支持 HTTP Range —— 没有它，浏览器无法 seek 音频。

Python 自带的 `http.server` 不支持 Range：请求 m4a 会返回 200 整个文件，
浏览器于是丢弃所有 currentTime 定位，只能从头播。点读/翻页全靠 seek，
所以本地调试必须用这个。

    python tools/serve.py --port 8787 --dir "E:\\apple app"
"""
import argparse
import html
import os
import re
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    server_version = "GKReader/1.0"

    def __init__(self, *a, **kw):
        self._limit = None
        super().__init__(*a, **kw)

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def list_directory(self, path):
        # 目录列表里给出可点击的入口，省得手敲 URL
        try:
            names = sorted(os.listdir(path))
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None
        rows = []
        for n in names:
            if n.startswith("."):
                continue
            full = os.path.join(path, n)
            label = html.escape(n) + ("/" if os.path.isdir(full) else "")
            rows.append(f'<li><a href="{urllib.parse.quote(n)}">{label}</a></li>')
        body = f"""<!doctype html><meta charset="utf-8">
<title>{html.escape(os.path.basename(path) or "/")}</title>
<style>body{{font:16px/1.7 system-ui,"Microsoft YaHei";padding:24px 32px}}
a{{color:#e87656}}li{{margin:2px 0}}</style>
<h2>{html.escape(os.path.basename(path) or "/")}</h2><ul>{''.join(rows)}</ul>"""
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        import io
        return io.BytesIO(data)

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith("/"):
                self.send_response(301)
                self.send_header("Location", parts.path + "/" + ("?" + parts.query if parts.query else ""))
                self.end_headers()
                return None
            for index in ("index.html", "index.htm"):
                candidate = os.path.join(path, index)
                if os.path.exists(candidate):
                    path = candidate
                    break
            else:
                return self.list_directory(path)

        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return None

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        size = os.fstat(f.fileno()).st_size
        ctype = self.guess_type(path)
        rng = self.headers.get("Range")

        if rng:
            m = RANGE_RE.match(rng.strip())
            if not m:
                f.close()
                self.send_error(400, "Bad Range header")
                return None
            g1, g2 = m.group(1), m.group(2)
            if g1 == "" and g2 == "":                       # bytes=-
                f.close()
                self.send_error(400, "Bad Range header")
                return None
            if g1 == "":                                    # bytes=-N  (last N bytes)
                length = min(int(g2), size)
                start, end = size - length, size - 1
            else:
                start = int(g1)
                end = int(g2) if g2 else size - 1
            end = min(end, size - 1)
            if start >= size or start > end:
                f.close()
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return None

            self._limit = end - start + 1
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(self._limit))
            self.end_headers()
            f.seek(start)
            return f

        self._limit = None
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        if self._limit is None:
            return super().copyfile(source, outputfile)
        remaining = self._limit
        while remaining > 0:
            chunk = source.read(min(256 * 1024, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--dir", default=os.getcwd())
    args = ap.parse_args()
    os.chdir(args.dir)
    srv = ThreadingHTTPServer((args.bind, args.port), RangeHandler)
    print(f"serving {os.getcwd()} on http://{args.bind}:{args.port}/  (Range: on)", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
