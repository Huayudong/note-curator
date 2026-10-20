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

        # --- 9. 英文查重 + 语言过滤 + 界面文案 ---
        import shutil as _shutil
        dedup_vault = tmp / "dedup-vault"
        dedup_vault.mkdir()
        for src in (EN_FIXTURES.glob("*.md")):
            _shutil.copy(src, dedup_vault / src.name)
        _shutil.copy(ZH_FIXTURE, dedup_vault / "zh-note.md")
        r = run([SCRIPTS / "scan_vault.py", "--vault", dedup_vault,
                 "--out", tmp / "dedup-index.json"])
        check("scan exit 0", r.returncode == 0, r.stderr[-200:])
        idx = json.loads((tmp / "dedup-index.json").read_text(encoding="utf-8"))
        langs = {n["path"]: n.get("language") for n in idx}
        check("index records language",
              langs.get("cache-invalidation.md") == "en" and langs.get("zh-note.md") == "zh",
              str(langs))

        r = run([SCRIPTS / "find_duplicates.py", "--index", tmp / "dedup-index.json",
                 "--query", "caching strategies and invalidation with ttl jitter"])
        hits = json.loads(r.stdout)
        check("en dedup finds en note", hits and hits[0]["path"] == "cache-invalidation.md",
              r.stdout[:300])

        r = run([SCRIPTS / "find_duplicates.py", "--index", tmp / "dedup-index.json",
                 "--query", "caching strategies and invalidation with ttl jitter",
                 "--lang", "zh"])
        hits_zh = json.loads(r.stdout)
        check("lang filter excludes en", all(h["path"] != "cache-invalidation.md" for h in hits_zh),
              r.stdout[:200])

        r = run([SCRIPTS / "find_duplicates.py", "--index", tmp / "dedup-index.json",
                 "--query", "缓存 失效 策略"])
        hits2 = json.loads(r.stdout)
        check("zh query auto-filters to zh", all(h.get("language") != "en" for h in hits2),
              r.stdout[:200])

        # 界面文案（--config 指向临时路径，与本机真实配置隔离，B01-01）
        r = run([SCRIPTS / "check_setup.py", "--lang", "en", "--json",
                 "--config", tmp / "no-such-config.yaml"])
        check("check_setup en messages", "No note-curator configuration" in r.stdout,
              r.stdout[:200])
        r = run([SCRIPTS / "init_setup.py", "--vault", tmp / "v-en", "--author", "T",
                 "--config", tmp / "cfg-en.yaml", "--lang", "en"])
        check("init_setup en messages", "[OK] Generated" in r.stdout and "Next:" in r.stdout,
              r.stdout[:300])

        # --- 10. B01：配置 schema 校验（safe_yaml）---
        (tmp / "v-en").mkdir(exist_ok=True)
        cfg_b01 = tmp / "cfg-b01.yaml"
        cfg_b01.write_text(
            'vault_path: "%s"\n'
            "frontmatter:\n"
            '  author: "T"\n'
            "some_unknown_key: 1\n" % (tmp / "v-en").as_posix(),
            encoding="utf-8")
        r = run([SCRIPTS / "check_setup.py", "--json", "--config", cfg_b01])
        data = json.loads(r.stdout)
        check("check_setup ok with valid config",
              data.get("status") == "ok" and data.get("ok") is True, r.stdout[:300])
        check("check_setup reports unknown fields",
              data.get("unknown_fields") == ["some_unknown_key"], r.stdout[:300])

        # --- 11. B02: bilingual profile isolation, forced-language filter, migration ---
        import shutil as _shutil2

        iso_root = tmp / "iso-profiles"
        for tag in ("v1", "v2"):
            iso_vault = tmp / ("iso-" + tag)
            (iso_vault / "diary").mkdir(parents=True)
            _shutil2.copy(ZH_FIXTURE, iso_vault / "diary" / "note.md")
            r = run([SCRIPTS / "style_profile.py", "--vault", str(iso_vault),
                     "--dir", "diary", "--profile-dir", str(iso_root)])
            check("b02 iso profile %s" % tag, r.returncode == 0, r.stderr[-300:])
        iso_dirs = sorted(d.name for d in iso_root.iterdir())
        check("b02 two isolated profiles", len(iso_dirs) == 2, str(iso_dirs))
        check("b02 lang suffix naming",
              all(name.endswith("-zh") for name in iso_dirs), str(iso_dirs))
        ids = set()
        for name in iso_dirs:
            key = json.loads((iso_root / name / "profile.json").read_text(encoding="utf-8"))
            ids.add(key["profile_key"]["vault_id"])
        check("b02 distinct vault ids", len(ids) == 2, str(ids))

        mix_vault = tmp / "mix-vault"
        mix_vault.mkdir()
        _shutil2.copy(ZH_FIXTURE, mix_vault / "zh.md")
        _shutil2.copy(EN_FIXTURES / "cache-invalidation.md", mix_vault / "en.md")
        mix_prof = tmp / "mix-profiles"
        r = run([SCRIPTS / "style_profile.py", "--vault", str(mix_vault),
                 "--files", "zh.md,en.md", "--profile-dir", str(mix_prof),
                 "--name", "auto-mix"])
        check("b02 auto mix exit 0", r.returncode == 0, r.stderr[-300:])
        auto = json.loads((mix_prof / "auto-mix" / "profile.json").read_text(encoding="utf-8"))
        check("b02 auto majority zh excludes en",
              auto["language"] == "zh"
              and auto["language_scope"]["files_excluded"][0]["path"].endswith("en.md"),
              json.dumps(auto.get("language_scope"), ensure_ascii=False))
        r = run([SCRIPTS / "style_profile.py", "--vault", str(mix_vault),
                 "--files", "zh.md,en.md", "--profile-dir", str(mix_prof),
                 "--name", "forced-zh", "--lang", "zh"])
        check("b02 forced zh exit 0", r.returncode == 0, r.stderr[-300:])
        forced = json.loads((mix_prof / "forced-zh" / "profile.json").read_text(encoding="utf-8"))
        check("b02 forced filters not force-counts",
              forced["language"] == "zh" and forced["corpus"]["file_count"] == 1
              and forced["language_scope"]["forced"] is True,
              str(forced.get("language_scope")))

        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir", str(mix_prof),
                 "--json"])
        check("b02 migrate keyed-only rc0", r.returncode == 0
              and json.loads(r.stdout)["plans"][0]["status"] == "already-keyed",
              r.stdout[:200])
        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir",
                 str(tmp / "no-profiles"), "--json"])
        check("b02 migrate empty rc2", r.returncode == 2, r.stdout[:200])

        old_prof = tmp / "legacy-profiles" / "legacy"
        old_prof.mkdir(parents=True)
        legacy = {"profile_version": 2, "language": "zh",
                  "corpus": {"file_count": 1, "total_chars": 400},
                  "metrics": {}, "samples": [],
                  "source": {"vault": str(mix_vault), "files": ["zh.md"]}}
        (old_prof / "profile.json").write_text(json.dumps(legacy, ensure_ascii=False),
                                               encoding="utf-8")
        (old_prof / "voice.md").write_text("# voice-keeper", encoding="utf-8")
        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir",
                 str(tmp / "legacy-profiles"), "--json"])
        plan = json.loads(r.stdout)
        check("b02 migrate plans legacy",
              plan["plans"][0]["status"] == "planned"
              and plan["plans"][0]["to"] == "legacy-zh", r.stdout[:300])
        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir",
                 str(tmp / "legacy-profiles"), "--apply"])
        check("b02 migrate apply rc0", r.returncode == 0, r.stderr[-200:])
        migrated = json.loads((tmp / "legacy-profiles" / "legacy-zh" / "profile.json")
                              .read_text(encoding="utf-8"))
        check("b02 migrated has key",
              migrated["profile_key"]["language"] == "zh"
              and migrated.get("migrated_from") == "legacy",
              json.dumps(migrated.get("profile_key"), ensure_ascii=False))
        kept = (tmp / "legacy-profiles" / "legacy-zh" / "voice.md").read_text(encoding="utf-8")
        check("b02 voice copied", "voice-keeper" in kept, kept[:100])
        still_old = json.loads((old_prof / "profile.json").read_text(encoding="utf-8"))
        check("b02 old profile intact", "profile_key" not in still_old)

        # --- 12. B03: language packs, weak-hint downgrade, allow/ban ---
        r = run([SCRIPTS / "resource_pack.py", "--lang", "zh", "--json"])
        zp = json.loads(r.stdout)
        check("b03 zh pack valid", r.returncode == 0 and zp["ok"] and zp["rules"] >= 8,
              r.stdout[:200])
        r = run([SCRIPTS / "resource_pack.py", "--lang", "en", "--json"])
        ep = json.loads(r.stdout)
        check("b03 en pack valid", r.returncode == 0 and ep["ok"] and ep["rules"] >= 6,
              r.stdout[:200])
        r = run([SCRIPTS / "resource_pack.py", "--lang", "zh", "--pack-root",
                 str(tmp / "no-such-pack-root"), "--json"])
        check("b03 missing pack rc2", r.returncode == 2, r.stdout[:150])

        weak_draft = tmp / "weak-draft.md"
        weak_draft.write_text(
            "把配置改了。把缓存清了。把服务重启了。把日志翻了。"
            "最后把问题定位了。就这样把事情办妥了。", encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", weak_draft, "--profile", zh2_profile,
                 "--json"])
        weak = json.loads(r.stdout)
        cons = [f["severity"] for f in weak["findings"] if f["category"] == "句式"]
        check("b03 constructions weak-only", cons and all(s == "info" for s in cons),
              str(cons))

        ab_draft = tmp / "ab-draft.md"
        ab_draft.write_text("值得注意的是，这个方案极大地提升了性能。说白了就是把缓存清了。",
                            encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", ab_draft, "--profile", zh2_profile,
                 "--json", "--allow", "值得注意的是", "--allow", "极大地"])
        ab = json.loads(r.stdout)
        left = [f for f in ab["findings"]
                if "套话提示语" in f["message"] or "空洞强调" in f["message"]]
        check("b03 allow suppresses", not left
              and ab.get("allowed_suppressed", 0) >= 2,
              str(ab.get("allowed_suppressed")))
        r = run([SCRIPTS / "style_check.py", ab_draft, "--profile", zh2_profile,
                 "--json", "--ban", "说白了"])
        ab2 = json.loads(r.stdout)
        banned = [f for f in ab2["findings"] if f.get("user_banned")]
        check("b03 ban flags", len(banned) == 1, str(banned)[:150])

        # --- 13. B04: fact retention, budget, tail-list violation ---
        import shutil as _sh3

        b04_dir = tmp / "b04"
        b04_dir.mkdir()
        source_md = b04_dir / "source.md"
        source_md.write_text(
            "2026-09-30 发布的基准测试显示，p99 延迟从 800ms 降到 300ms，吞吐提升 45%。"
            "该结论仅在只读负载下成立，可能随写入比例变化。集群配置了 3 副本。"
            "官方文档明确表示不支持跨机房同步。", encoding="utf-8")
        good = b04_dir / "good.md"
        good.write_text(
            "基准测试（2026-09-30）表明 p99 延迟从 800ms 降到 300ms，吞吐提升 45%。"
            "该结论仅在只读负载下成立，可能随写入比例变化。集群配置了 3 副本。"
            "官方文档不支持跨机房同步。" + "补充说明。" * 150, encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(good), "--json"])
        rep = json.loads(r.stdout)
        check("b04 full retention passes", r.returncode == 0
              and rep["retention"]["missing"] == [],
              json.dumps(rep["retention"]["missing"], ensure_ascii=False))
        bad = b04_dir / "bad.md"
        bad.write_text("性能大幅提升，支持跨机房同步。", encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(bad), "--json", "--strict"])
        rep2 = json.loads(r.stdout)
        check("b04 missing facts rc1", r.returncode == 1
              and {"number", "limit", "negation"} <= set(
                  m["kind"] for m in rep2["retention"]["missing"]),
              str(sorted(m["kind"] for m in rep2["retention"]["missing"])))
        nl2 = chr(10) + chr(10)
        tail_md = b04_dir / "tail.md"
        tail_md.write_text(good.read_text(encoding="utf-8")
                           + nl2 + "## Related" + nl2 + "- [[cache]]" + chr(10),
                           encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(tail_md), "--json"])
        rep3 = json.loads(r.stdout)
        check("b04 tail list violation rc2", r.returncode == 2
              and rep3["tail_violation"] is not None,
              str(rep3.get("tail_violation"))[:150])
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(good), "--json", "--lang", "zh"])
        rep4 = json.loads(r.stdout)
        check("b04 zh budget shape", rep4["budget"]["lang"] == "zh"
              and rep4["budget"]["unit"] == "字"
              and rep4["budget"]["within_soft"] is True,
              str(rep4["budget"])[:150])

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All style language-pack tests passed.")


if __name__ == "__main__":
    main()
