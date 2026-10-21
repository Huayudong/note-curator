#!/usr/bin/env python3
"""
vault_gate.py — B13 配置硬闸门（插件 PreToolUse 钩子）。

ZCode / Claude Code 插件形态下，由 hooks.json 以 process 方式在每次
Skill 工具调用前运行（参数向量、不经 shell，跨平台）：

    {"type": "process", "command": "python",
     "args": ["${CLAUDE_PLUGIN_ROOT}/hooks/vault_gate.py"]}

行为（与 SKILL.md「前置：强制配置检查」同一套判定）：
  - 只处理调用 note-curator 技能的请求，其他技能一律放行；
  - 复用 scripts/check_setup.py --json 判定配置是否就绪；
  - 就绪 → 退出码 0（放行）；
  - 未就绪（缺配置 / vault 路径无效 / 署名为空）→ 退出码 2（deny），
    stderr 写明原因与第 0 步引导流程；
  - 其余任何情况（stdin 非法、check 脚本缺失、超时、输出不可解析）
    一律放行（fail-open）：闸门是保险丝，不替代 SKILL.md 第 0 步的软约束，
    也不允许自己把插件卡死。

退出码：0 放行；2 拦截。测试可用 --check-script / --config 覆盖默认值。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

GATE_DIR = Path(__file__).resolve().parent
DEFAULT_CHECK = GATE_DIR.parent / "skills" / "note-curator" / "scripts" / "check_setup.py"
# 外层 hooks.json timeoutMs=20000 之前先自行超时，避免双重杀进程的歧义
SUBPROCESS_TIMEOUT_S = 15


def _force_utf8(stream):
    """B01-02/G16：Windows 默认编码环境下脚本自我声明 UTF-8。"""
    try:
        if (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _read_payload():
    """读取钩子事件 JSON；拿不到或非法时返回 None（放行）。"""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return None
    except Exception:
        return None
    try:
        raw = sys.stdin.read() or ""
        payload = json.loads(raw)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _targets_note_curator(payload):
    if str(payload.get("tool_name", "")) != "Skill":
        return False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return False
    # 技能名可能是 "note-curator" 或 "note-curator:note-curator"（插件:技能）
    return "note-curator" in str(tool_input.get("skill", "")).lower()


def _run_check(check_script, config_path):
    cmd = [sys.executable, str(check_script), "--json"]
    if config_path:
        cmd += ["--config", config_path]
    # 与各回归套件同一纪律：不依赖 PYTHONUTF8/PYTHONIOENCODING，
    # 让 check_setup 自己声明 UTF-8。
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=SUBPROCESS_TIMEOUT_S, env=env)


def _block(result):
    lines = ["[note-curator] 配置未就绪，本次技能调用已被拦截（status=%s）。"
             % result.get("status", "unknown"),
             "原因：%s" % result.get("message", ""),
             "标准修复：%s" % result.get("next", ""),
             "请按 SKILL.md 第 0 步引导：把原因告诉用户，一次性问齐 vault 路径与署名，"
             "运行 python scripts/init_setup.py --vault \"<路径>\" --author \"<署名>\""
             "（用户同意新建库时加 --create-vault），然后重跑 check_setup.py，"
             "只有 ok 才继续本次整理；不要绕过闸门生成或写入笔记。",
             "（用户坚持不配置只想要预览时：给不超过 300 字的短预览并标注"
             "「预览，未归档」，不要整理归档。）"]
    print("\n".join(lines), file=sys.stderr)
    return 2


def main():
    ap = argparse.ArgumentParser(description="note-curator 配置硬闸门（PreToolUse）")
    ap.add_argument("--check-script", default=str(DEFAULT_CHECK),
                    help="check_setup.py 路径；默认取同插件 skills 目录")
    ap.add_argument("--config", default=None,
                    help="透传给 check_setup.py --config（测试用）")
    args = ap.parse_args()
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)

    payload = _read_payload()
    if payload is None or not _targets_note_curator(payload):
        return 0

    try:
        proc = _run_check(args.check_script, args.config)
    except Exception as exc:
        print("[note-curator] vault_gate：配置检查未能运行，放行（fail-open）：%s" % exc,
              file=sys.stderr)
        return 0

    result = {}
    try:
        parsed = json.loads(proc.stdout or "")
        if isinstance(parsed, dict):
            result = parsed
    except Exception:
        result = {}

    if proc.returncode == 0 and result.get("ok") is True:
        return 0
    # check_setup 约定：退出码 2 = 需要配置，且 --json 一定带 ok/status。
    # 两者必须同时成立才拦截——Python 解释器对坏脚本路径也报 exit 2，
    # 不能把环境故障误判成「未配置」。
    if proc.returncode == 2 and result.get("ok") is False and result.get("status"):
        return _block(result)

    print("[note-curator] vault_gate：配置检查输出异常（exit=%s），放行（fail-open）。"
          % proc.returncode, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
