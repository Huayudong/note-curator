Cache invalidation remains one of the hardest problems in distributed systems.

According to a March 2026 post-mortem by a storage team, their read path checks Redis first and falls back to MySQL; writes update the database and then delete the cache entry. This ordering is safe for most workloads, but the team recorded three data-inconsistency incidents in 2025, and two of them happened right after a failed cache deletion.

Note that the delete-after-write strategy only holds when downstream consumers tolerate brief inconsistency. For strong-consistency paths such as inventory deduction, the team does not recommend relying on the cache at all; they use database row locks directly. In their benchmarks, the cached read path reached p99 latency of 12ms, roughly a quarter of the database-only baseline, while the write path was 18% slower due to the extra deletion step.

The post ends with a quote from another engineer: "There is no silver bullet for cache consistency, only trade-offs." That line fairly summarizes the current community consensus.
