#!/usr/bin/env python3
"""
run_pack_tests.py — 语言包维护回归测试。

覆盖：
  1. 限额拒绝：规则数/模式长度/非法正则
  2. 渠道与规则状态：stable 不加载 candidate/deprecated；
     experimental 加载 candidate
  3. 完整性清单：tamper 拒绝加载
  4. install/rollback 往返
  5. pack_compare 新旧包效果差异
  6. 贡献模板可解析

用法：python tests/run_pack_tests.py
退出码：0 全部通过；1 有失败。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "scripts"
PACKS = REPO_ROOT / "plugins" / "note-curator" / "skills" / "note-curator" / "language-packs"

FAILURES = []


def check(name, condition, detail=""):
    print("[%s] %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else " — %s" % str(detail)[:280]))
    if not condition:
        FAILURES.append(name)


def run(script, args, env_extra=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONUTF8", "PYTHONIOENCODING", "NC_PACK_CHANNEL",
                        "NOTE_CURATOR_PACK_ROOT")}
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(SCRIPTS / script)]
                          + [str(a) for a in args],
                          capture_output=True, encoding="utf-8",
                          errors="replace", env=env)


def base_pack():
    shutil_src = PACKS / "zh-CN" / "pack.json"
    return json.loads(shutil_src.read_text(encoding="utf-8"))


def write_pack(root, pack):
    d = Path(root) / "zh-CN"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
    (d / "pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    return d


def main():
    sys.path.insert(0, str(SCRIPTS))
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        proot = td / "packs"
        home = td / "home"
        proot.mkdir()
        shutil.copytree(PACKS / "zh-CN", proot / "zh-CN",
                        dirs_exist_ok=True)
        pack_env = {"NOTE_CURATOR_PACK_ROOT": str(proot)}

        # ---- 1. 限额 ----
        pack = base_pack()
        pack["rules"] = [{"id": "r%d" % i, "guidance": "g"} for i in range(201)]
        write_pack(proot, pack)
        from resource_pack import load_pack
        import importlib
        sys.path.insert(0, str(SCRIPTS))
        os.environ["NOTE_CURATOR_PACK_ROOT"] = str(proot)
        import resource_pack
        importlib.reload(resource_pack)
        got, warns = resource_pack.load_pack("zh")
        check("rule count limit", got is None
              and any("200" in w for w in warns), str(warns)[:150])

        pack = base_pack()
        pack["rules"] = [{"id": "long", "guidance": "g", "pattern": "a" * 600}]
        write_pack(proot, pack)
        got, warns = resource_pack.load_pack("zh")
        check("pattern length limit", got is None
              and any("500" in w for w in warns), str(warns)[:150])

        pack = base_pack()
        pack["rules"] = [{"id": "badre", "guidance": "g", "pattern": "(unclosed"}]
        write_pack(proot, pack)
        got, warns = resource_pack.load_pack("zh")
        check("bad regex rejected", got is None
              and any("编译" in w for w in warns), str(warns)[:150])

        # ---- 2. 渠道与规则状态 ----
        pack = base_pack()
        pack["rules"] = [
            {"id": "stable-one", "guidance": "g", "status": "stable"},
            {"id": "cand-one", "guidance": "g", "status": "candidate"},
            {"id": "dead-one", "guidance": "g", "status": "deprecated"},
        ]
        write_pack(proot, pack)
        os.environ.pop("NC_PACK_CHANNEL", None)
        got, warns = resource_pack.load_pack("zh")
        ids = [r["id"] for r in (got or {}).get("rules", [])]
        check("stable channel filters", got is not None and ids == ["stable-one"],
              str(ids))
        os.environ["NC_PACK_CHANNEL"] = "experimental"
        got, warns = resource_pack.load_pack("zh")
        ids = [r["id"] for r in (got or {}).get("rules", [])]
        check("experimental includes candidate only", ids == ["stable-one",
                                                              "cand-one"], str(ids))
        os.environ.pop("NC_PACK_CHANNEL", None)

        # ---- 3. 完整性清单 ----
        shutil.copytree(PACKS / "zh-CN", proot / "zh-CN",
                        dirs_exist_ok=True)
        r = run("resource_pack.py", ["--lang", "zh", "--write-manifest"], pack_env)
        check("write manifest rc0", r.returncode == 0, r.stdout[:100])
        manifest = json.loads((proot / "zh-CN" / "manifest.json")
                              .read_text(encoding="utf-8"))
        check("manifest lists files", len(manifest["files"]) >= 3, str(manifest)[:150])
        pack_meta = json.loads((proot / "zh-CN" / "pack.json")
                               .read_text(encoding="utf-8"))
        check("manifest version matches pack",
              manifest.get("pack_version") == pack_meta.get("pack_version"),
              str(manifest.get("pack_version")))
        pf = proot / "zh-CN" / "pack.json"
        pf.write_text(pf.read_text(encoding="utf-8") + " ", encoding="utf-8")
        got, warns = resource_pack.load_pack("zh")
        check("tamper refused by manifest", got is None
              and any("完整性" in w for w in warns), str(warns)[:150])
        shutil.rmtree(proot / "zh-CN")
        shutil.copytree(PACKS / "zh-CN", proot / "zh-CN",
                        dirs_exist_ok=True)

        # ---- 4. install / rollback ----
        src = td / "src-pack" / "zh-CN"
        src.mkdir(parents=True)
        newpack = base_pack()
        newpack["pack_version"] = "9.9.9"
        (src / "pack.json").write_text(json.dumps(newpack, ensure_ascii=False,
                                                  indent=2), encoding="utf-8")
        # 行尾不敏感（CI 修复回归）：CRLF/LF 差异不改变内容完整性判定
        cj = proot / "zh-CN" / "concepts.json"
        raw_cj = cj.read_text(encoding="utf-8")
        flipped = (raw_cj.replace(chr(10), chr(13) + chr(10))
                   if chr(13) not in raw_cj
                   else raw_cj.replace(chr(13) + chr(10), chr(10)))
        with open(cj, "w", encoding="utf-8", newline="") as h:
            h.write(flipped)
        got, warns = resource_pack.load_pack("zh")
        check("manifest newline-insensitive", got is not None
              and got.get("pack_version") == "1.0.0", str(warns)[:150])
        with open(cj, "w", encoding="utf-8", newline="") as h:
            h.write(raw_cj)

        r = run("resource_pack.py", ["--lang", "zh", "--install", src], pack_env)
        check("install rc0", r.returncode == 0, r.stdout[:120] + r.stderr[-120:])
        installed = json.loads((proot / "zh-CN" / "pack.json")
                               .read_text(encoding="utf-8"))
        check("installed version", installed["pack_version"] == "9.9.9")
        r = run("resource_pack.py", ["--lang", "zh", "--rollback"], pack_env)
        check("rollback rc0", r.returncode == 0, r.stdout[:120] + r.stderr[-120:])
        rolled = json.loads((proot / "zh-CN" / "pack.json").read_text(encoding="utf-8"))
        check("rolled back version", rolled["pack_version"] == "1.0.0")
        r = run("resource_pack.py", ["--lang", "zh", "--rollback"], pack_env)
        check("rollback is reversible rc0", r.returncode == 0, "rc=%s" % r.returncode)
        again = json.loads((proot / "zh-CN" / "pack.json").read_text(encoding="utf-8"))
        check("rollback back to 9.9.9", again["pack_version"] == "9.9.9")

        # ---- 5. pack_compare ----
        old_root = td / "old-root"
        old_pack_dir = old_root / "zh-CN"
        old_pack_dir.mkdir(parents=True)
        oldpack = base_pack()
        oldpack["terms"]["ai_tell_patterns"] = {
            k: v for k, v in oldpack["terms"]["ai_tell_patterns"].items()
            if k != "套话提示语"}
        (old_pack_dir / "pack.json").write_text(json.dumps(oldpack,
                                                           ensure_ascii=False,
                                                           indent=2),
                                                encoding="utf-8")
        profile = td / "prof" / "p" / "profile.json"
        profile.parent.mkdir(parents=True, exist_ok=True)
        vault = td / "v"
        vault.mkdir()
        (vault / "s.md").write_text(
            "用户的原创中文笔记，讲缓存策略。缓存能减少查询，但数据更新后旧值仍可能被读取，"
            "所以过期策略要配合抖动。配置里我们用 TTL 抖动把失效摊开，效果不错，值得记录。" * 3,
            encoding="utf-8")
        r = run("style_profile.py", ["--vault", vault, "--files", "s.md",
                                     "--profile-dir", profile.parent.parent,
                                     "--name", "p"], {"NOTE_CURATOR_HOME": str(home)})
        sample = td / "sample.md"
        sample.write_text("值得注意的是，缓存至关重要。", encoding="utf-8")
        r = run("pack_compare.py", ["--old", old_root, "--new", proot,
                                    "--profile", profile, "--samples", str(sample),
                                    "--json"],
                {"NOTE_CURATOR_HOME": str(home)})
        cmp_res = json.loads(r.stdout)
        check("compare detects delta", cmp_res["changed"] >= 1
              and any(k.startswith("AI 腔/") for k in
                      cmp_res["results"][0]["findings_delta"]),
              json.dumps(cmp_res, ensure_ascii=False)[:300])

        # ---- 6. 贡献模板 ----
        tpl = PACKS / "rule-template.json"
        tpl_data = json.loads(tpl.read_text(encoding="utf-8"))
        check("template parses with fields",
              {"id", "guidance", "status", "source_basis"} <= set(tpl_data))
        check("contributing doc exists", (PACKS / "CONTRIBUTING.md").is_file())

    print("")
    if FAILURES:
        print("FAILED: %d test(s): %s" % (len(FAILURES), ", ".join(FAILURES)))
        sys.exit(1)
    print("All maintenance tests passed.")


if __name__ == "__main__":
    main()
