"""网页版：安全边界 + 离线跑通"写脚本 → 体检 → 出图 → 单格重画"。

安全边界这条是实测出来的：以前任何网页都能对 127.0.0.1:8765/api/generate
发一个 text/plain 的跨站 POST（浏览器对这种请求不做预检），用你的 Key 跑整套计费生图。
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

from _helpers import ROOT, offline_cfg, quiet, run_all

from dig import webui


@contextlib.contextmanager
def server():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = offline_cfg(tmp)
        httpd = webui.make_server(cfg, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:%d" % httpd.server_address[1], webui.Handler.token, cfg
        finally:
            httpd.shutdown()
            httpd.server_close()


def call(base, path, body=None, token=None, headers=None):
    hdrs = dict(headers or {})
    if token:
        hdrs["X-Dig-Token"] = token
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(base + path, data=data, headers=hdrs, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def wait(base, token, job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, body = call(base, "/api/job/" + job_id, token=token)
        job = json.loads(body)
        if job["status"] != "running":
            return job
        time.sleep(0.3)
    raise AssertionError("任务超时")


def example_deck():
    with open(os.path.join(ROOT, "examples", "script.minimal.json"), encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------------------- #
def test_page_embeds_a_session_token():
    with server() as (base, token, _):
        status, body = call(base, "/")
        assert status == 200
        assert re.search(r'name="dig-token" content="%s"' % re.escape(token), body.decode("utf-8"))


def test_api_requires_the_token():
    with server() as (base, token, _):
        for bad in (None, "wrong-token"):
            status, _ = call(base, "/api/validate", {"deck": example_deck()}, token=bad)
            assert status == 403, bad


def test_cross_site_requests_are_refused():
    with server() as (base, token, _):
        # 恶意网页发的"简单请求"：text/plain、不带令牌、Origin 是别的站
        status, _ = call(base, "/api/render", {"deck": example_deck()},
                         headers={"Content-Type": "text/plain", "Origin": "https://evil.example"})
        assert status == 403
        # 就算拿到了令牌，Origin 不对也不行
        status, _ = call(base, "/api/validate", {"deck": example_deck()}, token=token,
                         headers={"Origin": "https://evil.example"})
        assert status == 403


def test_foreign_host_header_is_refused():
    """DNS rebinding：恶意域名解析到 127.0.0.1，Host 头会是那个域名。"""
    with server() as (base, _, _cfg):
        port = base.rsplit(":", 1)[1]
        status, _ = call(base, "/", headers={"Host": "evil.example:%s" % port})
        assert status == 403


def test_validate_endpoint_reports_issues_and_budget():
    with server() as (base, token, _):
        deck = example_deck()
        deck["pages"][0]["beats"][1]["caption"] = deck["pages"][0]["beats"][0]["caption"]
        status, body = call(base, "/api/validate", {"deck": deck, "offline": True}, token=token)
        data = json.loads(body)
        assert status == 200
        assert any(i["code"] == "caption-duplicate" and i["level"] == "error" for i in data["issues"])
        assert data["budget"]["panels"] == 10


def test_render_then_reroll_offline():
    with server() as (base, token, cfg):
        with quiet():
            _, body = call(base, "/api/render", {"deck": example_deck(), "offline": True}, token=token)
            job = wait(base, token, json.loads(body)["job"])
        assert job["status"] == "done", job.get("error")
        result = job["result"]
        assert result["ok"] and len(result["pages"]) == 5 and result["preview"]
        assert len(job["panels"]) == 10, "每一格完成时都该回报进度"

        status, _ = call(base, result["pages"][0]["thumb"])
        assert status == 200

        with quiet():
            _, body = call(base, "/api/reroll", {"out": result["out"], "panel": 4, "offline": True}, token=token)
            job = wait(base, token, json.loads(body)["job"])
        assert job["status"] == "done", job.get("error")
        with open(os.path.join(cfg.output_dir, result["out"], "manifest.json"), encoding="utf-8") as fh:
            assert json.load(fh)["panels"][3]["variant"] == 1


def test_browser_supplied_decks_cannot_point_at_local_files():
    with server() as (base, token, _):
        deck = example_deck()
        deck["pages"][0]["beats"][0]["image"] = "/etc/passwd"
        with quiet():
            _, body = call(base, "/api/render", {"deck": deck, "offline": True}, token=token)
            job = wait(base, token, json.loads(body)["job"])
        assert job["status"] == "done"


def test_file_route_stays_inside_the_output_folder():
    with server() as (base, _, _cfg):
        status, _ = call(base, "/files/..%2F..%2Fetc%2Fpasswd")
        assert status == 404


if __name__ == "__main__":
    raise SystemExit(run_all(globals()))
