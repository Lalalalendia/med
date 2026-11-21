# V51 — Temporal deferral with guaranteed future senders

Experimental standalone C++23 solver for numerical contest task B.

## Algorithm

The existing V47 greedy planner fills almost every feasible receiver immediately.
V51 introduces two optional modes, 36/37, which can **decline a feasible
transmission at the present hour** when an already scheduled future activation
of another adjacent sender gives the same receiver a better completion phase.
It does **not** delay a transmission, which would violate the immediate-send
rule. It chooses not to send now and may send from the later activated source.

For each current hour in those modes, the solver scans at most 50,000 future
neighbor incidences in an eight-hour lookahead and remembers the earliest
eligible future sender for a receiver. A receiver is deferred only if:

1. A source is already scheduled to activate at `T+d`, with `0 < d < t[v]`.
2. The receiver can start its unpacking legally at `T+d`.
3. The estimated continuation score at `T+d` exceeds the one at `T`
   by a mode-specific margin.

Those two modes replace *duplicated* early passes, leaving the other original
candidate modes and V47's certified window splicing available. All candidate
schedules are still checked through the independent offline validator.

An ablation build with `-DAHINTEK_ABLATION_NO_TEMPORAL_DEFER` disables only
this decision while preserving the same mode list and weights.

## Evaluation (synthetic, not official)

- Tuning set (seed 20261127), 32 cases, budget 0.45s: +2,478 activations vs V47,
  9 wins / 23 ties / 0 losses.
- Second set (seed 20261128), 32 cases, budget 0.45s: +6,358,
  9 wins / 23 ties / 0 losses.
- Third seed (20261130), 32 cases, budget 0.45s: +4,725,
  10 wins / 21 ties / 1 loss (−1).
- Independent 2.0s seed (20261129), 32 cases: **+3,270**,
  10 wins / 21 ties / 1 loss (−2).
- Additional 2.0s seed (20261130), first 16 cases: **+572**,
  3 wins / 13 ties / 0 losses.
- Selected ablation case (seed 20261128, index 22, n=150, m=700):
  same schedule/weights *without temporal defer* produced 5,596,
  *with temporal defer* 10,100 activations at budget 0.45s.
- Stress: n*m=1,000,000 for n=100000,m=10, n=5000,m=200, and n=1000,m=1000.
  All checked solutions valid under the task's 2s/256 MiB limits locally.

Synthetic sums are NOT official judging points; these samples were examined
while developing the algorithm. Results vary by CPU and execution budget.
V47's official test score is about 83.3913 and V51 has not been submitted.

## Next

Run official judge after CI. Compare by hidden test ID rather than aggregate
alone. If low-scoring IDs 40, 46, 62 remain unchanged, their bottleneck lies
outside this temporal deferral mechanism and requires a different planner.
