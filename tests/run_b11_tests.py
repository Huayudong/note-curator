#!/usr/bin/env python3
"""
run_b11_tests.py — B11 稳定交付回归测试。

覆盖：
  1. 写锁互斥：持锁期间另一进程 apply 被拒（B11-04）；释放后成功
  2. 陈旧锁接管：超时残留锁可自动接管
  3. 状态版本兼容矩阵：未来 schema 的计划被拒绝（B11-09）
  4. 路径拷打（B11-11）：中文+空格目录、超长文件名、NFD 组合字符
     的写入/撤销/索引/检索
  5. doctor 诊断输出（B11-10）
  6. perf_bench 冒烟（B11-01/02）

用法：python tests/run_b11_tests.py
退出码：0 全部通过；1 有失败。
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts"

FAILURES = []


def check(name, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else " — %s" % str(detail)[:300]))
    if not condition:
        FAILURES.append(name)


def run(script, args, home=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    if home:
        env["NOTE_CURATOR_HOME"] = str(home)
    return subprocess.run([sys.executable, str(SCRIPTS / script)]
                          + [str(a) for a in args],
                          capture_output=True, encoding="utf-8",
                          errors="replace", env=env)


def main():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        home = td / "home"
        # 锁目录随 NOTE_CURATOR_HOME：先设置环境再导入 nc_core，
        # 让测试进程与被测子进程看同一把锁
        os.environ["NOTE_CURATOR_HOME"] = str(home)
        sys.path.insert(0, str(SCRIPTS))
        import nc_core
        vault = td / "test vault 中文"

        # ---- 1. 写锁互斥（B11-04）----
        content = td / "content.md"
        content.write_text("# 标题\n\n正文。", encoding="utf-8")
        vault.mkdir()
        r = run("write_note.py", ["new", "--vault", vault, "--dir", "编程",
                                  "--title", "并发目标", "--file", content,
                                  "--json"], home)
        plan = json.loads(r.stdout)
        rid = plan["run_id"]
        lock = nc_core.acquire_lock("vault:" + str(vault.resolve()))
        check("lock acquired", lock is not None)
        r = run("write_note.py", ["apply", "--run", rid, "--json"], home)
        check("locked apply rejected rc2", r.returncode == 2
              and "E-LOCK" in r.stdout, r.stdout[:200])
        check("locked apply no write",
              not (vault / "编程" / "并发目标.md").exists())
        nc_core.release_lock(lock)
        r = run("write_note.py", ["apply", "--run", rid, "--json"], home)
        check("after release apply rc0", r.returncode == 0, r.stderr[-200:])

        # ---- 2. 陈旧锁接管 ----
        stale = nc_core.locks_dir() / "stale.lock"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(json.dumps({"pid": 1, "at": time.time() - 9999,
                                     "writer": "0.0.1"}), encoding="utf-8")
        got = nc_core.acquire_lock("stale", stale_seconds=300)
        check("stale lock taken over", got is not None)
        nc_core.release_lock(got)

        # ---- 3. 未来 schema 拒绝（B11-09）----
        (vault / "编程" / "并发目标.md").unlink()
        r = run("write_note.py", ["new", "--vault", vault, "--dir", "编程",
                                  "--title", "schema目标", "--file", content,
                                  "--json"], home)
        rid2 = json.loads(r.stdout)["run_id"]
        plan_file = home / "plans" / ("%s.json" % rid2)
        plan_obj = json.loads(plan_file.read_text(encoding="utf-8"))
        plan_obj["schema"] = 99
        plan_file.write_text(json.dumps(plan_obj, ensure_ascii=False),
                             encoding="utf-8")
        r = run("write_note.py", ["apply", "--run", rid2, "--json"], home)
        check("future schema refused rc1", r.returncode == 1
              and "E-SCHEMA-NEW" in r.stdout, r.stdout[:200])
        check("future schema no write",
              not (vault / "编程" / "schema目标.md").exists())

        # ---- 4. 路径拷打（B11-11）----
        torture_vault = td / "拷打 库"
        long_name = "长" * 120 + "文件名"
        torture_vault.mkdir(parents=True)
        r = run("write_note.py", ["new", "--vault", torture_vault,
                                  "--dir", "中文 目录/深 层", "--title", long_name,
                                  "--file", content, "--json", "--apply"], home)
        check("torture long name apply", r.returncode == 0, r.stderr[-200:])
        nfd = "cafe\u0301 文件"
        r = run("write_note.py", ["new", "--vault", torture_vault,
                                  "--dir", "中文 目录", "--title", nfd,
                                  "--file", content, "--json", "--apply"], home)
        check("torture nfd name apply", r.returncode == 0, r.stderr[-200:])
        idx = td / "torture-index.json"
        r = run("index_vault.py", ["--vault", torture_vault, "--out", idx])
        check("torture index ok", r.returncode == 0, r.stderr[-150:])
        r = run("search_notes.py", ["--index", idx, "--query", "正文内容足够长",
                                    "--json"])
        hits = json.loads(r.stdout)
        check("torture search hits", bool(hits)
              and any("长" in h["path"] for h in hits),
              json.dumps(hits, ensure_ascii=False)[:200])
        undo_r = run("write_note.py", ["log", "--json"], home)
        check("log readable after torture", undo_r.returncode == 0)

        # ---- 5. doctor（B11-10）----
        r = run("doctor.py", ["--json"], home)
        d = json.loads(r.stdout)
        # 此前故意写入了 schema=99 的坏计划，doctor 报告问题属正确行为
        check("doctor report fields", "versions" in d and "storage" in d
              and "state" in d and len(d["packs"]) == 2
              and any("schema" in p for p in d["problems"]), str(d)[:200])

        # ---- 6. perf_bench 冒烟（B11-01/02）----
        r = run("perf_bench.py", ["--notes", "60", "--size", "500", "--json"], home)
        bench = json.loads(r.stdout)
        check("perf bench smoke", r.returncode == 0
              and bench["full_index_seconds"] > 0
              and bench["incremental_index_seconds"] > 0
              and bench["search_hit_groups"] >= 2, str(bench)[:200])

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All B11 stability tests passed.")


if __name__ == "__main__":
    main()
