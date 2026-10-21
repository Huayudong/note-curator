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
import os
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
        # write_note 会落计划/基线/备份，统一隔离到临时 home，不碰真实 ~/.note-curator
        os.environ["NOTE_CURATOR_HOME"] = str(tmp / "nchome")
        (tmp / "nchome").mkdir()

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

        # 界面文案（--config 指向临时路径，与本机真实配置隔离）
        r = run([SCRIPTS / "check_setup.py", "--lang", "en", "--json",
                 "--config", tmp / "no-such-config.yaml"])
        check("check_setup en messages", "No note-curator configuration" in r.stdout,
              r.stdout[:200])
        r = run([SCRIPTS / "init_setup.py", "--vault", tmp / "v-en", "--author", "T",
                 "--config", tmp / "cfg-en.yaml", "--lang", "en"])
        check("init_setup en messages", "[OK] Generated" in r.stdout and "Next:" in r.stdout,
              r.stdout[:300])

        # --- 10. 配置 schema 校验（safe_yaml）---
        (tmp / "v-en").mkdir(exist_ok=True)
        cfg_schema = tmp / "cfg-schema.yaml"
        cfg_schema.write_text(
            'vault_path: "%s"\n'
            "frontmatter:\n"
            '  author: "T"\n'
            "some_unknown_key: 1\n" % (tmp / "v-en").as_posix(),
            encoding="utf-8")
        r = run([SCRIPTS / "check_setup.py", "--json", "--config", cfg_schema])
        data = json.loads(r.stdout)
        check("check_setup ok with valid config",
              data.get("status") == "ok" and data.get("ok") is True, r.stdout[:300])
        check("check_setup reports unknown fields",
              data.get("unknown_fields") == ["some_unknown_key"], r.stdout[:300])

        # --- 11. bilingual profile isolation, forced-language filter, migration ---
        import shutil as _shutil2

        iso_root = tmp / "iso-profiles"
        for tag in ("v1", "v2"):
            iso_vault = tmp / ("iso-" + tag)
            (iso_vault / "diary").mkdir(parents=True)
            _shutil2.copy(ZH_FIXTURE, iso_vault / "diary" / "note.md")
            r = run([SCRIPTS / "style_profile.py", "--vault", str(iso_vault),
                     "--dir", "diary", "--profile-dir", str(iso_root)])
            check("iso profile %s" % tag, r.returncode == 0, r.stderr[-300:])
        iso_dirs = sorted(d.name for d in iso_root.iterdir())
        check("two isolated profiles", len(iso_dirs) == 2, str(iso_dirs))
        check("lang suffix naming",
              all(name.endswith("-zh") for name in iso_dirs), str(iso_dirs))
        ids = set()
        for name in iso_dirs:
            key = json.loads((iso_root / name / "profile.json").read_text(encoding="utf-8"))
            ids.add(key["profile_key"]["vault_id"])
        check("distinct vault ids", len(ids) == 2, str(ids))

        mix_vault = tmp / "mix-vault"
        mix_vault.mkdir()
        _shutil2.copy(ZH_FIXTURE, mix_vault / "zh.md")
        _shutil2.copy(EN_FIXTURES / "cache-invalidation.md", mix_vault / "en.md")
        mix_prof = tmp / "mix-profiles"
        r = run([SCRIPTS / "style_profile.py", "--vault", str(mix_vault),
                 "--files", "zh.md,en.md", "--profile-dir", str(mix_prof),
                 "--name", "auto-mix"])
        check("auto mix exit 0", r.returncode == 0, r.stderr[-300:])
        auto = json.loads((mix_prof / "auto-mix" / "profile.json").read_text(encoding="utf-8"))
        check("auto majority zh excludes en",
              auto["language"] == "zh"
              and auto["language_scope"]["files_excluded"][0]["path"].endswith("en.md"),
              json.dumps(auto.get("language_scope"), ensure_ascii=False))
        r = run([SCRIPTS / "style_profile.py", "--vault", str(mix_vault),
                 "--files", "zh.md,en.md", "--profile-dir", str(mix_prof),
                 "--name", "forced-zh", "--lang", "zh"])
        check("forced zh exit 0", r.returncode == 0, r.stderr[-300:])
        forced = json.loads((mix_prof / "forced-zh" / "profile.json").read_text(encoding="utf-8"))
        check("forced filters not force-counts",
              forced["language"] == "zh" and forced["corpus"]["file_count"] == 1
              and forced["language_scope"]["forced"] is True,
              str(forced.get("language_scope")))

        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir", str(mix_prof),
                 "--json"])
        check("migrate keyed-only rc0", r.returncode == 0
              and json.loads(r.stdout)["plans"][0]["status"] == "already-keyed",
              r.stdout[:200])
        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir",
                 str(tmp / "no-profiles"), "--json"])
        check("migrate empty rc2", r.returncode == 2, r.stdout[:200])

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
        check("migrate plans legacy",
              plan["plans"][0]["status"] == "planned"
              and plan["plans"][0]["to"] == "legacy-zh", r.stdout[:300])
        r = run([SCRIPTS / "migrate_profiles.py", "--profile-dir",
                 str(tmp / "legacy-profiles"), "--apply"])
        check("migrate apply rc0", r.returncode == 0, r.stderr[-200:])
        migrated = json.loads((tmp / "legacy-profiles" / "legacy-zh" / "profile.json")
                              .read_text(encoding="utf-8"))
        check("migrated has key",
              migrated["profile_key"]["language"] == "zh"
              and migrated.get("migrated_from") == "legacy",
              json.dumps(migrated.get("profile_key"), ensure_ascii=False))
        kept = (tmp / "legacy-profiles" / "legacy-zh" / "voice.md").read_text(encoding="utf-8")
        check("voice copied", "voice-keeper" in kept, kept[:100])
        still_old = json.loads((old_prof / "profile.json").read_text(encoding="utf-8"))
        check("old profile intact", "profile_key" not in still_old)

        # --- 12. language packs, weak-hint downgrade, allow/ban ---
        r = run([SCRIPTS / "resource_pack.py", "--lang", "zh", "--json"])
        zp = json.loads(r.stdout)
        check("zh pack valid", r.returncode == 0 and zp["ok"] and zp["rules"] >= 8,
              r.stdout[:200])
        r = run([SCRIPTS / "resource_pack.py", "--lang", "en", "--json"])
        ep = json.loads(r.stdout)
        check("en pack valid", r.returncode == 0 and ep["ok"] and ep["rules"] >= 6,
              r.stdout[:200])
        r = run([SCRIPTS / "resource_pack.py", "--lang", "zh", "--pack-root",
                 str(tmp / "no-such-pack-root"), "--json"])
        check("missing pack rc2", r.returncode == 2, r.stdout[:150])

        weak_draft = tmp / "weak-draft.md"
        weak_draft.write_text(
            "把配置改了。把缓存清了。把服务重启了。把日志翻了。"
            "最后把问题定位了。就这样把事情办妥了。", encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", weak_draft, "--profile", zh2_profile,
                 "--json"])
        weak = json.loads(r.stdout)
        cons = [f["severity"] for f in weak["findings"] if f["category"] == "句式"]
        check("constructions weak-only", cons and all(s == "info" for s in cons),
              str(cons))

        ab_draft = tmp / "ab-draft.md"
        ab_draft.write_text("值得注意的是，这个方案极大地提升了性能。说白了就是把缓存清了。",
                            encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", ab_draft, "--profile", zh2_profile,
                 "--json", "--allow", "值得注意的是", "--allow", "极大地"])
        ab = json.loads(r.stdout)
        left = [f for f in ab["findings"]
                if "套话提示语" in f["message"] or "空洞强调" in f["message"]]
        check("allow suppresses", not left
              and ab.get("allowed_suppressed", 0) >= 2,
              str(ab.get("allowed_suppressed")))
        r = run([SCRIPTS / "style_check.py", ab_draft, "--profile", zh2_profile,
                 "--json", "--ban", "说白了"])
        ab2 = json.loads(r.stdout)
        banned = [f for f in ab2["findings"] if f.get("user_banned")]
        check("ban flags", len(banned) == 1, str(banned)[:150])

        # --- 13. fact retention, budget, tail-list violation ---
        import shutil as _sh3

        fact_dir = tmp / "facts"
        fact_dir.mkdir()
        source_md = fact_dir / "source.md"
        source_md.write_text(
            "2026-09-30 发布的基准测试显示，p99 延迟从 800ms 降到 300ms，吞吐提升 45%。"
            "该结论仅在只读负载下成立，可能随写入比例变化。集群配置了 3 副本。"
            "官方文档明确表示不支持跨机房同步。", encoding="utf-8")
        good = fact_dir / "good.md"
        good.write_text(
            "基准测试（2026-09-30）表明 p99 延迟从 800ms 降到 300ms，吞吐提升 45%。"
            "该结论仅在只读负载下成立，可能随写入比例变化。集群配置了 3 副本。"
            "官方文档不支持跨机房同步。" + "补充说明。" * 150, encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(good), "--json"])
        rep = json.loads(r.stdout)
        check("full retention passes", r.returncode == 0
              and rep["retention"]["missing"] == [],
              json.dumps(rep["retention"]["missing"], ensure_ascii=False))
        bad = fact_dir / "bad.md"
        bad.write_text("性能大幅提升，支持跨机房同步。", encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(bad), "--json", "--strict"])
        rep2 = json.loads(r.stdout)
        check("missing facts rc1", r.returncode == 1
              and {"number", "limit", "negation"} <= set(
                  m["kind"] for m in rep2["retention"]["missing"]),
              str(sorted(m["kind"] for m in rep2["retention"]["missing"])))
        nl2 = chr(10) + chr(10)
        tail_md = fact_dir / "tail.md"
        tail_md.write_text(good.read_text(encoding="utf-8")
                           + nl2 + "## Related" + nl2 + "- [[cache]]" + chr(10),
                           encoding="utf-8")
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(tail_md), "--json"])
        rep3 = json.loads(r.stdout)
        check("tail list violation rc2", r.returncode == 2
              and rep3["tail_violation"] is not None,
              str(rep3.get("tail_violation"))[:150])
        r = run([SCRIPTS / "fact_check.py", "--source", str(source_md),
                 "--draft", str(good), "--json", "--lang", "zh"])
        rep4 = json.loads(r.stdout)
        check("zh budget shape", rep4["budget"]["lang"] == "zh"
              and rep4["budget"]["unit"] == "字"
              and rep4["budget"]["within_soft"] is True,
              str(rep4["budget"])[:150])

        # --- 14. edit learning with candidates, confirm, undo ---
        learn_dir = tmp / "learning"
        learn_dir.mkdir()
        learn_src = learn_dir / "draft.md"
        learn_src.write_text("值得注意的是，缓存至关重要。综上所述，我们首先设置 TTL。"
                           "其次是过期时间。最后是抖动。以上就是全部内容。", encoding="utf-8")
        r = run([SCRIPTS / "write_note.py", "new", "--vault", str(learn_dir),
                 "--dir", "notes", "--title", "learn-target", "--file", str(learn_src),
                 "--json", "--apply"])
        rid5 = json.loads(r.stdout)["run_id"]
        learn_note = learn_dir / "notes" / "learn-target.md"
        learn_note.write_text("缓存能减少查询，但数据更新后旧值仍可能被读取。"
                            "过期时间要设置，失效时间再叠加随机抖动。", encoding="utf-8")
        r = run([SCRIPTS / "learn_edit.py", "diff", "--profile", str(zh2_profile),
                 "--note", str(learn_note), "--baseline-run", rid5, "--json"])
        check("diff rc0", r.returncode == 0, r.stderr[-250:])
        ev5 = json.loads(r.stdout)
        check("candidates extracted",
              any(c["type"] == "avoid_phrase" for c in ev5["candidates"]),
              json.dumps(ev5["candidates"], ensure_ascii=False)[:150])
        r = run([SCRIPTS / "learn_edit.py", "diff", "--profile", str(zh2_profile),
                 "--note", str(learn_note), "--baseline-run", rid5])
        check("edit learning re-diff idempotent rc2", r.returncode == 2, "rc=%s" % r.returncode)
        r = run([SCRIPTS / "learn_edit.py", "candidates",
                 "--profile", str(zh2_profile), "--json"])
        rows5 = json.loads(r.stdout)
        cid5 = rows5[0]["candidate_id"]
        r = run([SCRIPTS / "learn_edit.py", "confirm", "--profile", str(zh2_profile),
                 "--candidate", cid5])
        check("confirm rc0", r.returncode == 0, r.stderr[-150:])
        r = run([SCRIPTS / "learn_edit.py", "reject", "--profile", str(zh2_profile),
                 "--candidate", cid5])
        check("reject confirmed refused rc2", r.returncode == 2,
              "rc=%s" % r.returncode)
        r = run([SCRIPTS / "learn_edit.py", "undo", "--profile", str(zh2_profile),
                 "--event", ev5["event_id"]])
        check("undo rc0", r.returncode == 0, r.stderr[-150:])
        r = run([SCRIPTS / "learn_edit.py", "undo", "--profile", str(zh2_profile),
                 "--event", ev5["event_id"]])
        check("re-undo idempotent rc2", r.returncode == 2, "rc=%s" % r.returncode)

        # --- 15. learning modes, preference state machine, apply ---
        modes_dir = tmp / "modes"
        modes_dir.mkdir()
        d6 = tmp / "d6.md"
        d6.write_text("值得注意的是，缓存至关重要。综上所述，我们首先设置 TTL。", encoding="utf-8")
        r = run([SCRIPTS / "write_note.py", "new", "--vault", str(modes_dir),
                 "--dir", "notes", "--title", "n1", "--file", str(d6),
                 "--json", "--apply"])
        rid6 = json.loads(r.stdout)["run_id"]
        n1 = modes_dir / "notes" / "n1.md"
        n1.write_text("改好的正文，直接讲结论，没有套话。", encoding="utf-8")
        r = run([SCRIPTS / "learn_edit.py", "diff", "--profile", str(zh2_profile),
                 "--note", str(n1), "--baseline-run", rid6, "--json"])
        check("explicit default diff rc0", r.returncode == 0, r.stderr[-200:])
        r = run([SCRIPTS / "learn_edit.py", "diff", "--profile", str(zh2_profile),
                 "--note", str(n1), "--baseline-run", rid6, "--json"])
        check("mode learning re-diff idempotent rc2", r.returncode == 2, "rc=%s" % r.returncode)

        pf6 = json.loads(zh2_profile.read_text(encoding="utf-8"))
        pf6["learning_mode"] = "auto"
        zh2_profile.write_text(json.dumps(pf6, ensure_ascii=False), encoding="utf-8")
        d7 = tmp / "d7.md"
        d7.write_text("值得注意的是，延迟也很关键。总而言之，我们要加监控。", encoding="utf-8")
        r = run([SCRIPTS / "write_note.py", "new", "--vault", str(modes_dir),
                 "--dir", "notes", "--title", "n2", "--file", str(d7),
                 "--json", "--apply"])
        rid7 = json.loads(r.stdout)["run_id"]
        n2 = modes_dir / "notes" / "n2.md"
        n2.write_text("改好的正文，直接讲结论，没有套话。", encoding="utf-8")
        r = run([SCRIPTS / "learn_edit.py", "diff", "--profile", str(zh2_profile),
                 "--note", str(n2), "--baseline-run", rid7, "--json"])
        check("auto diff rc0", r.returncode == 0, r.stderr[-200:])
        pf6 = json.loads(zh2_profile.read_text(encoding="utf-8"))
        auto = [p for p in pf6.get("preferences", []) if p.get("auto_confirmed")]
        check("auto confirmed with evidence",
              len(auto) == 1 and auto[0]["evidence"] >= 2, str(pf6.get("preferences"))[:200])

        chk = tmp / "chk6.md"
        chk.write_text("值得注意的是，缓存依然至关重要。", encoding="utf-8")
        r = run([SCRIPTS / "style_check.py", chk, "--profile", zh2_profile, "--json"])
        hits = [f for f in json.loads(r.stdout)["findings"] if f.get("from_preference")]
        check("preference applies", len(hits) >= 1, str(hits)[:150])
        pid6 = auto[0]["id"]
        r = run([SCRIPTS / "preferences.py", "disable", "--profile", zh2_profile,
                 "--pref", pid6, "--reason", "暂停"])
        check("disable rc0", r.returncode == 0, r.stderr[-150:])
        r = run([SCRIPTS / "style_check.py", chk, "--profile", zh2_profile, "--json"])
        hits2 = [f for f in json.loads(r.stdout)["findings"] if f.get("from_preference")]
        check("disabled silent", not hits2, str(hits2)[:150])
        r = run([SCRIPTS / "preferences.py", "forget", "--profile", zh2_profile,
                 "--pref", pid6])
        check("forget rc0", r.returncode == 0, r.stderr[-150:])
        pf6 = json.loads(zh2_profile.read_text(encoding="utf-8"))
        check("forgotten status",
              pf6["preferences"][0]["status"] == "forgotten",
              str(pf6["preferences"][0]["status"]))

        # --- 16. chunked index, cross-language search, link resolver ---
        index_vault = tmp / "index-vault"
        (index_vault / "biancheng").mkdir(parents=True)
        (index_vault / "renwen").mkdir()
        NL2 = chr(10) + chr(10)
        tail_section = (chr(10).join(["失效时间叠加随机抖动。"] * 30)
                        + chr(10) + chr(10) + "## 雪崩恢复演练手册"
                        + chr(10) + chr(10)
                        + "恢复演练分四步，先降级读库再重建缓存，最后复盘告警阈值。")
        zh_body = "# 缓存失效" + NL2 + NL2 + "概述穿透击穿雪崩。" + NL2 + tail_section
        (index_vault / "biancheng" / "缓存失效.md").write_text(zh_body, encoding="utf-8")
        en_body = ("# Cache Invalidation" + NL2 + NL2
                   + "Cache invalidation is hard; avalanche recovery drills rebuild "
                     "the cache.")
        (index_vault / "biancheng" / "cache invalidation.md").write_text(en_body, encoding="utf-8")
        note_body = ("# 完全不同的标题" + NL2 + NL2 + "## 雪崩小节" + NL2 + NL2
                     + "内容 ^blk1")
        (index_vault / "biancheng" / "笔记.md").write_text(note_body, encoding="utf-8")
        (index_vault / "renwen" / "笔记.md").write_text(
            "# 人文笔记" + NL2 + NL2 + "正文。", encoding="utf-8")

        index_file = tmp / "index-file.json"
        r = run([SCRIPTS / "index_vault.py", "--vault", str(index_vault),
                 "--out", str(index_file), "--json"])
        check("index built", r.returncode == 0
              and json.loads(r.stdout)["files"] == 4, r.stdout[:150])
        r = run([SCRIPTS / "index_vault.py", "--vault", str(index_vault),
                 "--out", str(index_file), "--json", "--incremental"])
        stats = json.loads(r.stdout)
        check("incremental unchanged", stats["unchanged"] == 4
              and stats["updated"] == 0, str(stats))

        r = run([SCRIPTS / "search_notes.py", "--index", str(index_file),
                 "--query", "雪崩恢复演练 复盘告警", "--json"])
        hits = json.loads(r.stdout)
        check("tail content recall", bool(hits)
              and hits[0]["path"].endswith("缓存失效.md")
              and hits[0]["evidence"]["pos_ratio"] > 0.4,
              json.dumps(hits, ensure_ascii=False)[:200])
        r = run([SCRIPTS / "search_notes.py", "--index", str(index_file),
                 "--query", "缓存失效", "--json"])
        cross = [h for h in json.loads(r.stdout) if h.get("cross_language")]
        check("cross-language bridge", bool(cross)
              and cross[0]["path"].endswith("cache invalidation.md"),
              json.dumps(cross, ensure_ascii=False)[:200])

        r = run([SCRIPTS / "link_resolver.py", "--vault", str(index_vault),
                 "--resolve", "[[笔记]]", "--json"])
        rep = json.loads(r.stdout)["links"][0]
        check("ambiguous candidates",
              rep["status"] == "ambiguous" and len(rep["candidates"]) == 2, str(rep)[:200])
        r = run([SCRIPTS / "link_resolver.py", "--vault", str(index_vault),
                 "--resolve", "[[biancheng/笔记#雪崩小节]]", "--json"])
        check("heading anchor resolved",
              json.loads(r.stdout)["links"][0]["status"] == "resolved")
        link_draft = tmp / "link-draft.md"
        link_draft.write_text("见 [[biancheng/笔记]] 与 [[人文侧页面]] 与 [[不存在的页]]。",
                          encoding="utf-8")
        r = run([SCRIPTS / "link_resolver.py", "--vault", str(index_vault),
                 "--check-draft", str(link_draft), "--json"])
        payload = json.loads(r.stdout)
        check("draft unresolved blocked", payload["unresolved"] >= 2
              and r.returncode == 1, str(payload)[:250])

        # --- 17. SourceDocument pipeline, statuses, dedup ---
        fx = REPO_ROOT / "tests" / "fixtures" / "html"
        article = fx / "article.html"
        r = run([SCRIPTS / "source_document.py", "from-file", str(article)])
        doc = json.loads(r.stdout)
        check("from-file complete", r.returncode == 0
              and doc["extraction"]["status"] == "complete", str(doc["extraction"]))
        check("table+code stats", doc["stats"]["tables"] == 1
              and doc["stats"]["code_blocks"] == 1, str(doc["stats"]))
        source_doc = tmp / "source-doc.json"
        source_doc.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        r = run([SCRIPTS / "source_document.py", "check", str(source_doc)])
        check("check complete rc0", r.returncode == 0, "rc=%s" % r.returncode)

        r = run([SCRIPTS / "source_document.py", "from-url", article.as_uri()])
        docu = json.loads(r.stdout)
        check("from-url file scheme", r.returncode == 0
              and docu["kind"] == "url"
              and docu["source_normalized"].startswith("file:///"),
              str(docu.get("extraction")))
        source_url_doc = tmp / "source-doc-url.json"
        source_url_doc.write_text(json.dumps(docu, ensure_ascii=False), encoding="utf-8")

        r = run([SCRIPTS / "source_document.py", "from-file",
                 str(fx / "wall.html")])
        docw = json.loads(r.stdout)
        check("login wall failed", docw["extraction"]["status"] == "failed"
              and "login_wall" in docw["extraction"]["issues"],
              str(docw["extraction"]))
        r = run([SCRIPTS / "source_document.py", "from-file", str(article),
                 "--max-chars", "40"])
        doct = json.loads(r.stdout)
        check("truncated flagged",
              "truncated" in doct["extraction"]["issues"], str(doct["extraction"]))

        r = run([SCRIPTS / "source_document.py", "normalize-url",
                 "https://Example.com/a/?utm_source=x&id=3&spm=1#f"])
        check("normalize url", r.stdout.strip() == "https://example.com/a?id=3",
              r.stdout.strip())
        r = run([SCRIPTS / "source_document.py", "register", "--doc", str(source_url_doc)])
        check("register rc0", r.returncode == 0, r.stdout[:60])
        r = run([SCRIPTS / "source_document.py", "lookup", "--url",
                 str(docu["source_normalized"])])
        check("lookup hit", r.returncode == 0
              and "缓存实战笔记" in r.stdout, r.stdout[:100])
        r = run([SCRIPTS / "source_document.py", "register", "--doc", str(source_url_doc)])
        check("register same rc2", r.returncode == 2, "rc=%s" % r.returncode)

        r = run([SCRIPTS / "source_document.py", "from-file",
                 str(fx / "evil.html")])
        doce = json.loads(r.stdout)
        check("script stripped",
              "stealSecrets" not in json.dumps(doce, ensure_ascii=False))
        check("body text inert",
              any("读取密钥" in s["text"] for s in doce["segments"]))

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All style language-pack tests passed.")


if __name__ == "__main__":
    main()
