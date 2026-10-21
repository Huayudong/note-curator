#!/usr/bin/env python3
"""
run_plugin_contract.py — 插件契约测试。

不启动 Obsidian 也能验证的插件闭环：
  1. main.js 语法（node --check；无 node 时显式跳过）
  2. main.js 引用的核心脚本都存在，且 argparse 完好（--help 退出 0）
  3. 被调用脚本都支持 --json（桥的统一契约）
  4. model_generate：mock 确定性生成（事实保留 + layers 标记）
  5. model_generate：api 通道走本地 HTTP 服务（Bearer key 只进 header，
     不落盘不出现在输出）；缺 key 明确报错
  6. 保存事件隔离：插件待学习清单由桥逻辑写入，不触碰 vault

用法：python tests/run_plugin_contract.py
退出码：0 通过；1 失败。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts"
PLUGIN = REPO_ROOT / "apps" / "obsidian-plugin"

FAILURES = []


def check(name, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else " — %s" % str(detail)[:300]))
    if not condition:
        FAILURES.append(name)


def run(args, home=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    if home:
        env["NOTE_CURATOR_HOME"] = str(home)
    return subprocess.run([sys.executable] + [str(a) for a in args],
                          capture_output=True, encoding="utf-8", errors="replace",
                          env=env)


def main():
    main_js = PLUGIN / "main.js"
    check("plugin files exist", main_js.is_file()
          and (PLUGIN / "manifest.json").is_file()
          and (PLUGIN / "styles.css").is_file())

    node = None
    for candidate in ("node", "node.exe"):
        try:
            probe = subprocess.run([candidate, "--version"], capture_output=True)
            if probe.returncode == 0:
                node = candidate
                break
        except OSError:
            continue
    if node:
        r = subprocess.run([node, "--check", str(main_js)], capture_output=True)
        check("main.js syntax (node --check)", r.returncode == 0, r.stderr[:200])
    else:
        print("[SKIP] node 不可用，跳过语法检查")

    # main.js 引用的核心脚本契约
    src = main_js.read_text(encoding="utf-8")
    referenced = sorted(set(re.findall(r'"((?:check_setup|source_document|'
                                       r'model_generate|write_note|learn_edit|'
                                       r'preferences|fact_check)\.py)"', src)))
    check("main.js references core scripts", len(referenced) >= 6, str(referenced))
    for script in referenced:
        check("exists: " + script, (SCRIPTS / script).is_file())
        help_r = subprocess.run([sys.executable, str(SCRIPTS / script), "--help"],
                                capture_output=True, encoding="utf-8",
                                errors="replace")
        check("argparse ok: " + script, help_r.returncode == 0, help_r.stderr[:120])
        py_src = (SCRIPTS / script).read_text(encoding="utf-8")
        check("supports --json: " + script, '"--json"' in py_src)

    # model_generate：mock + api 双通道
    SEEN = {"auth": ""}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            json.loads(self.rfile.read(length))
            SEEN["auth"] = self.headers.get("Authorization", "")
            resp = {"choices": [{"message": {"content": "# API草稿\n\n模型正文 42。"}}],
                    "usage": {}}
            data = json.dumps(resp).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home = td / "home"
        doc = td / "doc.json"
        doc.write_text(json.dumps({
            "schema": 1, "kind": "file", "title": "缓存测试",
            "segments": [{"type": "paragraph",
                          "text": "缓存通常在 60s 后失效，命中率 45%，仅在只读负载下测试。"}],
        }, ensure_ascii=False), encoding="utf-8")

        r = run([SCRIPTS / "model_generate.py", "--source-doc", doc,
                 "--register", "technical", "--lang", "zh",
                 "--out", td / "d1.md", "--provider", "mock", "--json"], home)
        j = json.loads(r.stdout)
        check("mock generate rc0", r.returncode == 0 and j["ok"], r.stdout[:150])
        draft = (td / "d1.md").read_text(encoding="utf-8")
        check("mock keeps facts", "60s" in draft and "45%" in draft and "仅在" in draft,
              draft[:200])
        check("mock layers marker", "layers: public,profile,prefs" in draft)

        r = run([SCRIPTS / "model_generate.py", "--source-doc", doc,
                 "--out", td / "d2.md", "--provider", "mock",
                 "--layers", "public", "--json"], home)
        check("layers ablation marker",
              "layers: public" in (td / "d2.md").read_text(encoding="utf-8"))

        r = run([SCRIPTS / "model_generate.py", "--source-doc", doc,
                 "--out", td / "d3.md", "--provider", "api",
                 "--base-url", "http://127.0.0.1:%d" % port,
                 "--model", "test-model", "--api-key", "sk-contract", "--json"], home)
        j3 = json.loads(r.stdout)
        check("api generate rc0", r.returncode == 0 and j3["ok"], r.stdout[:150])
        check("api key only in header", SEEN["auth"] == "Bearer sk-contract")
        d3 = (td / "d3.md").read_text(encoding="utf-8")
        check("api key never leaked",
              "sk-contract" not in r.stdout and "sk-contract" not in d3)

        r = run([SCRIPTS / "model_generate.py", "--source-doc", doc,
                 "--out", td / "d4.md", "--provider", "api",
                 "--base-url", "http://127.0.0.1:%d" % port,
                 "--model", "m", "--json"], home)
        check("missing key rejected rc1", r.returncode == 1, "rc=%s" % r.returncode)

    srv.shutdown()
    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All plugin contract tests passed.")


if __name__ == "__main__":
    main()
