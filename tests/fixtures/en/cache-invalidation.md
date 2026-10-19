---
author: your-name
created: 2026-10-19
tags: [backend, caching, redis]
---

# Cache invalidation strategies

## Why this keeps biting people

Most teams treat invalidation as an afterthought, and that is exactly when it bites. The cache looks fine in staging, then a busy Friday afternoon arrives and half the reads serve stale data. I have seen this movie a few times, and the ending is always the same: someone disables the cache entirely and the database quietly catches fire.

The root cause is rarely exotic. Usually the write path updates the database but forgets the cache, or the TTL was tuned for a workload that no longer exists.

## The three working options

**Write-through.** Every write updates the cache before, or right after, committing to the database. It is simple and predictable, although the cache now sits on the critical path, so its latency becomes your write latency.

**TTL with jitter.** Set a modest TTL, add random jitter of maybe ten to twenty percent, and accept occasionally serving data that is a few seconds old. For most read-heavy workloads this is honestly good enough, and it requires almost no code.

**Explicit invalidation.** Subscribe to change events and delete or refresh the affected keys. This is the precise option, but it is also the fragile one; a missed event means stale data with no TTL to save you.

## What I actually recommend

Start with TTL plus jitter, because it survives outages and code you forgot about. Add explicit invalidation only for the handful of keys where staleness genuinely costs money. Measure first, though — in my experience the "we need perfect freshness" list is usually shorter than people expect.

> Rule of thumb: if you cannot explain what happens when the cache is wrong for thirty seconds, you have not designed the invalidation yet.
