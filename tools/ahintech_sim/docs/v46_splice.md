# V46: causal 24-hour window splicing

**Research-only offline contest optimization**, not network propagation or malware.

## Invariant

For a selected interval `[B, B+24)`, keep all original dispatches outside the
interval. Reserve unpacking already underway at `B`. At `B+24`, require exactly
the same active computers and unfinished unpacking completions as in the
original schedule. A replacement changes only dispatches inside the interval.

Because copies can transmit only at activation, an identical boundary state
makes the unchanged suffix valid. An independent validator checks every
candidate's emitted schedule in tests.

The bridge planner first uses a backward time-expanded causal search to
produce the mandatory activations at the right boundary; it then fills idle
periods with additional admissible transmissions. A candidate replaces the
incumbent only when it has **strictly more** completed activations.

## Runtime

V46 runs the entire V38 strategy, unchanged, before any window replacement.
Window exploration uses only part of the old conservative output reserve and
is enabled only for `n<=96`, `m>=50`, `k>=2`, at most 1800 directed adjacency
entries, and `n*m<=35000`. The allowed extra search is bounded by a separate
serialization reserve. On larger graphs V46 uses V38.

## Experimental observations

At a 0.65-second local budget, on 16 generated graphs with `n<=64`, V46
improved 7, matched 9, never worsened: +48 raw activations. On an independent
50-case set with longer unpacking times, 15 improved, 35 matched, none
worsened: +141 raw activations. On a selected 2-second comparison, a
32-computer/360-hour synthetic graph improved 994 -> 1026.

**These numbers are not official points.** Minor cross-build timing changes
can affect baseline results. The actual objective remains validation on the
hidden contest inputs. Do not claim the new method reaches the overall
optimum; it is a bounded anytime local improvement method.
