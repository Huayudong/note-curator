Experiment: batch size versus SQLite WAL write throughput.

Setup: SQLite 3.44 in WAL mode, page_size 4096, a test table with five text columns.
Procedure: insert with batch sizes 1, 32, 128, and 512; three runs each, take the median.
Environment: Windows 11, NVMe SSD, Python 3.12, serial execution in one process.

Results:
- batch 1: about 2,100 rows/s
- batch 32: about 26,000 rows/s
- batch 128: about 31,000 rows/s
- batch 512: about 31,500 rows/s, nearly no gain over 128, with clearly higher memory use

Surprise: at batch 512 we occasionally saw checkpoint stalls with 200ms-scale latency spikes, probably related to the default WAL auto-checkpoint threshold of 1,000 pages; not investigated further.

Preliminary conclusion: 128 is the knee of the curve on this machine; beyond 128 throughput stays flat. The result may only hold for this hardware and row width; rerun on HDD or wider rows.
