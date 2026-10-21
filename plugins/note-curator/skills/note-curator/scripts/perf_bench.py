#!/usr/bin/env python3
"""
perf_bench.py — B11-01/02 性能基准：合成库上的索引/检索/扫描计时。

方法：
  - 合成 vault：N 篇笔记（确定性伪文本，每 20 篇埋一个唯一关键词供检索命中）
  - 计时项：全量索引、增量索引（修改 10%、删除 5%）、检索 10 次、scan_vault 全扫
  - 内存：index_vault 构建期 tracemalloc 峰值
报告写到 --out（JSON + Markdown），默认打印摘要。

这是可复跑的基准工具（B11-01 要求公开机器/数据规模以便复跑）；
默认 N=300 保证秒级完成，万级库请显式 --notes 10000。

用法：
    python perf_bench.py --notes 300 [--out report.json] [--json]
"""

import argparse
import json
import shutil
import sys
import time
import tracemalloc
from pathlib import Path

import nc_core  # noqa: F401  B01-02: 统一 UTF-8 标准流与共享基础工具

SENTENCES = [
    "缓存失效策略要与业务一致性要求一起定。",
    "批量写入在 128 附近出现吞吐拐点，超过后几乎持平。",
    "倒排索引解决了关键词检索的规模问题。",
    "复盘的价值在于把判断依据留在纸面上。",
    "TTL 抖动把失效时间摊开，避免集中回源。",
    "文档搜索需要同时处理检索、分词与排序三个问题。",
]
KEYWORD = "唯一锚点词{:04d}"


def synthesize(vault, n, size_chars):
    vault.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        sub = vault / ("目录%02d" % (i % 7))
        sub.mkdir(exist_ok=True)
        keyword = KEYWORD.format(i) if i % 20 == 0 else ""
        chunks = []
        total = 0
        while total < size_chars:
            for s in SENTENCES:
                chunks.append(s)
                total += len(s)
                if total >= size_chars:
                    break
        body = "%s\n\n%s" % (keyword or ("笔记 %04d" % i), "。".join(chunks) + "。")
        (sub / ("笔记%04d.md" % i)).write_text("# 笔记 %04d\n\n%s" % (i, body),
                                               encoding="utf-8")


def modify_some(vault, n):
    changed = 0
    for i in range(0, n, 10):  # 10% 修改
        p = vault / ("目录%02d" % (i % 7)) / ("笔记%04d.md" % i)
        if p.is_file():
            with open(p, "a", encoding="utf-8") as handle:
                handle.write("\n\n追加的更新段落，用于增量索引。")
            changed += 1
    for i in range(5, n, 20):  # 5% 删除
        p = vault / ("目录%02d" % (i % 7)) / ("笔记%04d.md" % i)
        if p.is_file():
            try:
                os_remove(p)
            except OSError:
                pass
    return changed


def os_remove(path):
    import os
    os.remove(str(path))


def main():
    ap = argparse.ArgumentParser(description="性能基准")
    ap.add_argument("--notes", type=int, default=300)
    ap.add_argument("--size", type=int, default=800, help="每篇正文目标字符数")
    ap.add_argument("--out", help="报告 JSON 输出路径")
    ap.add_argument("--keep", action="store_true", help="保留合成库（默认删除）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tmp = Path(nc_core.data_root()) / "bench-tmp" / nc_core.new_run_id()
    vault = tmp / "vault"
    index_path = tmp / "index.json"
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import index_vault
    import search_notes
    import scan_vault

    t0 = time.perf_counter()
    synthesize(vault, args.notes, args.size)
    synth_seconds = time.perf_counter() - t0

    tracemalloc.start()
    t0 = time.perf_counter()
    index = index_vault_scan(vault, index_path, incremental=False)
    full_index_seconds = time.perf_counter() - t0
    peak_mb = tracemalloc.get_traced_memory()[1] / (1024 * 1024)
    tracemalloc.stop()

    changed = modify_some(vault, args.notes)
    t0 = time.perf_counter()
    index = index_vault_scan(vault, index_path, incremental=True)
    incr_index_seconds = time.perf_counter() - t0

    queries = [KEYWORD.format(i) for i in range(0, args.notes, max(args.notes // 10, 1))]
    t0 = time.perf_counter()
    hits = 0
    for q in queries:
        hits += 1 if search_notes.search(index, q, top=3) else 0
    search_seconds = time.perf_counter() - t0

    t0 = time.perf_counter()
    scan_vault.scan_vault(vault, max_body=400)
    scan_seconds = time.perf_counter() - t0

    report = {
        "notes": args.notes,
        "size_chars": args.size,
        "synthesize_seconds": round(synth_seconds, 3),
        "full_index_seconds": round(full_index_seconds, 3),
        "full_index_peak_mb": round(peak_mb, 2),
        "modified_for_incremental": changed,
        "incremental_index_seconds": round(incr_index_seconds, 3),
        "search_queries": len(queries),
        "search_seconds": round(search_seconds, 3),
        "search_hit_groups": hits,
        "scan_vault_seconds": round(scan_seconds, 3),
    }
    if not args.keep:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    else:
        print("[KEEP] 合成库保留在：%s" % vault, file=sys.stderr)
    if args.out:
        nc_core.atomic_write_text(args.out, json.dumps(report, ensure_ascii=False,
                                                       indent=2))
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report, ensure_ascii=False))
    sys.exit(0)


def index_vault_scan(vault, out_path, incremental):
    import index_vault as iv
    old_files = {}
    if incremental and out_path.is_file():
        try:
            old = json.loads(out_path.read_text(encoding="utf-8"))
            if old.get("schema") == iv.SCHEMA:
                old_files = old.get("files", {})
        except (OSError, ValueError):
            old_files = {}
    files = {}
    for md in iv.iter_notes(vault):
        rel = md.relative_to(vault).as_posix()
        try:
            text = md.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        digest = iv.file_hash(text)
        prior = old_files.get(rel)
        if prior and prior.get("hash") == digest:
            files[rel] = prior
            continue
        files[rel] = iv.build_entry(md, rel, text, iv.DEFAULT_CHUNK)
    index = {"schema": iv.SCHEMA, "vault": str(vault),
             "generated_at": nc_core.now_iso(), "files": files}
    nc_core.atomic_write_text(out_path, json.dumps(index, ensure_ascii=False))
    return index


if __name__ == "__main__":
    main()
