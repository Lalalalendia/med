# V47 — deeper causal window repair

Extends V46 with 256 candidate repairs per window and a third sweep through
candidate boundaries. The underlying complete V38 baseline is still executed
before local repair and is never replaced by a worse candidate. No external
optimizers are needed by the C++23 binary.

## Empirical checks (generated graphs only)

- 16 standard cases at a local 0.65 s budget: 10 improvements / 1 regression /
  5 ties vs V38, net +80 raw completed activations.
- 50 independent graphs with longer unpacking delays at the same budget:
  16 improvements / 0 regressions / 34 ties, net +176 activations vs V38.
- At a full 2.0 s budget, six targeted cases compared against V46 yielded
  5 improvements and 1 tie, net +22, peak observed wall-clock 1.916 s.
- Independent event validator accepted all reported schedules.

The isolated -1 loss in a standard sample was a comparison between two
separate time-limited binaries, not a rejected repair: the V38 incumbent
inside V47 is never deliberately replaced by an inferior output. Official
hidden-judge score is unknown. Time margin is limited; avoid increasing the
search budget without a runner-specific safety check.
