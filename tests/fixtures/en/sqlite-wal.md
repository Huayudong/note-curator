---
author: your-name
created: 2026-10-19
tags: [database, sqlite, performance]
---

# SQLite WAL mode in practice

## The experiment

We had a reporting job that wrote roughly 40,000 rows into SQLite per run, and the default rollback-journal mode made each run painfully slow. The question was simple: does switching to WAL actually help, or does it just move the pain somewhere else?

Setup: the same dataset, the same machine, three configurations — default journal mode, WAL with default settings, and WAL with `synchronous=NORMAL`.

## Results

Default mode finished the load in about 95 seconds. WAL with defaults cut that to 61 seconds, and WAL with `synchronous=NORMAL` reached 38 seconds. Reads during the load stopped blocking entirely, which honestly mattered more than the raw numbers; the dashboard that polled the database used to freeze for minutes.

| config | load time | reads during load |
|--------|-----------|-------------------|
| default | 95 s | blocked |
| WAL default | 61 s | concurrent |
| WAL + NORMAL | 38 s | concurrent |

One caveat: `synchronous=NORMAL` means a power loss can lose the last committed transactions. For a cache-style dataset that trade seemed fine; for billing data it would not be.

## Takeaway

WAL is not magic, but for write-heavy, read-while-writing workloads it is close to a free win. Set it once per connection, keep transactions reasonably short, and checkpoint periodically so the `-wal` file does not grow without bound.
