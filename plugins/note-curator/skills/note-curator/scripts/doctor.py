#!/usr/bin/env python3
"""
doctor.py — B11-10 健康诊断与维护：版本 / 占用 / 状态审计 / 清理。

输出（默认脱敏：用户目录显示为 ~，不包含任何笔记内容或草稿正文）：
    versions   核心写入者版本、Python 版本
    packs      中英文语言包版本与警告数（B11-09 兼容信息）
    storage    数据目录各子目录的文件数与字节数
    state      状态审计：plans/ 基线/ 登记表的 schema 兼容情况
    locks      活动锁文件（含 pid 与写入者版本）
    recent     最近写入记录（仅时间/状态/目标，无内容）

用法：
    python doctor.py [--json] [--clean]
    --clean 按保留期限清理（与 write_note prune 相同默认：计划/基线 90
    天、备份 30 天），并报告清理数量。

退出码：0 正常；1 发现需要用户处理的问题（schema 超版本、语言包不可用）。
"""

import argparse
import json
import sys
import time
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from nc_core import (data_root, storage_usage, schema_of, SCHEMA_MAX,
                     WRITER_VERSION, locks_dir)


def sanitize_path(path):
    home = str(Path.home())
    text = str(path)
    return text.replace(home, "~") if text.startswith(home) else text


def audit_states(root):
    """扫描 plans/baselines 的 schema；登记表做键值完整性检查。"""
    audit = {"plans_total": 0, "plans_schema_bad": 0, "baselines_total": 0,
             "baselines_schema_bad": 0, "sources_registry": "missing",
             "registry": "missing"}
    plans = root / "plans"
    if plans.is_dir():
        for f in plans.glob("*.json"):
            audit["plans_total"] += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                value = schema_of(data)
                if value is None or value > SCHEMA_MAX["plan"]:
                    audit["plans_schema_bad"] += 1
            except (OSError, ValueError):
                audit["plans_schema_bad"] += 1
    baselines = root / "baselines"
    if baselines.is_dir():
        for f in baselines.glob("*.json"):
            audit["baselines_total"] += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                value = schema_of(data)
                if value is None or value > SCHEMA_MAX["baseline"]:
                    audit["baselines_schema_bad"] += 1
            except (OSError, ValueError):
                audit["baselines_schema_bad"] += 1
    sources = root / "sources.json"
    if sources.is_file():
        try:
            json.loads(sources.read_text(encoding="utf-8"))
            audit["sources_registry"] = "ok"
        except (OSError, ValueError):
            audit["sources_registry"] = "corrupt"
    registry = root / "registry.json"
    if registry.is_file():
        try:
            json.loads(registry.read_text(encoding="utf-8"))
            audit["registry"] = "ok"
        except (OSError, ValueError):
            audit["registry"] = "corrupt"
    return audit


def clean(root, dry=False):
    """与 write_note prune 相同的保留期限默认值。"""
    cutoffs = {root / "plans": 90, root / "baselines": 90,
               root / "writes" / "backup": 30}
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
                    if not dry:
                        os_remove(f)
                    count += 1
            except OSError:
                continue
        removed[sanitize_path(directory)] = count
    return removed


def os_remove(path):
    import os
    os.remove(str(path))


def main():
    ap = argparse.ArgumentParser(description="健康诊断与维护")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--clean", action="store_true",
                    help="按保留期限清理计划/基线/备份")
    args = ap.parse_args()

    root = data_root()
    problems = []

    packs = []
    for lang in ("zh", "en"):
        try:
            from resource_pack import load_pack
            pack, warnings = load_pack(lang)
            packs.append({"language": lang,
                          "version": (pack or {}).get("pack_version"),
                          "rules": len((pack or {}).get("rules", [])),
                          "warnings": warnings})
            if pack is None:
                problems.append("语言包不可用：%s" % lang)
        except Exception as exc:
            packs.append({"language": lang, "version": None,
                          "error": str(exc)[:120]})
            problems.append("语言包加载异常：%s" % lang)

    state = audit_states(root)
    if state["plans_schema_bad"] or state["baselines_schema_bad"]:
        problems.append("存在超出当前版本可识别 schema 的状态文件（可能由"
                        "更新版本的写入者创建）；请升级或删除后重建。")

    locks = []
    if locks_dir().is_dir():
        for f in locks_dir().glob("*.lock"):
            try:
                info = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                info = {}
            locks.append({"file": sanitize_path(f), "pid": info.get("pid"),
                          "writer": info.get("writer")})

    recent = []
    try:
        from nc_core import read_write_log
        for e in read_write_log(limit=5):
            recent.append({"at": e.get("at"), "status": e.get("status"),
                           "op": e.get("op"), "target": sanitize_path(e.get("target", ""))})
    except (OSError, ValueError):
        pass

    report = {
        "versions": {"core_writer": WRITER_VERSION,
                     "python": sys.version.split()[0]},
        "packs": packs,
        "storage": storage_usage(),
        "state": state,
        "locks": locks,
        "recent_writes": recent,
        "problems": problems,
        "ok": not problems,
    }
    removed = None
    if args.clean:
        removed = clean(root)
        report["cleaned"] = removed

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("note-curator doctor（core %s，python %s）"
              % (WRITER_VERSION, sys.version.split()[0]))
        for p in packs:
            print("  语言包 %s：v%s（%d 条规则，警告 %d）"
                  % (p["language"], p.get("version"), p.get("rules", 0),
                     len(p.get("warnings", []))))
        for name, stat in report["storage"].items():
            print("  存储 %s：%d 文件，%.1f KB" % (name, stat["files"],
                                                 stat["bytes"] / 1024))
        print("  状态：plans %d（异常 %d），baselines %d（异常 %d），"
              "sources=%s，registry=%s"
              % (state["plans_total"], state["plans_schema_bad"],
                 state["baselines_total"], state["baselines_schema_bad"],
                 state["sources_registry"], state["registry"]))
        if removed:
            print("  清理：", json.dumps(removed, ensure_ascii=False))
        for problem in problems:
            print("  [问题] %s" % problem)
        if not problems:
            print("  [OK] 未发现需要处理的问题。")
    sys.exit(0 if not problems else 1)


if __name__ == "__main__":
    main()
