#!/usr/bin/env python3
"""
migrate_profiles.py — 旧画像迁移到 B02 命名空间（B02-08）。

旧画像按目录名存放，未隔离 vault 与语言（G03）。本工具做只读预检，
生成迁移计划；--apply 后把 profile.json / profile.md / voice.md 复制到
带语言后缀的新目录并注入 profile_key（user + vault_id + language +
register + scope）。**旧目录原样保留**：迁移失败删除新目录即可回退。

用法：
    python migrate_profiles.py                     # 预览迁移计划（不写入）
    python migrate_profiles.py --apply             # 执行迁移
    python migrate_profiles.py --relink "D:/旧路径" "E:/新路径"
                                                   # vault 搬家后重新关联 vault_id

退出码：0 有计划或完成；1 参数错误；2 无可迁移画像。
"""

import argparse
import datetime
import json
import shutil
import sys
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from nc_core import data_root, vault_id_for, vault_registry_path

DEFAULT_PROFILE_DIR = Path.home() / ".note-curator" / "style-profiles"


def scan_old_profiles(root):
    """返回待迁移画像清单（缺 profile_key 且未迁移过的才出计划）。"""
    plans = []
    if not root.is_dir():
        return plans
    # 已迁移识别：migrated_from 指回旧目录名且 vault_id 一致（B02-08）
    migrated = set()
    for entry in sorted(root.iterdir()):
        pf = entry / "profile.json"
        if not entry.is_dir() or not pf.is_file():
            continue
        try:
            keyed = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = keyed.get("profile_key")
        if key and keyed.get("migrated_from"):
            migrated.add((keyed["migrated_from"], key.get("vault_id", "")))
    for entry in sorted(root.iterdir()):
        pf = entry / "profile.json"
        if not entry.is_dir() or not pf.is_file():
            continue
        try:
            profile = json.loads(pf.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            plans.append({"from": entry.name, "status": "unreadable",
                          "reason": str(exc)})
            continue
        if profile.get("profile_key"):
            plans.append({"from": entry.name, "status": "already-keyed"})
            continue
        vault = profile.get("source", {}).get("vault", "")
        language = profile.get("language", "zh")
        vid = vault_id_for(vault) if vault else ""
        if (entry.name, vid) in migrated:
            plans.append({"from": entry.name, "status": "migrated",
                          "to": "", "language": language})
            continue
        proposed = "%s-%s" % (entry.name, language)
        target = root / proposed
        if target.exists():
            proposed = "%s-%s-%s" % (entry.name, vid[:4] or "vault", language)
        plans.append({
            "from": entry.name,
            "to": proposed,
            "status": "planned",
            "language": language,
            "vault": vault,
            "vault_id": vid,
        })
    return plans


def apply_plans(root, plans):
    done = []
    for plan in plans:
        if plan.get("status") != "planned":
            continue
        src = root / plan["from"]
        dst = root / plan["to"]
        if dst.exists():
            plan["status"] = "collision"
            continue
        dst.mkdir(parents=True)
        try:
            profile = json.loads((src / "profile.json").read_text(encoding="utf-8"))
            profile["profile_key"] = {
                "user_id": "local",
                "vault_id": plan.get("vault_id") or (vault_id_for(plan["vault"])
                                                     if plan.get("vault") else ""),
                "language": plan["language"],
                "register": "default",
                "scope": "migrated",
                "name": plan["to"],
            }
            profile["migrated_from"] = plan["from"]
            profile["migrated_at"] = datetime.datetime.now().isoformat(timespec="seconds")
            (dst / "profile.json").write_text(
                json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
            for name in ("profile.md", "voice.md"):
                if (src / name).is_file():
                    shutil.copy2(src / name, dst / name)
        except (OSError, ValueError) as exc:
            # 回退：删掉半成品新目录，旧目录从未动过
            shutil.rmtree(dst, ignore_errors=True)
            plan["status"] = "failed"
            plan["reason"] = str(exc)
            continue
        plan["status"] = "done"
        done.append(plan)
    return done


def relink(old_path, new_path):
    """vault 搬家：把旧路径登记的 vault_id 关联到新路径。"""
    registry_path = vault_registry_path()
    registry = {"vaults": {}}
    if registry_path.is_file():
        try:
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            registry = {"vaults": {}}
    vaults = registry.setdefault("vaults", {})
    import os
    old_key = os.path.normcase(os.path.normpath(old_path))
    new_key = os.path.normcase(os.path.normpath(new_path))
    vid = vaults.get(old_key)
    if not vid:
        print("[WARN] 登记表里没有旧路径：%s" % old_key, file=sys.stderr)
        return 1
    vaults[new_key] = vid
    nc_core.atomic_write_text(registry_path,
                              json.dumps(registry, ensure_ascii=False, indent=2))
    print("[OK] 已把 vault_id %s 关联到 %s（旧映射保留）" % (vid, new_key))
    return 0


def main():
    ap = argparse.ArgumentParser(description="旧画像迁移到 B02 命名空间")
    ap.add_argument("--profile-dir", help="画像根目录；默认 ~/.note-curator/style-profiles")
    ap.add_argument("--apply", action="store_true", help="执行迁移（默认只预览）")
    ap.add_argument("--relink", nargs=2, metavar=("OLD", "NEW"),
                    help="vault 搬家后把旧路径的 vault_id 关联到新路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON 计划")
    args = ap.parse_args()

    if args.relink:
        sys.exit(relink(args.relink[0], args.relink[1]))

    root = Path(args.profile_dir).expanduser() if args.profile_dir else DEFAULT_PROFILE_DIR
    plans = scan_old_profiles(root)
    pending = [p for p in plans if p.get("status") == "planned"]
    if args.apply and pending:
        apply_plans(root, plans)
    elif args.apply and not pending:
        print("[INFO] 没有待迁移的画像。", file=sys.stderr)

    if args.json:
        print(json.dumps({"ok": True, "profile_root": str(root), "plans": plans},
                         ensure_ascii=False, indent=2))
    else:
        for plan in plans:
            if plan["status"] == "planned":
                print("[PLAN] %s -> %s（language: %s）"
                      % (plan["from"], plan["to"], plan.get("language")))
            elif plan["status"] == "done":
                print("[DONE] %s -> %s" % (plan["from"], plan["to"]))
            elif plan["status"] == "already-keyed":
                print("[KEEP] %s（已是复合键画像）" % plan["from"])
            elif plan["status"] == "migrated":
                print("[DONE] %s（此前已迁移）" % plan["from"])
            elif plan["status"] == "failed":
                print("[FAIL] %s：%s" % (plan["from"], plan.get("reason")))
            else:
                print("[%s] %s" % (plan["status"].upper(), plan["from"]))
        if pending and not args.apply:
            print("[NEXT] 确认无误后加 --apply 执行；旧目录保留，删除新目录即可回退。")
        elif not plans:
            print("[INFO] 画像目录不存在或为空：%s" % root)
    sys.exit(0 if plans else 2)


if __name__ == "__main__":
    main()
