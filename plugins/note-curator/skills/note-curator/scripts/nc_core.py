#!/usr/bin/env python3
"""
nc_core.py — note-curator 共享基础层（B01 抽取）。

所有入口脚本 import 本模块即可获得：
  1. 统一 UTF-8 标准输入输出（Windows 默认 GBK 环境不再需要 PYTHONUTF8）。
  2. 内容哈希、原子写入（同目录临时文件 + os.replace）。
  3. vault 目标路径安全校验：拒绝绝对路径 / .. / 越出 vault / 符号链接逃逸 /
     Windows 保留名 / 仅大小写不同的同名碰撞。
  4. WritePlan、写入日志、受控备份、生成基线的存储约定：
       <data_root>/plans/<run_id>.json        计划（含预览内容与状态）
       <data_root>/writes/log.jsonl           写入日志（追加）
       <data_root>/writes/backup/<run_id>.md  应用前备份（merge）
       <data_root>/writes/backup/<run_id>.reverse.patch  撤销冲突时的反向差异
       <data_root>/baselines/<run_id>.json    生成基线（供后续改稿比较，不自动学习）
  <data_root> 默认 ~/.note-curator，可用环境变量 NOTE_CURATOR_HOME 覆盖（测试用）。

只依赖 Python 标准库。
"""

import datetime
import hashlib
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

SCHEMA_VERSION = 1


# ---------- 标准流编码（G16：Windows 默认编码下脚本必须可运行） ----------

def force_utf8_stdio():
    """把 stdout/stderr 重配为 UTF-8；老 Python 或非常规流失败时静默忽略。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


force_utf8_stdio()


# ---------- 基础工具 ----------

def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def new_run_id():
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return "%s-%s" % (stamp, uuid.uuid4().hex[:8])


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def data_root():
    env = os.environ.get("NOTE_CURATOR_HOME")
    return Path(env).expanduser() if env else Path.home() / ".note-curator"


def plans_dir():
    return data_root() / "plans"


def writes_dir():
    return data_root() / "writes"


def writes_log_path():
    return writes_dir() / "log.jsonl"


def backup_path(run_id):
    return writes_dir() / "backup" / ("%s.md" % run_id)


def reverse_patch_path(run_id):
    return writes_dir() / "backup" / ("%s.reverse.patch" % run_id)


def baselines_dir():
    return data_root() / "baselines"


def atomic_write_text(path, text):
    """同目录临时文件 + fsync + os.replace 的原子写入。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix="." + path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------- vault 目标路径安全（B01-04） ----------

WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"}
WINDOWS_RESERVED.update("COM%d" % i for i in range(1, 10))
WINDOWS_RESERVED.update("LPT%d" % i for i in range(1, 10))


def safe_filename(title):
    """标题 → 安全文件名：非法字符替换、Windows 保留名处理、结尾点/空格去除。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(title)).strip()
    name = re.sub(r"\s+", " ", name).rstrip(" .")
    stem = name[:-3] if name.lower().endswith(".md") else name
    if stem.upper() in WINDOWS_RESERVED:
        stem = stem + " 笔记"
    if not stem:
        stem = "未命名笔记"
    return stem[:120] + ".md"


def resolve_vault_target(vault, rel):
    """校验 rel 是 vault 内安全相对路径，返回解析后的绝对 Path。

    拒绝：空路径、绝对路径、盘符/UNC、.. 上跳、解析后越出 vault
    （含符号链接 / junction 指向库外的情况）。违规抛 ValueError。
    """
    vault = Path(vault)
    raw = str(rel).strip().strip('"').replace("\\", "/")
    if not raw:
        raise ValueError("目标路径为空")
    if re.match(r"^[A-Za-z]:", raw) or raw.startswith("//"):
        raise ValueError("目标必须是 vault 内相对路径，不接受绝对路径: %r" % raw)
    parts = [part for part in Path(raw).parts if part not in ("", ".")]
    if not parts:
        raise ValueError("目标路径为空: %r" % raw)
    if any(part == ".." for part in parts):
        raise ValueError("目标路径不允许上跳（..）: %r" % raw)
    target = vault.joinpath(*parts).resolve()
    try:
        target.relative_to(vault.resolve())
    except ValueError:
        raise ValueError("目标解析后越出 vault（可能是符号链接指向库外）: %r -> %s"
                         % (raw, target))
    return target


def check_case_collision(target):
    """同目录已有仅大小写不同的同名文件时报错（不论目标本身是否存在）。

    Windows 文件系统大小写不敏感，放行会静默覆盖另一篇笔记。
    """
    parent = target.parent
    if not parent.is_dir():
        return
    lowered = target.name.lower()
    for sibling in parent.iterdir():
        if sibling.name.lower() == lowered and sibling.name != target.name:
            raise ValueError("目标目录已存在仅大小写不同的同名文件「%s」（Windows 会互相覆盖，请换标题或改用 merge）"
                             % sibling.name)


# ---------- WritePlan / 写入日志 / 备份 / 基线（B01-03、06、08） ----------

def save_plan(plan):
    path = plans_dir() / ("%s.json" % plan["run_id"])
    atomic_write_text(path, json.dumps(plan, ensure_ascii=False, indent=2))
    return path


def load_plan(ref):
    """ref 可以是 run_id 或计划文件路径；找不到返回 None。"""
    candidate = Path(ref)
    if not candidate.suffix:
        candidate = plans_dir() / ("%s.json" % ref)
    if not candidate.is_file():
        return None
    try:
        return json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def append_write_log(entry):
    entry = dict(entry, at=now_iso())
    writes_dir().mkdir(parents=True, exist_ok=True)
    with open(writes_log_path(), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_write_log(limit=20):
    path = writes_log_path()
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries[-limit:]


def save_baseline(run_id, target_rel, content, source_type, note=None):
    """保存生成基线（B01-08）：只用于后续改稿比较与溯源，不自动进入风格学习。"""
    baseline = {
        "schema": SCHEMA_VERSION,
        "run_id": run_id,
        "target": target_rel,
        "content": content,
        "content_hash": sha256_text(content),
        "source_type": source_type,
        "model": None,
        "created_at": now_iso(),
        "note": note,
    }
    path = baselines_dir() / ("%s.json" % run_id)
    atomic_write_text(path, json.dumps(baseline, ensure_ascii=False, indent=2))
    return path
