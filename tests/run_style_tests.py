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
ZH_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "zh" / "git-rebase.md"

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

        # --- 6. 中文深化特征 ---
        zh2_dir = tmp / "zh2"
        r = run([SCRIPTS / "style_profile.py", "--vault", ZH_FIXTURE.parent.parent,
                 "--files", "zh/git-rebase.md", "--profile-dir", zh2_dir, "--name", "zh2"])
        check("zh deep profile exit 0", r.returncode == 0, r.stderr[-300:])
        zh2_profile = zh2_dir / "zh2" / "profile.json"
        zh2 = json.loads(zh2_profile.read_text(encoding="utf-8"))
        m = zh2["metrics"]
        check("zh constructions counted",
              m["zh_constructions"]["把字句"]["count"] >= 3
              and m["zh_constructions"]["被动式"]["count"] >= 1,
              str(m["zh_constructions"]))
        check("zh four-char counted", m["zh_four_char"]["count"] >= 3,
              str(m["zh_four_char"]))
        check("zh colloquial counted",
              sum(v["count"] for v in m["zh_colloquial"].values()) >= 3,
              str(m["zh_colloquial"]))
        check("zh punctuation dunhao", m["punctuation"]["顿号"]["count"] >= 1,
              str(m["punctuation"].get("顿号")))
        check("zh latin mixing", m["latin_per_1000"] >= 5,
              str(m["latin_per_1000"]))
        check("zh profile ai-tell free",
              sum(v["count"] for v in m["ai_tells"].values()) == 0,
              str(m["ai_tells"]))

        r = run([SCRIPTS / "style_check.py", ZH_FIXTURE, "--profile", zh2_profile,
                 "--strict"])
        check("zh deep self check consistent", "基本一致" in r.stdout and r.returncode == 0,
              r.stdout[-300:])

        ai_draft = tmp / "ai-draft.md"
        ai_draft.write_text(
            "# AI 腔草稿\n\n"
            "值得注意的是，缓存策略的选择至关重要。综上所述，我们应该把缓存、限流、降级结合起来。"
            "不难发现，这并不是一个技术问题，而是一个认知问题。由此可见，赋能业务的底层逻辑在于"
            "深度融合。总而言之，这套方案能够极大地提升系统性能。首先，我们把数据放进缓存。"
            "其次，我们设置过期时间。以上就是全部内容。\n", encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", ai_draft, "--profile", zh2_profile,
                 "--strict"])
        check("ai-tell draft flagged", "明显偏差" in r.stdout and r.returncode == 1
              and "AI 腔" in r.stdout, r.stdout[-500:])

        # --- 7. 双语写作资源完整性 ---
        refs = SKILL / "references"
        zh_guide = (refs / "writing-style.md").read_text(encoding="utf-8")
        en_guide = (refs / "writing-style.en.md").read_text(encoding="utf-8")
        zh_tpl = (refs / "templates.md").read_text(encoding="utf-8")
        en_tpl = (refs / "templates.en.md").read_text(encoding="utf-8")
        check("zh guide has blacklist", "AI 腔黑名单" in zh_guide)
        check("en guide has blacklist", "AI-tell blacklist" in en_guide)
        check("en guide native tells", "not just X" in en_guide and "reveal dash" in en_guide.lower()
              or "Reveal dash" in en_guide)
        check("en guide marks extension", "Curator's extension" in en_guide)
        check("zh templates knowledge+experiment", "知识类模板" in zh_tpl and "实验类模板" in zh_tpl)
        check("en templates knowledge+experiment",
              "Knowledge template" in en_tpl and "Experiment template" in en_tpl)
        check("en templates marks extension", "Curator's extension" in en_tpl)
        skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        check("SKILL routes by language",
              "writing-style.en.md" in skill_md and "templates.en.md" in skill_md
              and "不翻译" in skill_md)

        # --- 5. 语言不匹配 ---
        r = run([SCRIPTS / "style_check.py", EN_FIXTURES / "cache-invalidation.md",
                 "--profile", zh_profile, "--strict"])
        check("mismatch reported", "语言不一致" in r.stdout and r.returncode == 1,
              r.stdout[-300:])

        # --- 8. 持续学习（style_learn）---
        import shutil
        learn_vault = tmp / "learn-vault"
        learn_vault.mkdir()
        shutil.copy(ZH_FIXTURE, learn_vault / "note-a.md")
        shutil.copy(ZH_EXAMPLE, learn_vault / "note-b.md")
        lp_dir = tmp / "learn-profile"
        r = run([SCRIPTS / "style_profile.py", "--vault", learn_vault,
                 "--files", "note-a.md", "--profile-dir", lp_dir, "--name", "learn"])
        check("learn base profile exit 0", r.returncode == 0, r.stderr[-300:])
        lp = lp_dir / "learn" / "profile.json"

        r = run([SCRIPTS / "style_learn.py", "--profile", lp, "--note", "note-b.md"])
        check("learn note accepted", r.returncode == 0 and "已学习 1 篇" in r.stdout,
              "rc=%s %s%s" % (r.returncode, r.stdout[-200:], r.stderr[-200:]))
        data = json.loads(lp.read_text(encoding="utf-8"))
        check("learn corpus grew", data["corpus"]["file_count"] == 2,
              str(data["corpus"]))
        check("learn history kept", len(data.get("history", [])) == 1
              and data.get("learned_count") == 1, str(data.get("history")))
        check("learn keeps language", data.get("language") == "zh")

        r = run([SCRIPTS / "style_learn.py", "--profile", lp, "--note", "note-b.md"])
        check("learn duplicate rejected", r.returncode == 2, "rc=%s" % r.returncode)
        data2 = json.loads(lp.read_text(encoding="utf-8"))
        check("learn duplicate no change", data2["corpus"]["file_count"] == 2
              and data2.get("learned_count") == 1)

        r = run([SCRIPTS / "style_learn.py", "--profile", lp,
                 "--note", EN_FIXTURES / "cache-invalidation.md"])
        check("learn cross-language rejected", r.returncode == 2, "rc=%s" % r.returncode)
        data3 = json.loads(lp.read_text(encoding="utf-8"))
        check("learn cross-language no change", data3["corpus"]["file_count"] == 2)

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All style language-pack tests passed.")


if __name__ == "__main__":
    main()
