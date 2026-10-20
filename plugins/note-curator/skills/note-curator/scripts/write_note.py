#!/usr/bin/env python3
"""
write_note.py — 把笔记写入知识库（vault）。B01 起所有写入走统一 WritePlan 事务。

两种整理操作：
  new   新建：<vault>/<dir>/<title>.md；默认仅预览，--apply 才写盘。
  merge 合并：按 patch（APPEND/EDIT 操作块）改已有笔记；默认仅预览，--apply 才写盘。

四个事务入口（new / merge 共用同一提交模型）：
  apply  提交一份已生成的计划：--run <run_id> 或 --plan <计划文件路径>
  undo   撤销一次已提交的写入（--run）；用户此后又改过文件时拒绝直接恢复，
         生成反向差异文件交由人工处理
  log    查看最近写入记录
  prune  按保留期限清理 plans / baselines / backups

安全与一致性约定（见 nc_core.py）：
  - 只允许写 vault 内路径；拒绝绝对路径、..、符号链接逃逸、Windows 保留名、
    仅大小写不同的同名碰撞。
  - 原子写入：同目录临时文件 + fsync + os.replace；merge 提交前先把原文备份到
    受控备份目录，写前校验 base_hash，外部修改会被拒绝而不是覆盖。
  - 幂等：同一 run_id 重复 apply 不重复写入、不重复来源；重复 append 片段
    自动跳过（SKIP-DUP）。
  - 生成基线（baselines/<run_id>.json）记录本次生成内容与来源类型，仅供后续
    改稿比较与溯源，**不会自动进入风格学习**（学习只认用户改稿）。

patch 文件格式（merge 模式输入，由 LLM 按 merge-rules.md 生成）:
    ---
    source: "https://example.com/a"          # 来源（必填，缺失填「本地草稿」）
    ---
    ## APPEND <section>                      # 追加到小节末尾；## APPEND EOF 表示文件末尾
    （要追加的 markdown）

    ## EDIT                                  # 可选：精确替换（仅原笔记确有错误时）
    <<<OLD
    原文里需要被替换的精确字符串
    >>>NEW
    替换成的内容（留空表示删除）

退出码：0 成功（含幂等无操作）；1 参数/IO 错误；2 状态拒绝（目标已存在、
路径违规、计划不存在）；3 基线冲突（目标被外部修改，未写入，已生成反向差异）。
"""

import argparse
import difflib
import json
import re
import sys
import time
from pathlib import Path

import nc_core
from nc_core import (sha256_text, atomic_write_text, now_iso,
                     resolve_vault_target, check_case_collision, safe_filename)

FRONTMATTER_RE = re.compile(r"\A(---\s*\n.*?\n---\s*\n?)(.*)$", re.DOTALL)

SOURCE_TYPES = ("user_original", "user_edited", "quoted", "imported",
                "generated", "unknown")

# 退出码
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REJECTED = 2
EXIT_CONFLICT = 3


class TaskError(Exception):
    """带退出码与错误码的任务失败；--json 时输出结构化结果。"""

    def __init__(self, code, message, exit_code=EXIT_REJECTED, run_id=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.run_id = run_id


class ConflictError(TaskError):
    def __init__(self, code, message, run_id=None, detail=None):
        super().__init__(code, message, exit_code=EXIT_CONFLICT, run_id=run_id)
        self.detail = detail


# ---------- patch 解析与合并执行（与 v1.6 行为兼容） ----------

class AppendOp:
    def __init__(self, section, fragment):
        self.section = section
        self.fragment = fragment


class EditOp:
    def __init__(self, old, new):
        self.old = old
        self.new = new


def parse_patch(patch_text):
    """解析 patch：提取 frontmatter.source 和若干 APPEND/EDIT 操作。"""
    source = ""
    body = patch_text
    m = FRONTMATTER_RE.match(patch_text)
    if m:
        fm = m.group(1)
        body = m.group(2)
        for line in fm.splitlines():
            line = line.strip()
            if line.startswith("source:"):
                source = line.split(":", 1)[1].strip().strip("\"'")
    ops = []
    parts = re.split(r"(?=^## (?:APPEND|EDIT)\b)", body, flags=re.MULTILINE)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## APPEND"):
            head, _, rest = part.partition("\n")
            section = head[len("## APPEND"):].strip() or "EOF"
            ops.append(AppendOp(section, rest.strip()))
        elif part.startswith("## EDIT"):
            em = re.search(r"<<<OLD\s*\n(.*?)\n>>>NEW\s*\n?(.*)$", part, re.DOTALL)
            if em:
                ops.append(EditOp(em.group(1), em.group(2).strip()))
    return source, ops


def split_target(text):
    """拆成 (frontmatter块(含---), 正文)。无 frontmatter 时块为空。"""
    m = FRONTMATTER_RE.match(text)
    if m:
        return m.group(1), m.group(2)
    return "", text


def find_section_insert_point(body, section):
    """返回 (插入起始idx, 插入结束idx, 是否新建小节)。"""
    if section in ("", "EOF"):
        return len(body), len(body), False
    sec_level = len(section) - len(section.lstrip("#"))
    start = body.find(section)
    if start == -1:
        return len(body), len(body), True
    after = body.find("\n", start) + 1
    nxt = re.search(r"^(#{1," + str(sec_level) + r"}\s+\S.*)$", body[after:],
                    re.MULTILINE)
    cut = after + nxt.start() if nxt else len(body)
    return after, cut, False


def _normalized_contains(haystack, needle):
    """去空白/换行后判断 needle 是否已在 haystack 中，避免重复写入。"""
    def norm(s):
        return re.sub(r"\s+", "", s)
    return norm(needle) in norm(haystack)


def apply_ops(body, ops):
    """依次应用操作，返回 (新正文, 变更日志列表)。日志项: (类型, 描述, 片段)。"""
    log = []
    new_body = body
    for op in ops:
        if isinstance(op, AppendOp):
            frag = op.fragment.strip()
            if not frag:
                continue
            if _normalized_contains(new_body, frag):
                log.append(("SKIP-DUP", "片段已存在于笔记，跳过追加（section=%s）"
                            % op.section, frag))
                continue
            start, cut, create = find_section_insert_point(new_body, op.section)
            if op.section in ("", "EOF"):
                new_body = new_body.rstrip() + "\n\n" + frag + "\n"
                log.append(("APPEND", "追加到文件末尾", frag))
            elif create:
                new_body = (new_body.rstrip()
                            + "\n\n" + op.section + "\n\n" + frag + "\n")
                log.append(("APPEND", "文件末尾新建小节「%s」并追加" % op.section, frag))
            else:
                new_body = (new_body[:cut].rstrip() + "\n\n" + frag + "\n\n"
                            + new_body[cut:].lstrip())
                log.append(("APPEND", "追加到小节「%s」末尾" % op.section, frag))
        elif isinstance(op, EditOp):
            if not op.old:
                log.append(("SKIP", "EDIT 的 OLD 为空，跳过", ""))
                continue
            if op.new and _normalized_contains(new_body, op.new):
                log.append(("SKIP", "EDIT 的 NEW 已存在于笔记，疑似重复应用，跳过", op.new))
                continue
            if op.old in new_body:
                count = new_body.count(op.old)
                new_body = new_body.replace(op.old, op.new)
                action = "删除" if not op.new else "替换"
                log.append(("EDIT", "%s原文（命中 %d 处）" % (action, count),
                            "-" + op.old + "\n+" + op.new))
            else:
                log.append(("SKIP", "EDIT 的 OLD 未在原文找到，跳过（避免误改）", op.old))
    return new_body, log


def source_footnote(source):
    """合并留痕：来源追加到正文文末，不写 frontmatter。"""
    return "---\n来源补充：%s - %s\n" % (source, now_iso()[:10])


# ---------- 计划构建与提交 ----------

def load_vault(path):
    vault = Path(str(path)).expanduser()
    if not vault.is_dir():
        raise TaskError("E-VAULT-MISSING", "vault 不存在: %s" % vault,
                        exit_code=EXIT_ERROR)
    return vault.resolve()


def build_plan(vault, op, target_rel, base_text, new_text, source, source_type):
    return {
        "schema": nc_core.SCHEMA_VERSION,
        "run_id": nc_core.new_run_id(),
        "op": op,
        "vault": str(vault),
        "target": target_rel,
        "base_hash": sha256_text(base_text) if base_text is not None else None,
        "content_hash": sha256_text(new_text),
        "content": new_text,
        "source": source or "",
        "source_type": source_type,
        "created_at": now_iso(),
        "status": "previewed",
    }


def emit(args, payload):
    """--json 时向 stdout 输出结构化结果；否则不占 stdout（人读摘要在 stderr）。"""
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))


def finish_task(args, plan, status, message, extra=None):
    payload = {
        "ok": True,
        "run_id": plan["run_id"],
        "op": plan["op"],
        "status": status,
        "target": plan["target"],
        "message": message,
    }
    if extra:
        payload.update(extra)
    emit(args, payload)
    return EXIT_OK


def commit_plan(args, plan):
    """把一份计划提交写盘。幂等：已提交 / 内容已一致时只补记账，不重复写入。"""
    if plan.get("status") == "committed":
        return finish_task(args, plan, "already-applied",
                           "该计划已提交过，本次为幂等无操作。")
    if plan.get("status") == "reverted":
        raise TaskError("E-PLAN-REVERTED",
                        "该计划已撤销，不能再次应用；请重新整理生成新计划。",
                        run_id=plan["run_id"])
    vault = load_vault(plan["vault"])
    target = resolve_vault_target(vault, plan["target"])
    run_id = plan["run_id"]

    if plan["op"] == "new":
        if target.exists():
            current = target.read_text(encoding="utf-8")
            if sha256_text(current) == plan["content_hash"]:
                # 上次 apply 写盘后记账中断：补记账即视为成功
                record_commit(plan, target, old_text=None)
                return finish_task(args, plan, "already-applied",
                                   "目标已是本计划的内容（记账已补全），无重复写入。")
            raise ConflictError(
                "E-CONFLICT-EXISTS",
                "提交失败：目标已被外部创建且内容不同，本计划未写入（未覆盖任何内容）。",
                run_id=run_id,
                detail={"target": str(target)})
        atomic_write_text(target, plan["content"])
        record_commit(plan, target, old_text=None)
        return finish_task(args, plan, "committed", "已新建：%s" % target)

    # merge
    if not target.exists():
        raise TaskError("E-TARGET-MISSING",
                        "提交失败：目标旧笔记已不存在: %s" % target,
                        run_id=run_id)
    current = target.read_text(encoding="utf-8")
    current_hash = sha256_text(current)
    if current_hash == plan["content_hash"]:
        record_commit(plan, target, old_text=None, recovered=True)
        return finish_task(args, plan, "already-applied",
                           "目标已是本计划的内容（记账已补全），无重复写入。")
    if current_hash != plan["base_hash"]:
        patch_file = write_reverse_patch(run_id, current, plan["content"])
        raise ConflictError(
            "E-CONFLICT-BASE",
            "提交失败：预览后目标被外部修改（base_hash 不一致），本计划未写入。"
            "请重新预览生成新计划；旧计划与当前内容的差异见反向差异文件。",
            run_id=run_id,
            detail={"target": str(target), "reverse_patch": str(patch_file)})
    atomic_write_text(nc_core.backup_path(run_id), current)   # 先备份原文
    atomic_write_text(target, plan["content"])
    record_commit(plan, target, old_text=current)
    return finish_task(args, plan, "committed", "已合并写入：%s" % target)


def record_commit(plan, target, old_text, recovered=False):
    """写入后的记账：日志 + 计划状态 + 生成基线。任何一步失败可由 apply 幂等重放。"""
    nc_core.append_write_log({
        "run_id": plan["run_id"],
        "op": plan["op"],
        "target": plan["target"],
        "base_hash": plan["base_hash"],
        "new_hash": plan["content_hash"],
        "status": "committed",
        "recovered": recovered,
    })
    if old_text is not None:
        atomic_write_text(nc_core.backup_path(plan["run_id"]), old_text)
    plan["status"] = "committed"
    plan["committed_at"] = now_iso()
    nc_core.save_plan(plan)
    nc_core.save_baseline(plan["run_id"], plan["target"], plan["content"],
                          plan.get("source_type", "generated"),
                          note=plan.get("source") or None)


def write_reverse_patch(run_id, current_text, plan_text):
    """撤销/提交冲突时生成「当前内容 → 计划内容（撤销场景为备份内容）」的差异文件。"""
    diff = difflib.unified_diff(
        current_text.splitlines(keepends=True),
        plan_text.splitlines(keepends=True),
        fromfile="当前笔记（用户可能已修改）",
        tofile="计划/备份版本",
    )
    path = nc_core.reverse_patch_path(run_id)
    atomic_write_text(path, "".join(diff))
    return path


def cmd_apply(args):
    plan = nc_core.load_plan(args.run or args.plan)
    if plan is None:
        raise TaskError("E-PLAN-MISSING",
                        "找不到写入计划：%s（--run 接 run_id，--plan 接计划文件路径）"
                        % (args.run or args.plan), exit_code=EXIT_ERROR)
    return commit_plan(args, plan)


def cmd_undo(args):
    plan = nc_core.load_plan(args.run)
    if plan is None:
        raise TaskError("E-PLAN-MISSING", "找不到写入计划（run_id）：%s" % args.run,
                        exit_code=EXIT_ERROR)
    if plan.get("status") == "reverted":
        return finish_task(args, plan, "already-reverted",
                           "该计划已撤销过，本次为幂等无操作。")
    if plan.get("status") != "committed":
        raise TaskError("E-PLAN-NOT-COMMITTED",
                        "该计划尚未提交（状态 %s），无需撤销。" % plan.get("status"),
                        run_id=args.run)
    vault = load_vault(plan["vault"])
    target = resolve_vault_target(vault, plan["target"])

    if plan["op"] == "new":
        if not target.exists():
            plan["status"] = "reverted"
            nc_core.save_plan(plan)
            nc_core.append_write_log({"run_id": plan["run_id"], "op": "undo",
                                      "target": plan["target"],
                                      "status": "reverted"})
            return finish_task(args, plan, "already-reverted",
                               "目标文件已不存在，视为已撤销。")
        current = target.read_text(encoding="utf-8")
        if sha256_text(current) != plan["content_hash"]:
            patch_file = write_reverse_patch(plan["run_id"], current, "")
            raise ConflictError(
                "E-CONFLICT-EDITED",
                "撤销中止：新建的笔记在写入后又被修改过，为保护你的修改没有删除。"
                "确认要放弃请手工删除；差异（当前 → 空文件）见反向差异文件。",
                run_id=plan["run_id"],
                detail={"target": str(target), "reverse_patch": str(patch_file)})
        target.unlink()
    else:
        backup = nc_core.backup_path(plan["run_id"])
        if not backup.is_file():
            raise TaskError("E-BACKUP-MISSING",
                            "找不到受控备份，无法安全撤销: %s" % backup,
                            exit_code=EXIT_ERROR, run_id=plan["run_id"])
        backup_text = backup.read_text(encoding="utf-8")
        current = target.read_text(encoding="utf-8")
        if sha256_text(current) != plan["content_hash"]:
            patch_file = write_reverse_patch(plan["run_id"], current, backup_text)
            raise ConflictError(
                "E-CONFLICT-EDITED",
                "撤销中止：写入后笔记又被修改过，直接恢复会覆盖你的修改。"
                "反向差异（当前内容 → 备份版本）已生成，请人工合并后删除该差异文件再撤销。",
                run_id=plan["run_id"],
                detail={"target": str(target), "reverse_patch": str(patch_file)})
        atomic_write_text(target, backup_text)

    plan["status"] = "reverted"
    plan["reverted_at"] = now_iso()
    nc_core.save_plan(plan)
    nc_core.append_write_log({"run_id": plan["run_id"], "op": "undo",
                              "target": plan["target"], "status": "reverted"})
    return finish_task(args, plan, "reverted", "已撤销：%s" % target)


def cmd_log(args):
    entries = nc_core.read_write_log(limit=max(args.last, 1))
    if args.json:
        print(json.dumps({"ok": True, "entries": entries}, ensure_ascii=False,
                         indent=2))
        return EXIT_OK
    for e in entries:
        print("[%s] %s %s %s" % (e.get("at", "?"), e.get("status", "?"),
                                 e.get("op", "?"), e.get("target", "?")))
    if not entries:
        print("（暂无写入记录）")
    return EXIT_OK


def cmd_prune(args):
    cutoffs = {
        nc_core.plans_dir(): args.plans_days,
        nc_core.baselines_dir(): args.baselines_days,
        (nc_core.writes_dir() / "backup"): args.backups_days,
    }
    removed = {}
    now = time.time()
    for directory, days in cutoffs.items():
        if not directory.is_dir():
            continue
        count = 0
        for f in directory.iterdir():
            if not f.is_file():
                continue
            try:
                if now - f.stat().st_mtime > days * 86400:
                    f.unlink()
                    count += 1
            except OSError:
                continue
        removed[directory.name] = count
    message = "已清理：%s" % json.dumps(removed, ensure_ascii=False)
    if args.json:
        print(json.dumps({"ok": True, "removed": removed}, ensure_ascii=False))
    else:
        print(message)
    return EXIT_OK


# ---------- new / merge ----------

def preview_plan(args, plan, op_log=None):
    """向 stderr 输出人读预览；stdout 留给 --json。"""
    line = "-" * 60
    print(line, file=sys.stderr)
    if plan["op"] == "new":
        print("新建预览  目标: %s" % plan["target"], file=sys.stderr)
    else:
        print("合并预览  目标: %s" % plan["target"], file=sys.stderr)
    print("run_id: %s" % plan["run_id"], file=sys.stderr)
    if plan["base_hash"] is not None:
        print("base_hash: %s" % plan["base_hash"][:16], file=sys.stderr)
    print("content_hash: %s" % plan["content_hash"][:16], file=sys.stderr)
    print("来源类型: %s  来源: %s" % (plan["source_type"], plan["source"] or "（无）"),
          file=sys.stderr)
    if op_log is not None:
        effective = sum(1 for t, _, _ in op_log if t.startswith("APPEND") or t == "EDIT")
        print("操作数: %d  有效变更: %d" % (len(op_log), effective), file=sys.stderr)
        for t, desc, frag in op_log:
            marker = "+" if t.startswith("APPEND") else ("~" if t == "EDIT" else "?")
            print("[%s] %s %s" % (t, marker, desc), file=sys.stderr)
            if frag:
                for ln in frag.splitlines():
                    print("    %s %s" % (marker, ln), file=sys.stderr)
    else:
        body_lines = plan["content"].splitlines()
        shown = body_lines[:12]
        for ln in shown:
            print("  | %s" % ln, file=sys.stderr)
        if len(body_lines) > len(shown):
            print("  | …（共 %d 行）" % len(body_lines), file=sys.stderr)
    plan_path = nc_core.plans_dir() / ("%s.json" % plan["run_id"])
    print(line, file=sys.stderr)
    print("[PLAN] %s" % plan_path, file=sys.stderr)
    print("[未写入] 这是预览。确认后加 --apply 写入；或事后用 apply --run %s 提交。"
          % plan["run_id"], file=sys.stderr)
    return plan_path


def cmd_new(args):
    vault = load_vault(args.vault)
    content = Path(args.file).read_text(encoding="utf-8")
    rel = "%s/%s" % (args.dir.strip("/"), safe_filename(args.title))
    target = resolve_vault_target(vault, rel)
    check_case_collision(target)
    if target.exists():
        current = target.read_text(encoding="utf-8")
        if sha256_text(current) == sha256_text(content):
            emit(args, {"ok": True, "run_id": None, "op": "new",
                        "status": "already-exists-same-content",
                        "target": rel,
                        "message": "目标已存在且内容一致，未重复写入。"})
            print("[SKIP] 目标已存在且内容一致，未重复写入：%s" % target, file=sys.stderr)
            return EXIT_OK
        raise TaskError("E-TARGET-EXISTS",
                        "目标文件已存在：%s（不覆盖已有内容；若要合并请用 merge 模式）"
                        % target)
    plan = build_plan(vault, "new", rel, None, content, args.source, args.source_type)
    nc_core.save_plan(plan)
    preview_plan(args, plan)
    if args.apply:
        return commit_plan(args, plan)
    return finish_task(args, plan, "previewed", "预览已生成，未写盘。")


def cmd_merge(args):
    vault = load_vault(args.vault)
    target = resolve_vault_target(vault, args.target)
    if not target.exists():
        raise TaskError("E-TARGET-MISSING", "目标旧笔记不存在：%s" % target)
    old = target.read_text(encoding="utf-8")
    patch_text = Path(args.patch).read_text(encoding="utf-8")
    source, ops = parse_patch(patch_text)

    fm_block, body = split_target(old)
    new_body, op_log = apply_ops(body, ops)
    has_change = any(t.startswith("APPEND") or t == "EDIT" for t, _, _ in op_log)

    # 三字段铁律：合并一律不动 frontmatter；来源留痕追加到正文文末
    new_text = fm_block + new_body
    if has_change and source:
        foot = source_footnote(source)
        if not _normalized_contains(new_text, foot):
            new_text = new_text.rstrip() + "\n\n" + foot

    if not has_change:
        emit(args, {"ok": True, "run_id": None, "op": "merge",
                    "status": "no-change", "target": args.target,
                    "message": "没有需要写入的内容（可能全部重复或未命中）。"})
        print("[无变更] 没有需要写入的内容（可能全部重复或未命中）。", file=sys.stderr)
        return EXIT_OK

    plan = build_plan(vault, "merge", args.target.replace("\\", "/"), old,
                      new_text, source, args.source_type)
    nc_core.save_plan(plan)
    preview_plan(args, plan, op_log=op_log)
    if args.apply:
        return commit_plan(args, plan)
    return finish_task(args, plan, "previewed", "预览已生成，未写盘。")


def main():
    ap = argparse.ArgumentParser(
        description="把笔记写入 vault（新建/合并；统一预览→应用→撤销事务）。")
    sub = ap.add_subparsers(dest="mode", required=True)

    p_new = sub.add_parser("new", help="新建笔记（默认仅预览，--apply 写盘）")
    p_new.add_argument("--vault", required=True)
    p_new.add_argument("--dir", required=True, help="vault 内相对目录")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--file", required=True, help="笔记内容文件路径")
    p_new.add_argument("--apply", action="store_true", help="预览后直接提交写入")
    p_new.add_argument("--source-type", choices=SOURCE_TYPES, default="generated",
                       help="来源类型（写入生成基线；默认 generated）")
    p_new.add_argument("--source", default="", help="来源描述（URL 或说明），写入基线")
    p_new.add_argument("--json", action="store_true", help="stdout 输出结构化结果")

    p_mg = sub.add_parser("merge", help="合并到旧笔记（默认仅预览，--apply 写盘）")
    p_mg.add_argument("--vault", required=True)
    p_mg.add_argument("--target", required=True, help="旧笔记相对 vault 的路径")
    p_mg.add_argument("--patch", required=True, help="patch 文件（含 APPEND/EDIT 操作）")
    p_mg.add_argument("--apply", action="store_true", help="预览后直接提交写入")
    p_mg.add_argument("--source-type", choices=SOURCE_TYPES, default="generated",
                      help="来源类型（写入生成基线；默认 generated）")
    p_mg.add_argument("--json", action="store_true", help="stdout 输出结构化结果")

    p_ap = sub.add_parser("apply", help="提交一份已生成的写入计划")
    p_ap.add_argument("--run", help="run_id")
    p_ap.add_argument("--plan", help="计划文件路径（与 --run 二选一）")
    p_ap.add_argument("--json", action="store_true", help="stdout 输出结构化结果")

    p_undo = sub.add_parser("undo", help="撤销一次已提交的写入")
    p_undo.add_argument("--run", required=True, help="run_id")
    p_undo.add_argument("--json", action="store_true", help="stdout 输出结构化结果")

    p_log = sub.add_parser("log", help="查看最近写入记录")
    p_log.add_argument("--last", type=int, default=20, help="显示最近 N 条")
    p_log.add_argument("--json", action="store_true", help="stdout 输出 JSON")

    p_prune = sub.add_parser("prune", help="按保留期限清理计划/基线/备份")
    p_prune.add_argument("--plans-days", type=int, default=90)
    p_prune.add_argument("--baselines-days", type=int, default=90)
    p_prune.add_argument("--backups-days", type=int, default=30)
    p_prune.add_argument("--json", action="store_true", help="stdout 输出 JSON")

    args = ap.parse_args()
    handlers = {"new": cmd_new, "merge": cmd_merge, "apply": cmd_apply,
                "undo": cmd_undo, "log": cmd_log, "prune": cmd_prune}
    try:
        sys.exit(handlers[args.mode](args))
    except TaskError as exc:
        payload = {"ok": False, "error": {"code": exc.code,
                                          "message": exc.message}}
        if exc.run_id:
            payload["run_id"] = exc.run_id
        if getattr(exc, "detail", None):
            payload["error"]["detail"] = exc.detail
        if getattr(args, "json", False):
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        print("[ERROR] %s" % exc.message, file=sys.stderr)
        sys.exit(exc.exit_code)
    except ValueError as exc:
        # 路径安全校验（nc_core.resolve_vault_target / check_case_collision）
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "E-PATH",
                                                     "message": str(exc)}},
                             ensure_ascii=False, indent=2))
        print("[ERROR] %s" % exc, file=sys.stderr)
        sys.exit(EXIT_REJECTED)
    except OSError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"ok": False, "error": {"code": "E-IO",
                                                     "message": str(exc)}},
                             ensure_ascii=False, indent=2))
        print("[ERROR] 文件读写失败：%s" % exc, file=sys.stderr)
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
