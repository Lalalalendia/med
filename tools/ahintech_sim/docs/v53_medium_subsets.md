# Ahintek B V53 — 13–24-device joint subset beam

**Official result is unknown.** This is an offline research candidate extending V52 (which scored ~85.173575 on official tests). V51/V52 remain intact; no deployment or repository main merge.

## Algorithm

For connected graphs of 13–24 vertices with horizon at most 180 hours, construct a bounded time-expanded beam over **whole sets** of recipients at each activation time. A state packs remaining unpacking durations in 5 bits per vertex (`unsigned __int128`, at most 120 bits). This tracks simultaneous recipients and competition for future activations across successive hours.

For each state, select 9–10 currently feasible recipient candidates, with several shortlist variants across beam states. Check feasibility of every subset via *capacitated bipartite matching* from active senders to targets, respecting `k` and unique reception. If the entire candidate set is matchable, every subset is also feasible (downward closure), so skip repeated matching. Otherwise, build feasible subsets by dynamic programming with exact augmenting paths. Keep 28–48 high-potential states per hour, keyed by the resulting active/busy state. Reconstruct the exact parent-to-target transmissions for the selected path.

The beam has an additional deadline of **0.42 seconds**, leaving the rest of the judge's ~2-second budget to the original V52 methods. The new proposal replaces the incumbent only when it contains strictly more valid activations. Note that the competing binary can still occasionally outperform V53 because each binary follows a different time-bounded search path.

## Synthetic results (official judge NOT used)

Comparison against standalone V52 at **2.0 s** each, with independently validated outputs:

| Holdout seed | Cases | Wins | Ties | Losses | Net activations |
|---|---:|---:|---:|---:|---:|
| 20270120 | 20 | 9 | 10 | 1 (−1) | **+28** |
| 20270129 | 20 | 8 | 11 | 1 (−1) | **+26** |
| **Total** | **40** | **17** | **21** | **2** | **+54** |

Additional **0.65-second** development set (seed 20270116): 6 improved, 13 tied, one worsened (−3), net +10. Two deterministic fixtures with input SHA256 fingerprints show (n15,m48,k4) V52=75 to V53=78 and (n14,m48,k2) V52=93 to V53=96 under 0.65-second budget.

Stress tests: dense n24/m180, sparse n2000/m500, chain n100000/m10 all produced independently validated outputs. The two large-`n` cases use V52 unchanged; the dense medium case produced the same total.

**Limits:** These tests do not establish any likely official point gain. On official hidden inputs, V52 differed from V51 on only one tiny scoring fraction. To close the remaining ~3.3 points to the earlier leader, a method applicable to substantially larger graphs is still needed. V53 is an incremental proof-of-concept for truly joint temporal decisions, not the general large-graph answer.
