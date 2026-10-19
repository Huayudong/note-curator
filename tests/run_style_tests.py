#!/usr/bin/env python3
"""
run_style_tests.py — note-curator 文风语言包的端到端测试。

覆盖：
  1. 语言检测（zh / en / 中英混合）
  2. 中文画像回归：示例笔记自检应「基本一致」
  3. 英文画像：fixtures 建立 profile，语言应为 en，自检应通过
  4. 英文劣质草稿（碎句）应判「明显偏差」且 --strict 退出码 1
  5. 语言不匹配（英文草稿 vs 中文画像）应给出 mismatch 结论

用法：python tests/run_style_tests.py（仓库根目录或任意位置均可）
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator"
SCRIPTS = SKILL / "scripts"
ZH_EXAMPLE = SKILL / "examples" / "example-knowledge-note.md"
EN_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "en"

FAILURES = []


def run(args, **kwargs):
    return subprocess.run([sys.executable] + [str(a) for a in args],
                          capture_output=True, text=True, encoding="utf-8", **kwargs)


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, name, (" — %s" % detail) if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


def main():
    sys.path.insert(0, str(SCRIPTS))
    import langdetect
    import style_metrics

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # --- 1. 语言检测 ---
        check("detect zh", langdetect.detect_language(ZH_EXAMPLE.read_text(encoding="utf-8")) == "zh")
        en_text = (EN_FIXTURES / "cache-invalidation.md").read_text(encoding="utf-8")
        check("detect en", langdetect.detect_language(en_text) == "en")
        mixed = "这个方案的 trade-off 很明显：latency 降了，成本升了。" * 3
        check("detect mixed zh", langdetect.detect_language(mixed) == "zh")

        # --- 2. 中文回归 ---
        zh_dir = tmp / "zh"
        r = run([SCRIPTS / "style_profile.py", "--vault", SKILL,
                 "--files", "examples/example-knowledge-note.md",
                 "--profile-dir", zh_dir, "--name", "zh-test"])
        check("zh profile exit 0", r.returncode == 0, r.stderr[-300:])
        zh_profile = zh_dir / "zh-test" / "profile.json"
        zh_data = json.loads(zh_profile.read_text(encoding="utf-8"))
        check("zh profile detected zh", zh_data.get("language") == "zh",
              "got %s" % zh_data.get("language"))

        r = run([SCRIPTS / "style_check.py", ZH_EXAMPLE, "--profile", zh_profile, "--strict"])
        check("zh self check consistent", "基本一致" in r.stdout and r.returncode == 0,
              r.stdout[-300:])

        # --- 3. 英文画像 ---
        en_dir = tmp / "en"
        r = run([SCRIPTS / "style_profile.py", "--vault", EN_FIXTURES.parent,
                 "--dir", "en", "--profile-dir", en_dir, "--name", "en-test"])
        check("en profile exit 0", r.returncode == 0, r.stderr[-300:])
        en_profile = en_dir / "en-test" / "profile.json"
        en_data = json.loads(en_profile.read_text(encoding="utf-8"))
        check("en profile language", en_data.get("language") == "en",
              "got %s" % en_data.get("language"))
        check("en profile unit", en_data.get("unit") == "words",
              "got %s" % en_data.get("unit"))
        sl = en_data["metrics"]["sentence_length"]
        check("en sentence length sane", 5 <= sl["mean"] <= 60,
              "mean=%s" % sl["mean"])
        voice = en_dir / "en-test" / "voice.md"
        check("en voice template", "Voice profile" in voice.read_text(encoding="utf-8"))

        # 单篇画像自检（混合语料里另一篇的表格/行内代码会把单篇自检带偏，
        # 这是小语料的已知局限，写进了 references/style-profiling.md）
        single_dir = tmp / "en-single"
        r = run([SCRIPTS / "style_profile.py", "--vault", EN_FIXTURES.parent,
                 "--files", "en/cache-invalidation.md",
                 "--profile-dir", single_dir, "--name", "en-single"])
        check("en single profile exit 0", r.returncode == 0, r.stderr[-300:])
        r = run([SCRIPTS / "style_check.py", EN_FIXTURES / "cache-invalidation.md",
                 "--profile", single_dir / "en-single" / "profile.json", "--strict"])
        check("en self check consistent", "consistent" in r.stdout and r.returncode == 0,
              r.stdout[-400:])

        # --- 4. 英文劣质草稿 ---
        bad = tmp / "bad-en.md"
        bad.write_text(
            "# Bad draft\n\n"
            "Cache is fast. Cache fails. Add a lock. Limit the traffic. "
            "Delete the key. Retry once. Done. Ship it.\n", encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", bad, "--profile", en_profile, "--strict"])
        check("bad en draft flagged", "major deviation" in r.stdout and r.returncode == 1,
              "returncode=%s stdout=%s" % (r.returncode, r.stdout[-400:]))

        # --- 5. 语言不匹配 ---
        r = run([SCRIPTS / "style_check.py", EN_FIXTURES / "cache-invalidation.md",
                 "--profile", zh_profile, "--strict"])
        check("mismatch reported", "语言不一致" in r.stdout and r.returncode == 1,
              r.stdout[-300:])

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All style language-pack tests passed.")


if __name__ == "__main__":
    main()
