Quarterly retrospective: two rework cycles on the document-search feature.

Timeline:
- Early January: took the request for "search by title and tag", estimated three days.
- Mid January: v1 shipped using an in-memory linear scan.
- Early February: users reported over 2 seconds of latency at 5,000 documents; first rework introduced an inverted index.
- March: Chinese word segmentation was still missing, hit rate around 40%, second rework.

Judgment basis: both reworks trace back to the same mistake — I treated "search" as one problem when it is actually three: retrieval, segmentation, and ranking. v1 only solved retrieval.

Numbers: the first rework took 5 days, the second 3 days. Breaking the problem into three parts up front would have cost about 6 days in total, two days less than what actually happened.

Conclusion: when taking a requirement, first ask how many sub-problems it contains, instead of estimating hours first. This lesson comes from this very retrospective; whether it generalizes beyond search features needs more cases.
