"""本地网页版：浏览器里填主题、拖照片、点一下出图。

只用标准库 http.server，不引入 Flask/Gradio，装好 Pillow 就能跑。
仅监听 127.0.0.1，是给本机运营用的小工具，不要暴露到公网。
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

from . import pipeline
from .character import list_characters, load_character, register_character, stylize_character
from .config import Config
from .providers import make_image_engine, make_text_engine
from .style import list_styles, load_style, save_style, style_from_image
from .util import DigError, ensure_dir, log, slugify, warn

MAX_UPLOAD = 24 * 1024 * 1024   # 24MB


# --------------------------------------------------------------------------- #
# multipart 解析（不用已被移除的 cgi 模块）
# --------------------------------------------------------------------------- #
def parse_multipart(body: bytes, content_type: str) -> Tuple[Dict[str, str], Dict[str, Tuple[str, bytes]]]:
    """返回 (普通字段, 文件字段{name: (filename, bytes)})。"""
    fields: Dict[str, str] = {}
    files: Dict[str, Tuple[str, bytes]] = {}

    marker = "boundary="
    if marker not in content_type:
        return fields, files
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    sep = b"--" + boundary.encode("utf-8")

    for part in body.split(sep):
        if not part or part in (b"--\r\n", b"--", b"\r\n"):
            continue
        part = part.lstrip(b"\r\n")
        if part.startswith(b"--"):
            continue
        head, found, data = part.partition(b"\r\n\r\n")
        if not found:
            continue
        # 只去掉分隔符前的那一个 CRLF，不能用 rstrip：图片二进制结尾可能正好是 0d0a
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers = head.decode("utf-8", "replace")
        name = _header_param(headers, "name")
        if not name:
            continue
        filename = _header_param(headers, "filename")
        if filename:
            files[name] = (filename, data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


def _header_param(headers: str, key: str) -> str:
    token = key + '="'
    idx = headers.find(token)
    if idx < 0:
        return ""
    start = idx + len(token)
    end = headers.find('"', start)
    return headers[start:end] if end > start else ""


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>抖音图文生成器</title>
<style>
  :root { color-scheme: light dark;
    --bg:#f6f3ea; --card:#fffdf7; --ink:#241f1a; --muted:#6d6459;
    --line:#e2d8c4; --accent:#d8a13a; --accent-ink:#2a2119; }
  @media (prefers-color-scheme: dark) { :root {
    --bg:#16130f; --card:#211d18; --ink:#f2ece1; --muted:#a9a093;
    --line:#332c24; --accent:#e0ad4c; --accent-ink:#1a1510; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.6
    system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif; }
  .wrap { max-width:1080px; margin:0 auto; padding:24px 16px 80px; }
  h1 { font-size:22px; margin:8px 0 4px; }
  .sub { color:var(--muted); margin-bottom:22px; font-size:13px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px;
    padding:18px; margin-bottom:16px; }
  .card h2 { font-size:15px; margin:0 0 14px; letter-spacing:.02em; }
  label { display:block; font-size:13px; color:var(--muted); margin:10px 0 4px; }
  input, select, textarea { width:100%; padding:9px 11px; border-radius:9px;
    border:1px solid var(--line); background:var(--bg); color:var(--ink); font:inherit; }
  textarea { min-height:70px; resize:vertical; }
  .row { display:flex; gap:12px; flex-wrap:wrap; }
  .row > div { flex:1 1 180px; }
  button { background:var(--accent); color:var(--accent-ink); border:0; border-radius:10px;
    padding:11px 20px; font:600 15px/1 inherit; cursor:pointer; margin-top:16px; }
  button.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
  button:disabled { opacity:.5; cursor:wait; }
  .hint { font-size:12px; color:var(--muted); margin-top:6px; }
  .check { display:flex; align-items:center; gap:8px; margin-top:14px; font-size:13px; }
  .check input { width:auto; }
  #log { white-space:pre-wrap; font:12px/1.55 ui-monospace,Consolas,monospace;
    color:var(--muted); margin-top:12px; max-height:220px; overflow:auto; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
  .grid img { width:100%; border-radius:8px; border:1px solid var(--line); display:block; }
  pre.caption { white-space:pre-wrap; background:var(--bg); border:1px solid var(--line);
    border-radius:10px; padding:14px; font:13px/1.7 inherit; max-height:340px; overflow:auto; }
  .err { color:#c2410c; }
</style>
</head>
<body>
<div class="wrap">
  <h1>抖音图文轮播生成器</h1>
  <div class="sub">一个主题 → 5~7 张双格科普图 → 直接发布</div>

  <div class="card">
    <h2>① 主角（个人 IP，可选）</h2>
    <div class="row">
      <div><label>角色名</label><input id="cname" placeholder="小圆"></div>
      <div><label>照片</label><input id="cphoto" type="file" accept="image/*"></div>
    </div>
    <div class="check"><input type="checkbox" id="cstylize" checked>
      <span>同时生成风格化定妆图（强烈建议，跨图一致性靠它）</span></div>
    <button class="ghost" id="btnChar">登记主角</button>
    <div class="hint">登记后会出现在下面的「主角」下拉框里。照片只存在本机 characters/ 目录。</div>
  </div>

  <div class="card">
    <h2>② 画风</h2>
    <div class="row">
      <div><label>预设</label><select id="style"></select></div>
      <div><label>参考图反推新画风（可选）</label><input id="sphoto" type="file" accept="image/*"></div>
      <div><label>新画风名字</label><input id="sname" placeholder="复古港漫"></div>
    </div>
    <button class="ghost" id="btnStyle">从参考图生成画风</button>
    <label>临时画风描述（填了就覆盖预设）</label>
    <textarea id="styleprompt" placeholder="留空即用预设。例：90年代港漫风，粗线条，高对比，暖黄色调"></textarea>
  </div>

  <div class="card">
    <h2>③ 出图</h2>
    <label>主题（一句话）</label>
    <input id="theme" placeholder="例：楼盘名字里的暗号">
    <div class="row">
      <div><label>主角</label><select id="character"></select></div>
      <div><label>张数</label><input id="pages" type="number" value="6" min="3" max="10"></div>
      <div><label>每张格数</label><input id="panels" type="number" value="2" min="1" max="3"></div>
      <div><label>抖音号</label><input id="handle" placeholder="your_douyin_id"></div>
    </div>
    <div class="row">
      <div><label>目标观众（可选）</label><input id="audience" placeholder="刚毕业的年轻人"></div>
      <div><label>切入角度（可选）</label><input id="angle" placeholder="从新手视角"></div>
    </div>
    <div class="check"><input type="checkbox" id="offline">
      <span>离线试跑（mock 引擎，不联网不花钱，只验证排版）</span></div>
    <button id="btnRun">一键生成</button>
    <div id="log"></div>
  </div>

  <div class="card" id="resultCard" style="display:none">
    <h2>④ 成图</h2>
    <div class="grid" id="grid"></div>
    <h2 style="margin-top:20px">发布文案</h2>
    <pre class="caption" id="caption"></pre>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);
function say(msg, cls) {
  const el = $("log");
  el.innerHTML += (cls ? '<span class="' + cls + '">' + msg + '</span>' : msg) + "\\n";
  el.scrollTop = el.scrollHeight;
}
async function refresh() {
  const r = await fetch("/api/state");
  const s = await r.json();
  $("style").innerHTML = s.styles.map(x =>
    '<option value="' + x.id + '"' + (x.id === s.current_style ? " selected" : "") + '>'
    + x.name + " (" + x.id + ")</option>").join("");
  $("character").innerHTML = '<option value="">（不用主角）</option>' +
    s.characters.map(x => '<option value="' + x.id + '">' + x.name + "</option>").join("");
  if (s.handle && !$("handle").value) $("handle").value = s.handle;
}
$("btnChar").onclick = async () => {
  const name = $("cname").value.trim();
  const file = $("cphoto").files[0];
  if (!name || !file) { say("请填角色名并选一张照片", "err"); return; }
  const fd = new FormData();
  fd.append("name", name); fd.append("photo", file);
  fd.append("stylize", $("cstylize").checked ? "1" : "");
  fd.append("style", $("style").value);
  fd.append("offline", $("offline").checked ? "1" : "");
  $("btnChar").disabled = true; say("正在登记主角…");
  try {
    const r = await fetch("/api/character", { method: "POST", body: fd });
    const d = await r.json();
    if (d.error) say("✗ " + d.error, "err");
    else { say("✓ 主角已登记：" + d.id + " — " + (d.sheet || "")); await refresh(); $("character").value = d.id; }
  } catch (e) { say("✗ " + e, "err"); }
  $("btnChar").disabled = false;
};
$("btnStyle").onclick = async () => {
  const file = $("sphoto").files[0];
  if (!file) { say("请先选一张参考图", "err"); return; }
  const fd = new FormData();
  fd.append("image", file); fd.append("name", $("sname").value.trim());
  fd.append("offline", $("offline").checked ? "1" : "");
  $("btnStyle").disabled = true; say("正在分析参考图画风…");
  try {
    const r = await fetch("/api/style", { method: "POST", body: fd });
    const d = await r.json();
    if (d.error) say("✗ " + d.error, "err");
    else { say("✓ 新画风：" + d.id + " — " + (d.prompt || "").slice(0, 80)); await refresh(); $("style").value = d.id; }
  } catch (e) { say("✗ " + e, "err"); }
  $("btnStyle").disabled = false;
};
$("btnRun").onclick = async () => {
  const theme = $("theme").value.trim();
  if (!theme) { say("请先填主题", "err"); return; }
  $("btnRun").disabled = true;
  say("开始：" + theme + "（生图较慢，请等 1~3 分钟，别关页面）");
  try {
    const r = await fetch("/api/generate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        theme, style: $("style").value, style_prompt: $("styleprompt").value.trim(),
        character: $("character").value, pages: +$("pages").value, panels: +$("panels").value,
        handle: $("handle").value.trim(), audience: $("audience").value.trim(),
        angle: $("angle").value.trim(), offline: $("offline").checked,
      }),
    });
    const d = await r.json();
    if (d.error) { say("✗ " + d.error, "err"); }
    else {
      say("✓ 完成，用时 " + d.seconds + "s，输出在 " + d.out_dir);
      $("resultCard").style.display = "block";
      $("grid").innerHTML = d.files.map(f =>
        '<a href="' + f + '" target="_blank"><img src="' + f + '"></a>').join("");
      $("caption").textContent = d.caption_text || "";
    }
  } catch (e) { say("✗ " + e, "err"); }
  $("btnRun").disabled = false;
};
refresh();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# 服务
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    cfg: Config = None            # type: ignore[assignment]
    server_version = "dig-ui/0.3"

    # 日志安静一点
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    # -- 工具 ----------------------------------------------------------- #
    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise DigError("上传内容太大（上限 %d MB）" % (MAX_UPLOAD // 1024 // 1024))
        return self.rfile.read(length) if length else b""

    def _cfg_for(self, offline: bool) -> Config:
        import copy

        from .config import Config as _C

        cfg = _C(data=copy.deepcopy(self.cfg.data), path=self.cfg.path, root=self.cfg.root)
        if offline:
            cfg.use_mock()
        return cfg

    # -- 路由 ----------------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route in ("/", "/index.html"):
            self._html(PAGE)
            return
        if route == "/api/state":
            self._json(self._state())
            return
        if route.startswith("/files/"):
            self._serve_file(urllib.parse.unquote(route[len("/files/") :]))
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        route = urllib.parse.urlparse(self.path).path
        try:
            if route == "/api/generate":
                self._json(self._generate(json.loads(self._read_body() or b"{}")))
                return
            if route == "/api/character":
                self._json(self._character())
                return
            if route == "/api/style":
                self._json(self._style())
                return
        except DigError as exc:
            self._json({"error": str(exc)}, 200)
            return
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": "%s: %s" % (type(exc).__name__, exc)}, 200)
            return
        self.send_error(404)

    # -- 业务 ----------------------------------------------------------- #
    def _state(self) -> Dict[str, Any]:
        cfg = self.cfg
        styles = []
        for sid in list_styles(cfg):
            try:
                preset = load_style(cfg, sid)
                styles.append({"id": preset.id, "name": preset.name})
            except Exception:  # noqa: BLE001
                styles.append({"id": sid, "name": sid})
        chars = []
        for cid in list_characters(cfg):
            try:
                c = load_character(cfg, cid)
                if c:
                    chars.append({"id": c.id, "name": c.name or c.id})
            except Exception:  # noqa: BLE001
                chars.append({"id": cid, "name": cid})
        return {
            "styles": styles,
            "characters": chars,
            "current_style": str(cfg.get("style", "")),
            "handle": str(cfg.get("handle", "") or ""),
        }

    def _generate(self, body: Dict[str, Any]) -> Dict[str, Any]:
        theme = str(body.get("theme") or "").strip()
        if not theme:
            raise DigError("主题不能为空")
        cfg = self._cfg_for(bool(body.get("offline")))
        result = pipeline.run(
            cfg,
            theme=theme,
            style_id=str(body.get("style") or ""),
            style_prompt=str(body.get("style_prompt") or ""),
            character_id=str(body.get("character") or ""),
            pages=int(body.get("pages") or 0) or None,
            panels=int(body.get("panels") or 0) or None,
            handle=str(body.get("handle") or ""),
            angle=str(body.get("angle") or ""),
            audience=str(body.get("audience") or ""),
        )
        caption_text = ""
        try:
            with open(result["caption"], "r", encoding="utf-8") as fh:
                caption_text = fh.read()
        except Exception:  # noqa: BLE001
            pass
        return {
            "out_dir": result["out_dir"],
            "files": [self._file_url(f) for f in result["files"]],
            "caption_text": caption_text,
            "seconds": (result.get("stats") or {}).get("seconds", 0),
        }

    def _character(self) -> Dict[str, Any]:
        fields, files = parse_multipart(self._read_body(), self.headers.get("Content-Type", ""))
        name = (fields.get("name") or "").strip()
        if not name:
            raise DigError("角色名不能为空")
        if "photo" not in files:
            raise DigError("没有收到照片")
        cfg = self._cfg_for(bool(fields.get("offline")))

        filename, data = files["photo"]
        tmp_dir = ensure_dir(os.path.join(cfg.characters_dir, "_upload"))
        tmp = os.path.join(tmp_dir, slugify(name) + os.path.splitext(filename)[1].lower())
        with open(tmp, "wb") as fh:
            fh.write(data)

        vision = make_text_engine(cfg.provider("vision"), cfg.root)
        char = register_character(cfg, vision, name=name, photo=tmp)
        if fields.get("stylize"):
            preset = load_style(cfg, fields.get("style") or str(cfg.get("style")))
            engine = make_image_engine(cfg.provider("image"), cfg.root)
            try:
                stylize_character(cfg, engine, char, preset)
            except Exception as exc:  # noqa: BLE001
                warn("定妆图生成失败（不影响后续）：%s" % exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return {"id": char.id, "name": char.name, "sheet": char.sheet}

    def _style(self) -> Dict[str, Any]:
        fields, files = parse_multipart(self._read_body(), self.headers.get("Content-Type", ""))
        if "image" not in files:
            raise DigError("没有收到参考图")
        cfg = self._cfg_for(bool(fields.get("offline")))
        name = (fields.get("name") or "参考风格").strip()

        filename, data = files["image"]
        tmp_dir = ensure_dir(os.path.join(cfg.styles_dir, "_ref"))
        tmp = os.path.join(tmp_dir, slugify(name) + (os.path.splitext(filename)[1].lower() or ".jpg"))
        with open(tmp, "wb") as fh:
            fh.write(data)

        vision = make_text_engine(cfg.provider("vision"), cfg.root)
        preset = style_from_image(cfg, vision, tmp, name=name)
        save_style(cfg, preset)
        return {"id": preset.id, "name": preset.name, "prompt": preset.prompt}

    # -- 静态文件 -------------------------------------------------------- #
    def _file_url(self, path: str) -> str:
        rel = os.path.relpath(os.path.abspath(path), self.cfg.output_dir)
        return "/files/" + urllib.parse.quote(rel.replace(os.sep, "/"))

    def _serve_file(self, rel: str) -> None:
        base = os.path.abspath(self.cfg.output_dir)
        target = os.path.abspath(os.path.join(base, rel))
        # 只允许读 output/ 里的东西
        if not target.startswith(base + os.sep) or not os.path.isfile(target):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        with open(target, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    ensure_dir(cfg.output_dir)
    Handler.cfg = cfg
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)
    log("网页版已启动：" + url)
    log("（只监听本机；Ctrl+C 退出）")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\n已停止")
    finally:
        httpd.server_close()
