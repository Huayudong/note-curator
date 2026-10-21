#!/usr/bin/env python3
"""
run_b13_tests.py — B13 配置硬闸门（vault_gate）回归测试。

覆盖：
  1. hooks.json 契约：PreToolUse 事件、Skill 匹配器、process 参数、脚本存在
  2. 放行路径：非 note-curator 技能、非 Skill 工具、配置就绪
  3. 拦截路径：缺配置 / vault 路径不存在 / 署名为空 → 退出码 2
  4. fail-open：stdin 非法、check 脚本缺失（解释器 exit 2 不误判为未配置）
  5. 技能名带插件前缀（note-curator:note-curator）同样被拦截

用法：python tests/run_b13_tests.py
退出码：0 全部通过；1 有失败。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN = REPO_ROOT / "plugins" / "note-curator"
HOOKS = PLUGIN / "hooks"
GATE = HOOKS / "vault_gate.py"
CHECK = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts" / "check_setup.py"

FAILURES = []


def check(name, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else " — %s" % str(detail)[:280]))
    if not condition:
        FAILURES.append(name)


def run_gate(stdin_text, check_script=None, config=None):
    cmd = [sys.executable, str(GATE)]
    if check_script is not None:
        cmd += ["--check-script", str(check_script)]
    if config is not None:
        cmd += ["--config", str(config)]
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    return subprocess.run(cmd, input=stdin_text, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=env)


def skill_event(skill="note-curator", tool="Skill"):
    return json.dumps({"tool_name": tool,
                       "tool_input": {"skill": skill, "args": "整理这篇文章"}})


def write_config(root, vault, author):
    cfg = Path(root) / "config.yaml"
    cfg.write_text(
        'vault_path: "%s"\n'
        'interface_language: "zh"\n'
        "frontmatter:\n"
        '  author: "%s"\n' % (Path(vault).as_posix(), author),
        encoding="utf-8")
    return cfg


def main():
    check("gate script exists", GATE.is_file())

    # ---- 1. hooks.json 契约 ----
    try:
        spec = json.loads((HOOKS / "hooks.json").read_text(encoding="utf-8"))
    except Exception as exc:
        spec = None
        check("hooks.json parses", False, exc)
    if spec:
        entries = spec.get("hooks", {}).get("PreToolUse", [])
        check("PreToolUse event registered", len(entries) == 1)
        entry = entries[0] if entries else {}
        check("matcher is Skill", entry.get("matcher") == "Skill", entry.get("matcher"))
        hooks = entry.get("hooks", [])
        check("one process hook", len(hooks) == 1 and hooks[0].get("type") == "process")
        hook = hooks[0] if hooks else {}
        args = [str(a) for a in hook.get("args", [])]
        check("args target vault_gate.py",
              len(args) == 1 and args[0].replace("\\", "/").endswith("hooks/vault_gate.py"),
              args)
        check("timeoutMs sane",
              isinstance(hook.get("timeoutMs"), int) and hook["timeoutMs"] >= 5000,
              hook.get("timeoutMs"))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        vault = root / "vault"
        vault.mkdir()
        cfg_ok = write_config(root, vault, "Tester")

        # ---- 2. 放行路径 ----
        r = run_gate(skill_event(skill="obsidian:setup"))
        check("unrelated skill allowed", r.returncode == 0, r.stderr[:200])
        r = run_gate(skill_event(skill="note-curator", tool="Bash"))
        check("non-Skill tool allowed", r.returncode == 0, r.stderr[:200])
        r = run_gate(skill_event(), check_script=CHECK, config=cfg_ok)
        check("valid config allowed", r.returncode == 0,
              "rc=%s stderr=%s" % (r.returncode, r.stderr[:200]))
        check("allow keeps stdout empty", r.stdout.strip() == "", r.stdout[:120])

        # ---- 3. 拦截路径 ----
        cfg_missing = root / "no-such-config.yaml"
        r = run_gate(skill_event(), check_script=CHECK, config=cfg_missing)
        check("missing config blocked", r.returncode == 2, r.stderr[:200])
        check("block explains via stderr",
              "[note-curator]" in r.stderr and "init_setup.py" in r.stderr, r.stderr[:200])
        check("block keeps stdout empty", r.stdout.strip() == "", r.stdout[:120])

        cfg_vault = write_config(root, root / "gone-vault", "Tester")
        r = run_gate(skill_event(), check_script=CHECK, config=cfg_vault)
        check("dead vault path blocked", r.returncode == 2, r.stderr[:200])

        cfg_author = write_config(root, vault, "")
        r = run_gate(skill_event(), check_script=CHECK, config=cfg_author)
        check("empty author blocked", r.returncode == 2, r.stderr[:200])

        r = run_gate(skill_event(skill="note-curator:note-curator"),
                     check_script=CHECK, config=cfg_missing)
        check("plugin-prefixed skill blocked", r.returncode == 2, r.stderr[:200])

        # ---- 4. fail-open ----
        r = run_gate("not-json")
        check("malformed stdin fail-open", r.returncode == 0, r.stderr[:200])
        r = run_gate("")
        check("empty stdin fail-open", r.returncode == 0, r.stderr[:200])
        r = run_gate(skill_event(), check_script=root / "missing_check.py",
                     config=cfg_missing)
        check("missing check script fail-open (interpreter exit 2 not misread)",
              r.returncode == 0, r.stderr[:200])

    print()
    if FAILURES:
        print("FAILED: %d — %s" % (len(FAILURES), ", ".join(FAILURES)))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
