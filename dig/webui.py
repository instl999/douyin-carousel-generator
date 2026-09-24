"""本地网页版：写脚本 → 表格里改文案（实时体检）→ 出图（看得见进度）→ 单格重画。

只用标准库 http.server，不引入 Flask/Gradio，装好 Pillow 就能跑。
仅供本机使用：

- 只接受 Host 为 127.0.0.1 / localhost 的请求（挡 DNS rebinding）；
- 所有 /api/ 请求必须带页面里下发的一次性令牌（X-Dig-Token 请求头）。
  以前任何网页都能对 http://127.0.0.1:8765/api/generate 发一个跨站 POST，
  用你的 Key 跑一整套计费生图 —— 浏览器对 text/plain 的跨站 POST 不做预检。
  自定义请求头会触发预检，而这里不回 CORS 头，跨站请求就发不出来。
"""
from __future__ import annotations

import hmac
import io
import json
import mimetypes
import os
import secrets
import threading
import time
import traceback
import urllib.parse
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from . import pipeline, script_gen, validate
from .character import list_characters, load_character, register_character, stylize_character
from .config import Config
from .models import Deck
from .providers import make_image_engine, make_text_engine
from .style import list_styles, load_style, save_style, style_from_image
from .util import DigError, ensure_dir, load_json, log, redact, slugify, warn

MAX_UPLOAD = 24 * 1024 * 1024   # 24MB
MAX_LOG = 400


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
# 后台任务：生图要几分钟，不能让一个 HTTP 请求干等
# --------------------------------------------------------------------------- #
class Jobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self.busy: Optional[str] = None

    def start(self, kind: str, fn) -> str:
        with self._lock:
            if self.busy and self._jobs.get(self.busy, {}).get("status") == "running":
                raise DigError("已经有一个任务在跑（%s），等它结束再开新的" % self._jobs[self.busy]["kind"])
            job_id = uuid.uuid4().hex[:12]
            job = {"id": job_id, "kind": kind, "status": "running", "log": [], "panels": {},
                   "result": None, "error": None, "started": time.time()}
            self._jobs[job_id] = job
            self.busy = job_id

        def runner() -> None:
            try:
                job["result"] = fn(job)
                job["status"] = "done"
            except DigError as exc:
                job["error"] = redact(exc)
                job["status"] = "error"
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                job["error"] = redact("%s: %s" % (type(exc).__name__, exc))
                job["status"] = "error"

        threading.Thread(target=runner, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._jobs.get(job_id)

    @staticmethod
    def say(job: Dict[str, Any], msg: str) -> None:
        for line in str(msg).splitlines():
            job["log"].append(redact(line))
        del job["log"][:-MAX_LOG]


JOBS = Jobs()


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="dig-token" content="__TOKEN__">
<title>抖音图文生成器</title>
<style>
  :root { color-scheme: light dark;
    --bg:#f6f3ea; --card:#fffdf7; --ink:#241f1a; --muted:#6d6459;
    --line:#e2d8c4; --accent:#d8a13a; --accent-ink:#2a2119; --bad:#c2410c; --warn:#a16207; --ok:#3f7d4e; }
  @media (prefers-color-scheme: dark) { :root {
    --bg:#16130f; --card:#211d18; --ink:#f2ece1; --muted:#a9a093;
    --line:#332c24; --accent:#e0ad4c; --accent-ink:#1a1510; --bad:#f97316; --warn:#eab308; --ok:#6fbf82; } }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.6
    system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:1120px; margin:0 auto; padding:24px 16px 80px; }
  h1 { font-size:22px; margin:8px 0 4px; }
  .sub { color:var(--muted); margin-bottom:22px; font-size:13px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:16px; }
  .card h2 { font-size:15px; margin:0 0 14px; letter-spacing:.02em; }
  label { display:block; font-size:13px; color:var(--muted); margin:10px 0 4px; }
  input, select, textarea { width:100%; padding:9px 11px; border-radius:9px;
    border:1px solid var(--line); background:var(--bg); color:var(--ink); font:inherit; }
  textarea { min-height:64px; resize:vertical; }
  .row { display:flex; gap:12px; flex-wrap:wrap; }
  .row > div { flex:1 1 180px; }
  button { background:var(--accent); color:var(--accent-ink); border:0; border-radius:10px;
    padding:10px 18px; font:600 15px/1 inherit; cursor:pointer; margin-top:14px; margin-right:8px; }
  button.ghost { background:transparent; color:var(--ink); border:1px solid var(--line); }
  button.small { padding:6px 10px; font-size:13px; margin-top:6px; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  .hint { font-size:12px; color:var(--muted); margin-top:6px; }
  .check { display:flex; align-items:center; gap:8px; margin-top:12px; font-size:13px; }
  .check input { width:auto; }
  .log { white-space:pre-wrap; font:12px/1.55 ui-monospace,Consolas,monospace; color:var(--muted);
    margin-top:12px; max-height:220px; overflow:auto; }
  table.beats { width:100%; border-collapse:collapse; margin-top:8px; }
  table.beats td { border-top:1px solid var(--line); padding:8px 6px; vertical-align:top; }
  table.beats td.where { width:92px; color:var(--muted); font-size:13px; white-space:nowrap; }
  table.beats td.cap { width:30%; }
  .count { font-size:12px; color:var(--muted); }
  .count.long { color:var(--warn); } .count.bad { color:var(--bad); }
  ul.issues { margin:8px 0 0; padding-left:0; list-style:none; font-size:13px; }
  ul.issues li { padding:6px 10px; border-radius:8px; margin-bottom:6px; background:var(--bg); }
  ul.issues li.error { border-left:4px solid var(--bad); }
  ul.issues li.warn { border-left:4px solid var(--warn); }
  ul.issues .fix { color:var(--muted); display:block; }
  .budget { font-size:13px; margin-top:10px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:12px; margin-top:10px; }
  .tile { border:1px solid var(--line); border-radius:10px; overflow:hidden; background:var(--bg); }
  .tile img { width:100%; display:block; }
  .tile .meta { padding:6px 8px; font-size:12px; }
  .tile .st-ok { color:var(--ok); } .tile .st-warn { color:var(--warn); } .tile .st-failed { color:var(--bad); }
  .pages { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }
  .pages img, .preview img { width:100%; border-radius:8px; border:1px solid var(--line); display:block; }
  pre.caption { white-space:pre-wrap; background:var(--bg); border:1px solid var(--line);
    border-radius:10px; padding:14px; font:13px/1.7 inherit; max-height:340px; overflow:auto; }
  .err { color:var(--bad); } .hidden { display:none; }
</style>
</head>
<body>
<div class="wrap">
  <h1>抖音图文轮播生成器</h1>
  <div class="sub">写脚本 → 改文案（实时体检）→ 出图 → 不满意的格单独重画。生图按格计费，先改好文案再出图。</div>

  <div class="card">
    <h2>① 主角（个人 IP，可选）</h2>
    <div class="row">
      <div><label>角色名</label><input id="cname" placeholder="小圆"></div>
      <div><label>照片</label><input id="cphoto" type="file" accept="image/*"></div>
    </div>
    <div class="check"><input type="checkbox" id="cstylize">
      <span>现在就生成这个画风的定妆图（不勾也行：出图时会自动画，每个画风一张并缓存）</span></div>
    <button class="ghost" id="btnChar">登记主角</button>
    <div class="hint">照片只存在本机 characters/ 目录，生图时才会发给你配置的模型服务商。</div>
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
    <h2>③ 写脚本</h2>
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
      <span>离线试跑（mock 引擎，不联网不花钱，只验证流程和排版）</span></div>
    <button id="btnScript">生成脚本</button>
    <button class="ghost" id="btnExample">载入示例脚本</button>
    <div class="log" id="scriptLog"></div>
  </div>

  <div class="card hidden" id="editCard">
    <h2>④ 改文案 · 体检</h2>
    <div class="row">
      <div><label>作品标题</label><input id="dTitle"></div>
      <div><label>话题（空格分隔）</label><input id="dTags"></div>
    </div>
    <label>发布文案</label><textarea id="dCaption"></textarea>
    <table class="beats"><tbody id="beatRows"></tbody></table>
    <ul class="issues" id="issues"></ul>
    <div class="budget" id="budget"></div>
    <button id="btnRender" disabled>出图</button>
    <span class="hint" id="renderHint"></span>
  </div>

  <div class="card hidden" id="progressCard">
    <h2>⑤ 出图进度</h2>
    <div class="grid" id="panelGrid"></div>
    <div class="log" id="renderLog"></div>
  </div>

  <div class="card hidden" id="resultCard">
    <h2>⑥ 成图</h2>
    <div class="pages" id="pageGrid"></div>
    <h2 style="margin-top:20px">发布前看这一张：整套 + 手机里的样子</h2>
    <div class="preview" id="previewBox"></div>
    <h2 style="margin-top:20px">单格重画（1 格 = 1 次计费）</h2>
    <div class="grid" id="rerollGrid"></div>
    <h2 style="margin-top:20px">发布文案</h2>
    <pre class="caption" id="captionText"></pre>
  </div>
</div>

<script>
"use strict";
const $ = (id) => document.getElementById(id);
const TOKEN = document.querySelector('meta[name="dig-token"]').content;
const state = { deck: null, outDir: "", issues: [], polling: null };

// ---- DOM helpers: never innerHTML with server / model strings -------------
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) n.append(kid);
  return n;
}
function say(box, msg, bad) {
  const line = el("div", { class: bad ? "err" : "", text: msg });
  $(box).append(line);
  $(box).scrollTop = $(box).scrollHeight;
}
async function api(path, body, form) {
  const opt = { method: body || form ? "POST" : "GET", headers: { "X-Dig-Token": TOKEN } };
  if (form) opt.body = form;
  else if (body) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  const r = await fetch(path, opt);
  const d = await r.json();
  if (d.error) throw new Error(d.error);
  return d;
}
function options() {
  return { style: $("style").value, style_prompt: $("styleprompt").value.trim(),
           character: $("character").value, handle: $("handle").value.trim(),
           offline: $("offline").checked };
}

async function refresh() {
  const s = await api("/api/state");
  $("style").replaceChildren(...s.styles.map(x => {
    const o = el("option", { value: x.id, text: x.name + " (" + x.id + ")" });
    if (x.id === s.current_style) o.selected = true;
    return o;
  }));
  $("character").replaceChildren(el("option", { value: "", text: "（不用主角）" }),
    ...s.characters.map(x => el("option", { value: x.id, text: x.name })));
  if (s.handle && !$("handle").value) $("handle").value = s.handle;
}

// ---- ① 主角 / ② 画风 ------------------------------------------------------
$("btnChar").onclick = async () => {
  const name = $("cname").value.trim(), file = $("cphoto").files[0];
  if (!name || !file) { say("scriptLog", "请填角色名并选一张照片", true); return; }
  const fd = new FormData();
  fd.append("name", name); fd.append("photo", file);
  fd.append("stylize", $("cstylize").checked ? "1" : ""); fd.append("style", $("style").value);
  fd.append("offline", $("offline").checked ? "1" : "");
  $("btnChar").disabled = true; say("scriptLog", "正在登记主角…");
  try { const d = await api("/api/character", null, fd);
        say("scriptLog", "✓ 主角已登记：" + d.id + " — " + (d.sheet || ""));
        await refresh(); $("character").value = d.id; }
  catch (e) { say("scriptLog", "✗ " + e.message, true); }
  $("btnChar").disabled = false;
};
$("btnStyle").onclick = async () => {
  const file = $("sphoto").files[0];
  if (!file) { say("scriptLog", "请先选一张参考图", true); return; }
  const fd = new FormData();
  fd.append("image", file); fd.append("name", $("sname").value.trim());
  fd.append("offline", $("offline").checked ? "1" : "");
  $("btnStyle").disabled = true; say("scriptLog", "正在分析参考图画风…");
  try { const d = await api("/api/style", null, fd);
        say("scriptLog", "✓ 新画风：" + d.id + " — " + (d.prompt || "").slice(0, 80));
        await refresh(); $("style").value = d.id; }
  catch (e) { say("scriptLog", "✗ " + e.message, true); }
  $("btnStyle").disabled = false;
};

// ---- ③ 写脚本 ---------------------------------------------------------------
$("btnScript").onclick = async () => {
  const theme = $("theme").value.trim();
  if (!theme) { say("scriptLog", "请先填主题", true); return; }
  $("btnScript").disabled = true;
  try {
    const d = await api("/api/script", Object.assign(options(), {
      theme, pages: +$("pages").value, panels: +$("panels").value,
      audience: $("audience").value.trim(), angle: $("angle").value.trim() }));
    await follow(d.job, "scriptLog", (res) => loadDeck(res.deck));
  } catch (e) { say("scriptLog", "✗ " + e.message, true); }
  $("btnScript").disabled = false;
};
$("btnExample").onclick = async () => {
  try { const d = await api("/api/example"); loadDeck(d.deck); say("scriptLog", "已载入示例脚本，可以直接改"); }
  catch (e) { say("scriptLog", "✗ " + e.message, true); }
};

// ---- ④ 改文案 · 体检 ----------------------------------------------------------
function charWidth(s) {
  let n = 0;
  for (const ch of s) n += (ch.codePointAt(0) >= 0x2E80 || (ch.codePointAt(0) >= 0x2010 && ch.codePointAt(0) <= 0x206F)) ? 1 : 0.5;
  return n;
}
function loadDeck(deck) {
  state.deck = deck;
  $("dTitle").value = deck.title || "";
  $("dCaption").value = deck.caption || "";
  $("dTags").value = (deck.hashtags || []).join(" ");
  if (deck.handle && !$("handle").value) $("handle").value = deck.handle;
  const rows = [];
  (deck.pages || []).forEach((page, p) => (page.beats || []).forEach((beat, b) => {
    const count = el("div", { class: "count" });
    const cap = el("input", { value: beat.caption || "" });
    const scene = el("textarea", {});
    scene.value = beat.scene || "";
    const upd = () => {
      beat.caption = cap.value.trim(); beat.scene = scene.value.trim();
      const w = charWidth(beat.caption);
      count.textContent = w + " 个字宽";
      count.className = "count" + (w > 18 ? " bad" : (w > 14 ? " long" : ""));
      scheduleValidate();
    };
    cap.addEventListener("input", upd); scene.addEventListener("input", upd);
    upd();
    rows.push(el("tr", {},
      el("td", { class: "where", text: "第" + (p + 1) + "张·第" + (b + 1) + "格" }),
      el("td", { class: "cap" }, cap, count),
      el("td", {}, scene)));
  }));
  $("beatRows").replaceChildren(...rows);
  $("editCard").classList.remove("hidden");
  validateNow();
}
["dTitle", "dCaption", "dTags"].forEach(id => $(id).addEventListener("input", () => {
  if (!state.deck) return;
  state.deck.title = $("dTitle").value.trim();
  state.deck.caption = $("dCaption").value;
  state.deck.hashtags = $("dTags").value.split(/\\s+/).filter(Boolean);
  scheduleValidate();
}));
let vTimer = null;
function scheduleValidate() { clearTimeout(vTimer); vTimer = setTimeout(validateNow, 350); }
async function validateNow() {
  if (!state.deck) return;
  state.deck.handle = $("handle").value.trim();
  try {
    const d = await api("/api/validate", Object.assign(options(), { deck: state.deck }));
    state.issues = d.issues;
    $("issues").replaceChildren(...d.issues.map(i => el("li", { class: i.level },
      el("b", { text: (i.level === "error" ? "✗ " : "△ ") + i.where + "：" }), document.createTextNode(i.message),
      i.fix ? el("span", { class: "fix", text: "改法：" + i.fix }) : null)));
    const errors = d.issues.filter(i => i.level === "error").length;
    $("budget").textContent = d.budget_text;
    $("btnRender").disabled = errors > 0;
    $("renderHint").textContent = errors ? "有 " + errors + " 个错误，改掉才能出图" :
      (d.issues.length ? "只剩警告，可以出图" : "体检通过");
  } catch (e) { $("renderHint").textContent = "体检失败：" + e.message; }
}
["handle", "style", "character", "styleprompt"].forEach(id => $(id).addEventListener("change", scheduleValidate));

// ---- ⑤ 出图 / 单格重画 ---------------------------------------------------------
$("btnRender").onclick = async () => {
  $("btnRender").disabled = true;
  $("progressCard").classList.remove("hidden");
  $("panelGrid").replaceChildren(); $("renderLog").replaceChildren();
  try {
    const d = await api("/api/render", Object.assign(options(), { deck: state.deck }));
    await follow(d.job, "renderLog", showResult);
  } catch (e) { say("renderLog", "✗ " + e.message, true); }
  $("btnRender").disabled = false;
};
async function reroll(panel) {
  $("progressCard").classList.remove("hidden");
  $("panelGrid").replaceChildren();
  try {
    const d = await api("/api/reroll", { out: state.outDir, panel, offline: $("offline").checked });
    await follow(d.job, "renderLog", showResult);
  } catch (e) { say("renderLog", "✗ " + e.message, true); }
}
function panelTiles(panels) {
  return Object.keys(panels).sort((a, b) => a - b).map(i => {
    const p = panels[i];
    return el("div", { class: "tile" },
      p.url ? el("img", { src: p.url, alt: "" }) : null,
      el("div", { class: "meta" }, el("b", { text: "第 " + (+i + 1) + " 格 " }),
        el("span", { class: "st-" + p.status, text: { ok: "完成", cached: "命中缓存", warn: "质检提醒", failed: "失败·占位图" }[p.status] || p.status })));
  });
}
function follow(jobId, box, onDone) {
  let seen = 0;
  return new Promise((resolve) => {
    const tick = async () => {
      let j;
      try { j = await api("/api/job/" + jobId); } catch (e) { say(box, "✗ " + e.message, true); return resolve(); }
      j.log.slice(seen).forEach(line => say(box, line)); seen = j.log.length;
      if (box === "renderLog") $("panelGrid").replaceChildren(...panelTiles(j.panels));
      if (j.status === "running") return setTimeout(tick, 1200);
      if (j.status === "error") say(box, "✗ " + j.error, true);
      else if (onDone) onDone(j.result);
      resolve();
    };
    tick();
  });
}
function showResult(res) {
  state.outDir = res.out;
  $("resultCard").classList.remove("hidden");
  $("pageGrid").replaceChildren(...res.pages.map(p => el("a", { href: p.full, target: "_blank" }, el("img", { src: p.thumb, alt: "" }))));
  $("previewBox").replaceChildren(res.preview ? el("a", { href: res.preview, target: "_blank" }, el("img", { src: res.preview, alt: "" })) : "");
  $("rerollGrid").replaceChildren(...res.panels.map(p => el("div", { class: "tile" },
    el("img", { src: p.url, alt: "" }),
    el("div", { class: "meta" }, el("div", { text: "第 " + p.panel + " 格：" + p.caption }),
      el("button", { class: "small ghost", text: "重画这一格", onclick: () => reroll(p.panel) })))));
  $("captionText").textContent = res.caption_text || "";
  const b = res.billing;
  if (b) say("renderLog", b.billed ? "本次实际发出 " + b.requests + " 次生图请求" : "离线 mock，不计费");
}
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
    token: str = ""
    allowed_hosts: frozenset = frozenset()
    server_version = "dig-ui/0.4"

    # 日志安静一点
    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    # -- 工具 ----------------------------------------------------------- #
    def _json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD:
            raise DigError("上传内容太大（上限 %d MB）" % (MAX_UPLOAD // 1024 // 1024))
        return self.rfile.read(length) if length else b""

    def _read_json(self) -> Dict[str, Any]:
        try:
            data = json.loads(self._read_body() or b"{}")
        except ValueError:
            raise DigError("请求体不是合法 JSON") from None
        if not isinstance(data, dict):
            raise DigError("请求体必须是 JSON 对象")
        return data

    def _cfg_for(self, offline: bool) -> Config:
        import copy

        cfg = Config(data=copy.deepcopy(self.cfg.data), path=self.cfg.path, root=self.cfg.root)
        if offline:
            cfg.use_mock()
        return cfg

    # -- 访问控制 ------------------------------------------------------- #
    def _host_ok(self) -> bool:
        """Host 必须是本机：挡住 DNS rebinding（恶意域名解析到 127.0.0.1 再来读写）。"""
        return (self.headers.get("Host") or "").strip().lower() in self.allowed_hosts

    def _api_ok(self) -> bool:
        """/api/ 必须带令牌；带了 Origin 的话也必须是本机页面。"""
        origin = (self.headers.get("Origin") or "").strip().lower()
        if origin and urllib.parse.urlparse(origin).netloc not in self.allowed_hosts:
            return False
        token = self.headers.get("X-Dig-Token") or ""
        return bool(self.token) and hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8"))

    def _deny(self, why: str) -> None:
        self._json({"error": why}, 403)

    # -- 路由 ----------------------------------------------------------- #
    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._deny("只允许本机访问")
            return
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route in ("/", "/index.html"):
            self._html(PAGE.replace("__TOKEN__", self.token))
            return
        if route == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if route.startswith("/files/"):
            query = urllib.parse.parse_qs(parsed.query)
            width = int((query.get("w") or ["0"])[0] or 0)
            self._serve_file(urllib.parse.unquote(route[len("/files/"):]), width)
            return
        if route.startswith("/api/"):
            if not self._api_ok():
                self._deny("缺少或错误的令牌")
                return
            try:
                if route == "/api/state":
                    self._json(self._state())
                    return
                if route == "/api/example":
                    self._json({"deck": load_json(os.path.join(self.cfg.root, "examples", "script.minimal.json"))})
                    return
                if route.startswith("/api/job/"):
                    job = JOBS.get(route[len("/api/job/"):])
                    if job is None:
                        self._json({"error": "没有这个任务"}, 404)
                        return
                    self._json({k: job[k] for k in ("id", "kind", "status", "log", "panels", "result", "error")})
                    return
            except DigError as exc:
                self._json({"error": redact(exc)})
                return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            self._deny("只允许本机访问")
            return
        if not self._api_ok():
            self._deny("缺少或错误的令牌（这个接口只接受本页面发起的请求）")
            return
        route = urllib.parse.urlparse(self.path).path
        handlers = {
            "/api/script": lambda: self._script(self._read_json()),
            "/api/validate": lambda: self._validate(self._read_json()),
            "/api/render": lambda: self._render(self._read_json()),
            "/api/reroll": lambda: self._reroll(self._read_json()),
            "/api/character": self._character,
            "/api/style": self._style,
        }
        fn = handlers.get(route)
        if fn is None:
            self.send_error(404)
            return
        try:
            self._json(fn())
        except DigError as exc:
            self._json({"error": redact(exc)}, 200)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            self._json({"error": redact("%s: %s" % (type(exc).__name__, exc))}, 200)

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

    def _script(self, body: Dict[str, Any]) -> Dict[str, Any]:
        theme = str(body.get("theme") or "").strip()
        if not theme:
            raise DigError("主题不能为空")
        cfg = self._cfg_for(bool(body.get("offline")))

        def work(job):
            # 只写脚本、不落盘：脚本在网页表格里改，出图时才建作品目录
            cid = str(body.get("character") or "")
            character = load_character(cfg, cid) if cid else None
            style = pipeline.resolve_style(cfg, str(body.get("style") or ""), str(body.get("style_prompt") or ""))
            pages = pipeline.clamp_pages(int(body.get("pages") or 0) or cfg.get("deck.pages", 6), True)
            panels = pipeline.clamp_panels(int(body.get("panels") or 0) or cfg.get("deck.panels_per_page", 2))
            Jobs.say(job, "正在写分镜脚本（%d 张 × %d 格）…" % (pages, panels))
            deck = script_gen.generate_script(
                cfg, make_text_engine(cfg.provider("text"), cfg.root),
                theme=theme, pages=pages, panels=panels, character=character,
                style_name=style.name, angle=str(body.get("angle") or ""),
                audience=str(body.get("audience") or ""), style=style,
            )
            deck.theme = deck.theme or theme
            deck.style_id = style.id
            deck.character_id = character.id if character else None
            deck.handle = str(body.get("handle") or "") or str(cfg.get("handle", "") or "")
            Jobs.say(job, "脚本完成：%s%s" % (deck.title or theme, "（已按体检结果自动改过一轮）"
                                            if deck.meta.get("repaired") else ""))
            return {"deck": deck.to_dict()}

        return {"job": JOBS.start("写脚本", work)}

    def _deck_from(self, body: Dict[str, Any]) -> Deck:
        data = body.get("deck")
        if not isinstance(data, dict):
            raise DigError("缺少脚本（deck）")
        deck = Deck.from_dict(data)
        for beat in deck.all_beats:          # 浏览器传回来的脚本不许指定本机文件
            beat.image, beat.error, beat.warning, beat.prompt = None, None, None, None
        if body.get("handle"):
            deck.handle = str(body["handle"])
        return deck

    def _validate(self, body: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self._cfg_for(bool(body.get("offline")))
        deck = self._deck_from(body)
        style = pipeline.resolve_style(cfg, str(body.get("style") or deck.style_id or ""),
                                       str(body.get("style_prompt") or ""))
        missing = None
        try:
            character = pipeline.resolve_character(cfg, deck, str(body.get("character") or ""))
        except DigError as exc:
            character, missing = None, exc
        page_size = (int(cfg.get("page.width", 1792)), int(cfg.get("page.height", 2400)))
        issues = validate.validate_deck(deck, style, character, page_size=page_size, cfg=cfg)
        if missing is not None:
            issues.insert(0, validate.Issue("error", "脚本", "character-missing", str(missing).splitlines()[0]))
        b = pipeline.budget(cfg, deck, character)
        if cfg.provider("image").provider == "mock":
            text = "离线 mock：%d 格，不计费" % b["panels"]
        else:
            text = "本次最多 %d 次计费请求（%d 格%s%s），已缓存的不计费" % (
                b["worst_case"], b["panels"],
                "＋定妆图 1" if b["sheet"] else "",
                ("＋质检重画最多 %d" % b["redraws_max"]) if b["redraws_max"] else "")
        return {
            "issues": [{"level": i.level, "where": i.where, "code": i.code, "message": i.message, "fix": i.fix}
                       for i in issues],
            "budget": b,
            "budget_text": text,
        }

    def _render(self, body: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self._cfg_for(bool(body.get("offline")))
        deck = self._deck_from(body)

        def work(job):
            result = pipeline.run(
                cfg,
                deck=deck,
                style_id=str(body.get("style") or ""),
                style_prompt=str(body.get("style_prompt") or ""),
                character_id=str(body.get("character") or ""),
                handle=str(body.get("handle") or ""),
                on_progress=lambda stage, msg: Jobs.say(job, msg),
                on_panel=self._panel_hook(job),
            )
            return self._result(result)

        return {"job": JOBS.start("出图", work)}

    def _reroll(self, body: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self._cfg_for(bool(body.get("offline")))
        out_dir = self._inside_output(str(body.get("out") or ""))
        script = os.path.join(out_dir, "script.json")
        if not os.path.isfile(script):
            raise DigError("找不到这套图的 script.json")
        panel = int(body.get("panel") or 0)

        def work(job):
            result = pipeline.reroll(
                cfg, script_path=script, panels=[panel],
                on_progress=lambda stage, msg: Jobs.say(job, msg),
                on_panel=self._panel_hook(job),
            )
            return self._result(result)

        return {"job": JOBS.start("重画第 %d 格" % panel, work)}

    def _panel_hook(self, job):
        def hook(i, beat, status):
            job["panels"][str(i)] = {
                "status": status,
                "url": self._file_url(beat.image, thumb=True) if beat.image else None,
            }
        return hook

    def _result(self, result: Dict[str, Any]) -> Dict[str, Any]:
        caption_text = ""
        try:
            with open(result["caption"], "r", encoding="utf-8") as fh:
                caption_text = fh.read()
        except Exception:  # noqa: BLE001
            pass
        deck = result["deck"]
        return {
            "out": os.path.relpath(result["out_dir"], self.cfg.output_dir).replace(os.sep, "/"),
            "pages": [{"thumb": self._file_url(f, thumb=True, width=640), "full": self._file_url(f)}
                      for f in result["files"]],
            "preview": self._file_url(result["preview"]) if result.get("preview") else None,
            "panels": [
                {"panel": i + 1, "caption": b.caption, "url": self._file_url(b.image, thumb=True)}
                for i, b in enumerate(deck.all_beats) if b.image
            ],
            "caption_text": caption_text,
            "billing": (result.get("stats") or {}).get("billing"),
            "ok": result.get("ok", True),
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
        try:
            char = register_character(cfg, vision, name=name, photo=tmp)
            if fields.get("stylize"):
                preset = load_style(cfg, fields.get("style") or str(cfg.get("style")))
                engine = make_image_engine(cfg.provider("image"), cfg.root)
                try:
                    stylize_character(cfg, engine, char, preset)
                except Exception as exc:  # noqa: BLE001
                    warn("定妆图生成失败（不影响后续，出图时会自动再画）：%s" % redact(exc))
        finally:
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
    def _inside_output(self, rel: str) -> str:
        base = os.path.abspath(self.cfg.output_dir)
        target = os.path.abspath(os.path.join(base, rel))
        if not target.startswith(base + os.sep):
            raise DigError("路径不在输出目录里")
        return target

    def _file_url(self, path: str, thumb: bool = False, width: int = 480) -> str:
        rel = os.path.relpath(os.path.abspath(path), self.cfg.output_dir)
        url = "/files/" + urllib.parse.quote(rel.replace(os.sep, "/"))
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            stamp = 0
        # 带上修改时间：重画之后同一个文件名，浏览器也会重新取
        return url + "?t=%d%s" % (int(stamp * 1000), ("&w=%d" % width) if thumb else "")

    def _serve_file(self, rel: str, width: int = 0) -> None:
        base = os.path.abspath(self.cfg.output_dir)
        target = os.path.abspath(os.path.join(base, rel))
        # 只允许读 output/ 里的东西
        if not target.startswith(base + os.sep) or not os.path.isfile(target):
            self.send_error(404)
            return
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if width and ctype.startswith("image/"):
            # 缩略图：进度页一格一张 2400 宽的 PNG 太重
            from PIL import Image

            with Image.open(target) as im:
                im = im.convert("RGB")
                im.thumbnail((max(64, min(width, 1200)), 4000))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=85)
            data, ctype = buf.getvalue(), "image/jpeg"
        else:
            with open(target, "rb") as fh:
                data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def make_server(cfg: Config, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    ensure_dir(cfg.output_dir)
    httpd = ThreadingHTTPServer((host, port), Handler)
    real_port = httpd.server_address[1]
    names = {"127.0.0.1", "localhost", host.lower()}
    Handler.cfg = cfg
    Handler.token = secrets.token_urlsafe(24)
    Handler.allowed_hosts = frozenset(
        ("[%s]:%d" if ":" in n else "%s:%d") % (n, real_port) for n in names
    )
    return httpd


def serve(cfg: Config, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        warn("网页版只该给本机用；监听 %s 会把它暴露给局域网" % host)
    httpd = make_server(cfg, host, port)
    url = "http://%s:%d/" % (host, httpd.server_address[1])
    log("网页版已启动：" + url)
    log("（只接受本机访问；Ctrl+C 退出）")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("\n已停止")
    finally:
        httpd.server_close()
