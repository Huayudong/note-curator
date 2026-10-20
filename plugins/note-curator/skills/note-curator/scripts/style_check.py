#!/usr/bin/env python3
"""
style_check.py — 把草稿和文风画像做确定性对比，指出明显的风格偏差。

用法：
    python style_check.py _note.md --profile ~/.note-curator/style-profiles/<name>/profile.json
    python style_check.py _note.md --profile ... --json
    python style_check.py _note.md --profile ... --strict   # 有 major 偏差时退出码 1

它只检查可量化特征（句长、标点、人称、语气词、连接词、修辞、排版等），
不判断内容是否正确，也不替代 voice.md 里的定性描述。
"""

import argparse
import json
import sys
import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具
from pathlib import Path

from style_metrics import analyze_text, compare_profiles, LABELS


def fmt(value):
    if isinstance(value, float):
        return ("%.2f" % value).rstrip("0").rstrip(".")
    return str(value)


def main():
    ap = argparse.ArgumentParser(description="检查草稿与文风画像的偏差")
    ap.add_argument("draft", help="草稿文件路径")
    ap.add_argument("--profile", required=True, help="profile.json 路径")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--strict", action="store_true", help="存在 major 偏差时退出码 1")
    ap.add_argument("--max-findings", type=int, default=20, help="最多显示多少条，默认 20")
    args = ap.parse_args()

    draft_path = Path(args.draft).expanduser()
    if not draft_path.is_file():
        raise SystemExit("[ERROR] 草稿不存在: %s" % draft_path)
    profile_path = Path(args.profile).expanduser()
    if not profile_path.is_file():
        raise SystemExit("[ERROR] 画像不存在: %s" % profile_path)

    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit("[ERROR] 无法读取画像 JSON: %s" % exc)

    if "metrics" not in profile:
        raise SystemExit("[ERROR] 画像文件缺少 metrics 字段，请重新运行 style_profile.py")

    draft_text = draft_path.read_text(encoding="utf-8", errors="ignore")
    draft_metrics = analyze_text(draft_text)
    result = compare_profiles(profile, draft_metrics)
    result["draft"] = str(draft_path)
    result["profile"] = str(profile_path)
    result["draft_language"] = draft_metrics.get("language")
    result["profile_language"] = profile.get("language", "zh")

    labels = LABELS[result["profile_language"]]
    is_en = result["profile_language"] == "en"
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        counts = result["counts"]
        print("# %s" % ("Style check" if is_en else "文风检查"))
        print("")
        print("%s: profile=%s, draft=%s" % ("language" if is_en else "语言",
                                            result["profile_language"],
                                            result["draft_language"]))
        print("")
        print("%s%s%s（major %d / minor %d / info %d）"
              % ("Verdict" if is_en else "结论", ": " if is_en else "：",
                 result["verdict"], counts["major"], counts["minor"], counts["info"]))
        print("")
        findings = result["findings"][:args.max_findings]
        if not findings:
            print("No significant statistical deviation found." if is_en
                  else "没有发现明显的统计偏差。")
            print("")
        else:
            major = [item for item in findings if item["severity"] == "major"]
            other = [item for item in findings if item["severity"] != "major"]
            if major:
                print("## %s" % ("Fix first" if is_en else "优先调整"))
                for item in major:
                    print("- [major] %s: %s" % (item["category"], item["message"]))
                print("")
            if other:
                print("## %s" % ("Other notes" if is_en else "其他提示"))
                for item in other:
                    print("- [%s] %s: %s" % (item["severity"], item["category"], item["message"]))
                print("")
        print("> %s" % (
            "Statistical check only; whether the tone truly matches still depends on voice.md."
            if is_en else
            "这是统计检查，只覆盖可量化特征；语气是否贴近本人，还要结合 voice.md 判断。"))

    if args.strict and result["counts"]["major"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
