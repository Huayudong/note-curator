#!/usr/bin/env python3
"""
run_write_tests.py — 写入事务回归测试（预览/应用/撤销/冲突/幂等/编码/滚动窗口）。

在临时目录里跑全部用例；通过 NOTE_CURATOR_HOME 把计划、日志、备份、基线
全部隔离到临时目录，不读写真实用户数据。
子进程不设置 PYTHONUTF8 / PYTHONIOENCODING，验证脚本在 Windows 默认编码
环境下自我声明 UTF-8。

用法：python tests/run_write_tests.py
退出码：0 全部通过；1 有失败。
"""

import json
import os
import subprocess
import sys
import tempfile
import hashlib
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts"
WRITE = SCRIPTS / "write_note.py"
PROFILE = SCRIPTS / "style_profile.py"
LEARN = SCRIPTS / "style_learn.py"
ZH_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "zh" / "git-rebase.md"

FAILURES = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print("[%s] %s%s" % (status, name, ("" if condition else " — %s" % str(detail)[:400])))
    if not condition:
        FAILURES.append(name)


def child_env(data_home):
    """模拟 Windows 默认编码环境：剥掉 UTF-8 相关环境变量。"""
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO")}
    env["NOTE_CURATOR_HOME"] = str(data_home)
    return env


def run_write(args, data_home):
    return subprocess.run([sys.executable, str(WRITE)] + [str(a) for a in args],
                          capture_output=True, env=child_env(data_home))


def run_py(script, args, data_home):
    return subprocess.run([sys.executable, str(script)] + [str(a) for a in args],
                          capture_output=True, env=child_env(data_home))


def out_json(result):
    return json.loads(result.stdout.decode("utf-8"))


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        data = td / "nchome"
        vault = td / "vault"
        (vault / "prog").mkdir(parents=True)
        content_a = td / "content-a.md"
        content_a.write_text("# 缓存雪崩\n\n正文内容第一段。\n", encoding="utf-8")
        content_b = td / "content-b.md"
        content_b.write_text("# 另一篇\n\n不同的内容。\n", encoding="utf-8")

        # ---- 1. new：默认仅预览 ----
        r = run_write(["new", "--vault", vault, "--dir", "prog",
                       "--title", "缓存雪崩", "--file", content_a, "--json"], data)
        check("new preview exit 0", r.returncode == 0, r.stderr[-300:])
        j = out_json(r)
        check("new preview status",
              j.get("ok") is True and j.get("status") == "previewed" and j.get("run_id"),
              r.stdout[:200])
        target = vault / "prog" / "缓存雪崩.md"
        check("new preview not written", not target.exists())
        rid = j["run_id"]

        # ---- 2. apply 提交 ----
        r = run_write(["apply", "--run", rid, "--json"], data)
        check("apply exit 0", r.returncode == 0, r.stderr[-300:])
        check("apply committed", out_json(r).get("status") == "committed", r.stdout[:200])
        check("apply content", target.exists()
              and target.read_text(encoding="utf-8") == content_a.read_text(encoding="utf-8"))

        # ---- 3. 相同 run_id 重复 apply 幂等（验收 2） ----
        r = run_write(["apply", "--run", rid, "--json"], data)
        check("reapply exit 0", r.returncode == 0, r.stderr[-200:])
        check("reapply idempotent",
              out_json(r).get("status") == "already-applied", r.stdout[:200])
        check("reapply no duplication",
              target.read_text(encoding="utf-8").count("缓存雪崩") == 1)

        # ---- 4. new 目标已存在：同内容幂等、不同内容拒绝（验收 1） ----
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "缓存雪崩",
                       "--file", content_a, "--json"], data)
        check("new same-content idempotent",
              r.returncode == 0 and "already-exists" in out_json(r).get("status", ""),
              r.stdout[:200] + r.stderr[-200:])
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "缓存雪崩",
                       "--file", content_b, "--json"], data)
        check("new different rejected", r.returncode == 2, "rc=%s" % r.returncode)
        check("new different not overwritten",
              target.read_text(encoding="utf-8").startswith("# 缓存雪崩"))

        # ---- 5. 路径安全 ----
        (vault / "prog" / "Note.md").write_text("x", encoding="utf-8")
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "NOTE",
                       "--file", content_b, "--json"], data)
        check("case collision rejected", r.returncode == 2, "rc=%s" % r.returncode)
        r = run_write(["new", "--vault", vault, "--dir", "../outside", "--title", "T",
                       "--file", content_b, "--json"], data)
        check("dir escape rejected", r.returncode == 2, "rc=%s" % r.returncode)
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "CON",
                       "--file", content_b, "--json", "--apply"], data)
        check("reserved name sanitized", r.returncode == 0
              and (vault / "prog" / "CON 笔记.md").exists(), r.stderr[-200:])

        # ---- 6. merge：预览后外部修改 → apply 冲突拒绝（验收 3） ----
        old_note = vault / "prog" / "old.md"
        old_note.write_text("# 旧笔记\n\n原内容。\n", encoding="utf-8")
        patch = td / "patch.md"
        patch.write_text('---\nsource: "https://example.com/a"\n---\n'
                         "## APPEND EOF\n\n新增段落内容。\n", encoding="utf-8")
        r = run_write(["merge", "--vault", vault, "--target", "prog/old.md",
                       "--patch", patch, "--json"], data)
        check("merge preview exit 0", r.returncode == 0, r.stderr[-300:])
        jm = out_json(r)
        check("merge preview status", jm.get("status") == "previewed", r.stdout[:200])
        check("merge preview not written",
              "来源补充" not in old_note.read_text(encoding="utf-8"))
        rid_m = jm["run_id"]
        old_note.write_text("# 旧笔记\n\n用户改过的内容。\n", encoding="utf-8")
        r = run_write(["apply", "--run", rid_m, "--json"], data)
        check("merge conflict exit 3", r.returncode == 3, "rc=%s" % r.returncode)
        check("merge conflict not written",
              "用户改过的内容" in old_note.read_text(encoding="utf-8")
              and "新增段落内容。" not in old_note.read_text(encoding="utf-8"))
        rev = data / "writes" / "backup" / ("%s.reverse.patch" % rid_m)
        check("merge reverse patch saved", rev.exists(), str(rev))

        # ---- 7. merge 正常提交：写入 + 来源行 + 备份 → undo 恢复（验收 4/5） ----
        old_note.write_text("# 旧笔记\n\n原内容。\n", encoding="utf-8")
        r = run_write(["merge", "--vault", vault, "--target", "prog/old.md",
                       "--patch", patch, "--json", "--apply"], data)
        check("merge apply exit 0", r.returncode == 0, r.stderr[-300:])
        merged = old_note.read_text(encoding="utf-8")
        check("merge written", "新增段落内容。" in merged and "来源补充" in merged,
              merged[:200])
        check("merge frontmatter untouched", merged.startswith("# 旧笔记"))
        rid_m2 = out_json(r)["run_id"]
        backup = data / "writes" / "backup" / ("%s.md" % rid_m2)
        check("backup saved", backup.exists(), str(backup))
        r = run_write(["undo", "--run", rid_m2, "--json"], data)
        check("undo exit 0", r.returncode == 0, r.stderr[-300:])
        check("undo restored",
              old_note.read_text(encoding="utf-8") == "# 旧笔记\n\n原内容。\n")
        r = run_write(["undo", "--run", rid_m2, "--json"], data)
        check("undo idempotent", r.returncode == 0
              and out_json(r).get("status") == "already-reverted", r.stdout[:200])

        # ---- 8. 撤销前用户又改 → 拒绝恢复 + 反向差异（验收 5） ----
        r = run_write(["merge", "--vault", vault, "--target", "prog/old.md",
                       "--patch", patch, "--json", "--apply"], data)
        rid_m3 = out_json(r)["run_id"]
        old_note.write_text("# 旧笔记\n\n原内容。\n\n用户又改了。\n", encoding="utf-8")
        r = run_write(["undo", "--run", rid_m3, "--json"], data)
        check("undo conflict exit 3", r.returncode == 3, "rc=%s" % r.returncode)
        check("undo conflict preserved",
              "用户又改了" in old_note.read_text(encoding="utf-8"))
        check("undo reverse patch saved",
              (data / "writes" / "backup" / ("%s.reverse.patch" % rid_m3)).exists())

        # ---- 9. new 撤销：未修改可删；被修改拒绝 ----
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "撤销测试",
                       "--file", content_b, "--json", "--apply"], data)
        rid_n = out_json(r)["run_id"]
        n_target = vault / "prog" / "撤销测试.md"
        check("new apply written", n_target.exists())
        r = run_write(["undo", "--run", rid_n, "--json"], data)
        check("new undo removed", r.returncode == 0 and not n_target.exists(),
              r.stderr[-200:])
        r = run_write(["new", "--vault", vault, "--dir", "prog", "--title", "撤销测试2",
                       "--file", content_b, "--json", "--apply"], data)
        rid_n2 = out_json(r)["run_id"]
        n_target2 = vault / "prog" / "撤销测试2.md"
        n_target2.write_text("用户编辑过", encoding="utf-8")
        r = run_write(["undo", "--run", rid_n2, "--json"], data)
        check("new undo conflict exit 3", r.returncode == 3, "rc=%s" % r.returncode)
        check("new undo conflict preserved",
              n_target2.read_text(encoding="utf-8") == "用户编辑过")

        # ---- 10. 生成基线 + 日志 + merge 重复 apply 幂等 ----
        r = run_write(["merge", "--vault", vault, "--target", "prog/old.md",
                       "--patch", patch, "--json", "--apply"], data)
        check("merge apply 2 exit 0", r.returncode == 0, r.stderr[-300:])
        rid_m4 = out_json(r)["run_id"]
        baseline = data / "baselines" / ("%s.json" % rid_m4)
        check("baseline saved", baseline.exists(), str(baseline))
        bj = json.loads(baseline.read_text(encoding="utf-8"))
        check("baseline fields",
              bj.get("source_type") == "generated"
              and bj.get("target") == "prog/old.md"
              and bj.get("content_hash") == sha(bj.get("content", "")),
              json.dumps({k: bj.get(k) for k in ("source_type", "target")}, ensure_ascii=False))
        r = run_write(["apply", "--run", rid_m4, "--json"], data)
        check("merge reapply idempotent", r.returncode == 0, r.stderr[-200:])
        appended_twice = old_note.read_text(encoding="utf-8").count("新增段落内容。")
        check("merge reapply no dup fragment", appended_twice == 1, appended_twice)
        r = run_write(["log", "--json"], data)
        entries = out_json(r).get("entries", [])
        check("log entries recorded", len(entries) >= 5, len(entries))

        # ---- 11. 默认编码环境下 UTF-8 输出 ----
        raw = run_write(["new", "--vault", vault, "--dir", "prog", "--title",
                         "编码检查", "--file", content_a], data)
        text = raw.stderr.decode("utf-8", errors="strict")
        check("utf8 stderr decodes", "编码检查" in text, text[:200])

        # ---- 12. 滚动窗口按样本时间保留最新 ----
        window_vault = td / "window-vault"
        window_vault.mkdir()
        shutil_src = ZH_FIXTURE.read_text(encoding="utf-8")
        old_f = window_vault / "old-note.md"
        new_f = window_vault / "new-note.md"
        old_f.write_text(shutil_src, encoding="utf-8")
        new_f.write_text(shutil_src + "\n\n补一段更晚的修改。\n", encoding="utf-8")
        past = time.time() - 86400 * 30
        os.utime(old_f, (past, past))
        wp = td / "window-profile"
        r = run_py(PROFILE, ["--vault", window_vault, "--files", "old-note.md",
                             "--profile-dir", wp, "--name", "win"], data)
        check("window base profile exit 0", r.returncode == 0, r.stderr[-300:])
        r = run_py(LEARN, ["--profile", wp / "win" / "profile.json",
                           "--note", "new-note.md", "--sample", "1"], data)
        check("window learn exit 0", r.returncode == 0, r.stderr[-300:])
        kept = json.loads((wp / "win" / "profile.json").read_text(encoding="utf-8"))
        files = kept.get("source", {}).get("files", [])
        check("window keeps newest", files == ["new-note.md"], str(files))

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All write-transaction tests passed.")


if __name__ == "__main__":
    main()
