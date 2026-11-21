#!/usr/bin/env python3
"""Offline interactive judge for 'Sorting with a Liar'. No third-party packages."""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import random
import resource
import statistics
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


# The official 50 hidden tests are not available. These are synthetic profiles.
PROFILES = {
    "smoke": [
        (2, 0, 1), (3, 0, 3), (10, 0, 60), (32, 1, 500),
        (100, 3, 2000), (100, 30, 11000),
    ],
    "balanced": [
        (100, 1, 2000), (250, 5, 5500), (500, 10, 11000),
        (1000, 0, 11000), (1000, 10, 11000), (1000, 30, 11000),
    ],
    "adversarial": [
        (100, 30, 11000), (500, 30, 11000),
        (1000, 10, 11000), (1000, 30, 11000),
    ],
}
STRATEGIES = {
    "smoke": ("honest", "uniform", "first", "first_neighbor"),
    "balanced": ("honest", "uniform", "first", "last", "spaced", "midburst", "element"),
    "adversarial": ("first_neighbor", "middle_neighbor", "repeat_pair", "repeat_all", "element", "late_element", "late"),
}
SHAPES = ("random", "sorted", "reversed", "nearly_sorted", "zigzag", "blocks")


def case_seed(master: int, n: int, k: int, q: int, mode: str, trial: int) -> int:
    raw = f"{master}:{n}:{k}:{q}:{mode}:{trial}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def build_permutation(n: int, shape: str, seed: int) -> list[int]:
    rng = random.Random(seed)
    if shape == "random":
        return rng.sample(range(1, n + 1), n)
    if shape == "sorted":
        return list(range(1, n + 1))
    if shape == "reversed":
        return list(range(n, 0, -1))
    if shape == "nearly_sorted":
        p = list(range(1, n + 1))
        for _ in range(max(1, n // 20)):
            j = rng.randrange(n - 1)
            p[j], p[j + 1] = p[j + 1], p[j]
        return p
    if shape == "zigzag":
        p = []
        for j in range((n + 1) // 2):
            p.append(j + 1)
            if n - j != j + 1:
                p.append(n - j)
        return p
    if shape == "blocks":
        size = max(2, math.isqrt(n))
        blocks = [list(range(j, min(j + size, n + 1))) for j in range(1, n + 1, size)]
        rng.shuffle(blocks)
        return [x for block in blocks for x in block]
    raise ValueError(f"unknown permutation shape: {shape}")


class Liar:
    """Stateful adaptive judge: every returned lie consumes exactly one of k."""
    def __init__(self, strategy: str, pi: list[int], k: int, q: int, seed: int):
        self.strategy = strategy
        self.pi = pi
        self.k = k
        self.q = q
        self.lies = 0
        self.queries = 0
        self.selected: tuple[int, int] | None = None
        self.seen: set[tuple[int, int]] = set()
        self.rng = random.Random(seed ^ 0xBADC0FFEE0DDF00D)
        self.uniform = set(self.rng.sample(range(1, q + 1), min(k, q)))
        self.element_index = pi.index((len(pi) + 1) // 2) + 1
        self.middle_rank = max(1, len(pi) // 2)

    def respond(self, x: int, y: int) -> tuple[bool, bool, bool]:
        self.queries += 1
        truth = self.pi[x - 1] < self.pi[y - 1]
        pair = (min(x, y), max(x, y))
        repeated = pair in self.seen
        self.seen.add(pair)
        t = self.queries
        lie = False
        if self.lies < self.k:
            s = self.strategy
            if s == "honest":
                pass
            elif s == "uniform":
                lie = t in self.uniform
            elif s == "first":
                lie = t <= self.k
            elif s in {"last", "late"}:
                lie = t > self.q - self.k if s == "last" else t > (3 * self.q // 4)
            elif s == "spaced":
                lie = t in {1 + j * self.q // max(1, self.k) for j in range(self.k)}
            elif s == "midburst":
                lie = (self.q - self.k) // 2 < t <= (self.q + self.k) // 2
            elif s == "first_neighbor":
                if self.selected is None and abs(self.pi[x - 1] - self.pi[y - 1]) == 1:
                    self.selected = pair
                lie = self.selected == pair
            elif s == "middle_neighbor":
                lie = {self.pi[x - 1], self.pi[y - 1]} == {
                    self.middle_rank, self.middle_rank + 1
                }
            elif s == "repeat_pair":
                if self.selected is None and repeated:
                    self.selected = pair
                lie = pair == self.selected
            elif s == "repeat_all":
                lie = repeated
            elif s == "element":
                lie = self.element_index in (x, y)
            elif s == "late_element":
                lie = t > self.q // 2 and self.element_index in (x, y)
            else:
                raise ValueError(f"unknown liar strategy: {s}")
        if lie:
            self.lies += 1
        return not truth if lie else truth, truth, lie


class ReplayDivergence(ValueError):
    """The contestant issued different queries from a saved transcript."""


class RecordedLiar:
    """Replay exact recorded replies and require exactly the same ordered queries."""
    def __init__(self, pi: list[int], k: int, q: int, recorded: list[dict[str, Any]]):
        self.pi = pi
        self.k = k
        self.q = q
        self.recorded = recorded
        self.lies = 0
        self.queries = 0
        if len(recorded) > q:
            raise ValueError('recorded trace exceeds Q')
        seen_lies = 0
        for i, record in enumerate(recorded):
            x, y = int(record['x']), int(record['y'])
            if not (1 <= x <= len(pi) and 1 <= y <= len(pi) and x != y):
                raise ValueError('invalid recorded query')
            truth = pi[x - 1] < pi[y - 1]
            if record.get('t') != i + 1 or record['truth'] != ('YES' if truth else 'NO'):
                raise ValueError('recorded truth does not match permutation')
            if record['reply'] not in ('YES', 'NO'):
                raise ValueError('invalid recorded reply')
            lie = (record['reply'] == 'YES') != truth
            if bool(record['lie']) != lie:
                raise ValueError('inconsistent recorded lie flag')
            seen_lies += int(lie)
        if seen_lies > k:
            raise ValueError('recorded transcript exceeds lie budget')

    def respond(self, x: int, y: int) -> tuple[bool, bool, bool]:
        if self.queries >= len(self.recorded):
            raise ReplayDivergence(f'extra query {x} {y} beyond recorded transcript')
        expected = self.recorded[self.queries]
        if (x, y) != (expected['x'], expected['y']):
            raise ReplayDivergence(
                f'query #{self.queries + 1}: expected {expected["x"]} {expected["y"]},'
                f' got {x} {y}'
            )
        self.queries += 1
        truth = self.pi[x - 1] < self.pi[y - 1]
        said = expected['reply'] == 'YES'
        lied = not (truth == said)
        self.lies += int(lied)
        return said, truth, lied


def answer_diagnostics(
    pi: list[int], answer: list[int] | None, trace: list[dict[str, Any]]
) -> dict[str, Any]:
    """Explain wrong permutations: inversions and misplaced true neighbors."""
    n = len(pi)
    if answer is None or len(answer) != n or set(answer) != set(range(1, n + 1)):
        return {'valid_final_permutation': False}

    by_true_rank = [0] * (n + 1)
    for idx, rank in enumerate(pi, 1):
        by_true_rank[rank] = idx
    inverted_neighbors = [
        (rank, by_true_rank[rank], by_true_rank[rank + 1])
        for rank in range(1, n)
        if answer[by_true_rank[rank] - 1] > answer[by_true_rank[rank + 1] - 1]
    ]
    touched: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for e in trace:
        key = tuple(sorted((e['x'], e['y'])))
        touched[key][0] += 1
        touched[key][1] += int(e['lie'])
    items = sorted(range(n), key=lambda i: answer[i])
    bit = [0] * (n + 1)
    inversions = 0
    for j, i in enumerate(items):
        rank = pi[i]
        count_leq = 0
        z = rank
        while z:
            count_leq += bit[z]
            z -= z & -z
        inversions += j - count_leq
        z = rank
        while z <= n:
            bit[z] += 1
            z += z & -z
    return {
        'valid_final_permutation': True,
        'wrong_positions': sum(a != b for a, b in zip(pi, answer)),
        'max_rank_displacement': max(abs(a - b) for a, b in zip(pi, answer)),
        'kendall_inversions': inversions,
        'inverted_true_neighbor_pairs': len(inverted_neighbors),
        'inverted_neighbor_examples': [
            {
                'true_ranks': [rank, rank + 1],
                'indices': [u, v],
                'comparisons': touched[tuple(sorted((u, v)))][0],
                'lies_on_pair': touched[tuple(sorted((u, v)))][1],
            }
            for rank, u, v in inverted_neighbors[:20]
        ],
    }


@dataclass
class Result:
    solver: str
    suite: str
    n: int
    k: int
    q: int
    strategy: str
    shape: str
    trial: int
    seed: int
    correct: bool
    queries: int
    lies: int
    score: float
    wall_seconds: float
    reason: str
    wrong_positions: int | None = None
    kendall_inversions: int | None = None
    inverted_neighbor_pairs: int | None = None


def cpu_memory_limits(cpu_seconds: int, memory_mb: int):
    # Executed in the contestant child process on Linux, not in the judge.
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
    bytes_limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (bytes_limit, bytes_limit))


async def collect_stderr(reader: asyncio.StreamReader, cap: int = 8192) -> bytes:
    saved = bytearray()
    while chunk := await reader.read(4096):
        if len(saved) < cap:
            saved.extend(chunk[:cap - len(saved)])
    return bytes(saved)


async def run_case(
    solver: str, command: str, *, suite: str, n: int, k: int, q: int,
    strategy: str, shape: str, trial: int, seed: int,
    wall_limit: float = 8.0, cpu_limit: int = 2, memory_mb: int = 256,
    replay_trace: list[dict[str, Any]] | None = None,
) -> tuple[Result, dict[str, Any]]:
    """Execute one contestant with real pipes, enforce protocol and exact permutation."""
    pi = build_permutation(n, shape, seed)
    liar = RecordedLiar(pi, k, q, replay_trace) if replay_trace is not None else Liar(strategy, pi, k, q, seed)
    trace: list[dict[str, Any]] = []
    answer: list[int] | None = None
    reason = "missing_final_answer"
    start = time.monotonic()
    proc = await asyncio.create_subprocess_exec(
        command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        preexec_fn=lambda: cpu_memory_limits(cpu_limit, memory_mb),
        env={**os.environ, 'SORT_LIAR_SEED': str(seed)},
        limit=65536,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    # Drain stderr concurrently: diagnostics must never block the protocol.
    stderr_task = asyncio.create_task(collect_stderr(proc.stderr))
    proc.stdin.write(f"{n} {k} {q}\n".encode())
    await proc.stdin.drain()

    try:
        while True:
            remaining = wall_limit - (time.monotonic() - start)
            if remaining <= 0:
                reason = "wall_timeout"
                break
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                reason = "wall_timeout_or_unflushed_output"
                break
            if not raw:
                reason = "exited_without_final_answer"
                break
            words = raw.decode("utf-8", errors="replace").strip().split()
            if len(words) == 3 and words[0] == "?":
                try:
                    x, y = int(words[1]), int(words[2])
                except ValueError:
                    reason = "malformed_query"
                    break
                if x == y or not (1 <= x <= n and 1 <= y <= n):
                    reason = "invalid_query_indices"
                    break
                if liar.queries >= q:
                    reason = "query_limit_exceeded"
                    break
                said, truth, lied = liar.respond(x, y)
                trace.append({
                    "t": liar.queries, "x": x, "y": y,
                    "truth": "YES" if truth else "NO",
                    "reply": "YES" if said else "NO", "lie": lied,
                })
                proc.stdin.write(b"YES\n" if said else b"NO\n")
                await proc.stdin.drain()
            elif words and words[0] == "!":
                try:
                    answer = [int(w) for w in words[1:]]
                except ValueError:
                    reason = "noninteger_answer"
                    break
                if len(answer) != n or set(answer) != set(range(1, n + 1)):
                    reason = "not_a_permutation"
                elif answer == pi:
                    reason = "correct"
                else:
                    reason = "wrong_permutation"
                if replay_trace is not None and liar.queries != len(replay_trace):
                    reason = 'replay_query_count_mismatch'
                break
            else:
                reason = "malformed_protocol_output"
                break
    except ReplayDivergence as e:
        reason = 'replay_query_diverged'
        replay_divergence = str(e)
    except (BrokenPipeError, ConnectionResetError):
        reason = "broken_pipe"
    except ValueError as e:
        reason = f"invalid_output: {e}"
    finally:
        if proc.stdin and not proc.stdin.is_closing():
            if reason in {"invalid_query_indices", "query_limit_exceeded", "malformed_query"}:
                try:
                    proc.stdin.write(b"-1\n")
                    await asyncio.wait_for(proc.stdin.drain(), timeout=0.2)
                except (OSError, asyncio.TimeoutError):
                    pass
            proc.stdin.close()
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.25)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            if reason == "correct":
                reason = "did_not_exit_after_answer"
        extra = await proc.stdout.read(4096)
        if extra.strip() and reason == "correct":
            reason = "output_after_final_answer"
        stderr = await stderr_task

    elapsed = time.monotonic() - start
    assert liar.lies <= k, "judge emitted too many lies"
    assert liar.queries <= q, "judge exceeded Q"
    correct = reason == "correct" and proc.returncode == 0
    if reason == "correct" and proc.returncode != 0:
        reason = "nonzero_exit_after_answer"
    points = (1.5 + 0.5 * (q - liar.queries) / q) if correct else 0.0
    diagnostics = answer_diagnostics(pi, answer, trace)
    result = Result(
        solver=solver, suite=suite, n=n, k=k, q=q, strategy=strategy,
        shape=shape, trial=trial, seed=seed, correct=correct,
        queries=liar.queries, lies=liar.lies, score=points,
        wall_seconds=round(elapsed, 5), reason=reason,
        wrong_positions=diagnostics.get('wrong_positions'),
        kendall_inversions=diagnostics.get('kendall_inversions'),
        inverted_neighbor_pairs=diagnostics.get('inverted_true_neighbor_pairs'),
    )
    replay = {
        "solver": solver, "suite": suite, "n": n, "k": k, "q": q,
        "strategy": strategy, "shape": shape, "trial": trial,
        "seed": seed, "permutation": pi, "result": asdict(result),
        "answer": answer, "stderr": stderr.decode(errors="replace"),
        "trace": trace,
        "diagnostics": diagnostics,
        "replay_divergence": locals().get("replay_divergence"),
    }
    return result, replay


def render_markdown(rows: list[Result], failures: list[str], baseline: str = 'adaptive_v5') -> str:
    groups: dict[tuple[str, str], list[Result]] = defaultdict(list)
    for r in rows:
        groups[(r.solver, r.strategy)].append(r)
    lines = [
        "# Sorting with a Liar — synthetic judge",
        "",
        "These are reproducible synthetic tests, **not** the official hidden test suite.",
        "Scores use the original formula; a wrong answer scores zero.",
        "",
        "| Solver | Strategy | OK / total | Success rate | Total points | Mean points | Mean queries |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for (solver, strategy), group in sorted(groups.items()):
        ok = sum(r.correct for r in group)
        lines.append(
            f"| {solver} | {strategy} | {ok}/{len(group)} | {ok / len(group):.1%} "
            f"| {sum(r.score for r in group):.3f} | {statistics.mean(r.score for r in group):.4f} "
            f"| {statistics.mean(r.queries for r in group):.0f} |"
        )
    lines += ["", "## Overall", "", "| Solver | OK / total | Total points | Mean points |", "|---|---:|---:|---:|"]
    by_solver: dict[str, list[Result]] = defaultdict(list)
    for r in rows:
        by_solver[r.solver].append(r)
    for solver, group in sorted(by_solver.items()):
        lines.append(
            f"| {solver} | {sum(r.correct for r in group)}/{len(group)} "
            f"| {sum(r.score for r in group):.3f} "
            f"| {statistics.mean(r.score for r in group):.4f} |"
        )
    # Compare score on exactly the same synthetic cases and liar strategies.
    cases: dict[tuple[Any, ...], dict[str, Result]] = defaultdict(dict)
    for r in rows:
        key = (r.n, r.k, r.q, r.strategy, r.shape, r.trial, r.seed)
        cases[key][r.solver] = r
    if baseline in by_solver:
        lines += ["", f"## Paired comparison against `{baseline}`", "",
                  "Comparison uses matched generated cases, not the official hidden tests.", "",
                  "| Solver | Matched tests | Score delta | Fixed WA | New WA |",
                  "|---|---:|---:|---:|---:|"]
        for solver in sorted(by_solver):
            pairs = [(one[baseline], one[solver]) for one in cases.values()
                     if baseline in one and solver in one]
            lines.append(
                f"| {solver} | {len(pairs)} | {sum(s.score-b.score for b,s in pairs):+.3f} "
                f"| {sum(not b.correct and s.correct for b,s in pairs)} "
                f"| {sum(b.correct and not s.correct for b,s in pairs)} |"
            )
    lines += ["", "## Failure diagnostics", "",
              "| Solver | Wrong permutation | Single adjacent swap | Multi-inversion WA | Protocol / timeout / exit |",
              "|---|---:|---:|---:|---:|"]
    for solver, group in sorted(by_solver.items()):
        wrong = sum(r.reason == 'wrong_permutation' for r in group)
        single = sum(r.reason == 'wrong_permutation' and r.kendall_inversions == 1 for r in group)
        multi = sum(r.reason == 'wrong_permutation' and (r.kendall_inversions or 0) > 1 for r in group)
        other = sum(not r.correct and r.reason != 'wrong_permutation' for r in group)
        lines.append(f"| {solver} | {wrong} | {single} | {multi} | {other} |")
    lines += ["", "## First failure artifacts", ""]
    lines += [f"- `{path}`" for path in failures[:30]] or ["No failures in this run."]
    lines += ["", "Reproduce with `python3 olympiad/sort_liar/judge.py --replay <failure.json> --solver name=path`.\n"]
    return "\n".join(lines)


def get_solvers(raw: list[str]) -> dict[str, str]:
    out = {}
    for item in raw:
        if "=" not in item:
            raise ValueError("use --solver NAME=EXECUTABLE")
        name, path = item.split("=", 1)
        p = Path(path).resolve()
        if not name or not p.is_file():
            raise ValueError(f"solver does not exist: {item}")
        out[name] = str(p)
    if not out:
        raise ValueError("at least one --solver NAME=EXECUTABLE required")
    return out


async def main_async(args: argparse.Namespace) -> int:
    solvers = get_solvers(args.solver)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[Result] = []
    artifacts: list[str] = []
    failures_by_solver: dict[str, int] = defaultdict(int)
    recorded_failures: list[tuple[str, Result, dict[str, Any]]] = []

    if args.replay:
        payload = json.loads(Path(args.replay).read_text())
        cases = [(payload["n"], payload["k"], payload["q"], payload["strategy"],
                  payload["shape"], payload["trial"], payload["seed"])]
        expected_pi = payload["permutation"]
        if build_permutation(payload["n"], payload["shape"], payload["seed"]) != expected_pi:
            raise ValueError("replay permutation disagrees with case seed")
        suite = "replay"
        recorded_trace = payload.get("trace") if args.replay_mode == "exact" else None
        if args.replay_mode == "exact" and recorded_trace is None:
            raise ValueError("exact replay requires a saved query trace")
    else:
        suite = args.suite
        recorded_trace = None
        cases = []
        for n, k, q in PROFILES[suite]:
            for mode in STRATEGIES[suite]:
                for trial in range(args.runs):
                    seed = case_seed(args.seed, n, k, q, mode, trial)
                    if trial % args.shards != args.shard_index:
                        continue
                    shape = SHAPES[trial % len(SHAPES)]
                    cases.append((n, k, q, mode, shape, trial, seed))
    print(f"Suite={suite}, cases={len(cases)}, solvers={list(solvers)}, seed={args.seed}", flush=True)
    start = time.monotonic()
    for idx, (n, k, q, mode, shape, trial, seed) in enumerate(cases):
        for name, command in solvers.items():
            result, detail = await run_case(
                name, command, suite=suite, n=n, k=k, q=q,
                strategy=mode, shape=shape, trial=trial, seed=seed,
                wall_limit=args.wall_limit, cpu_limit=args.cpu_limit,
                memory_mb=args.memory_mb, replay_trace=recorded_trace,
            )
            rows.append(result)
            if not result.correct and failures_by_solver[name] < args.max_failure_traces:
                failures_by_solver[name] += 1
                file = out_dir / "failures" / f"{name}_{n}_{k}_{q}_{mode}_{trial}_{seed}.json"
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_text(json.dumps(detail, ensure_ascii=False, indent=2))
                artifacts.append(str(file.relative_to(out_dir)))
                if failures_by_solver[name] <= args.verify_failures:
                    recorded_failures.append((command, result, detail))
        if (idx + 1) % max(1, len(cases) // 10) == 0:
            print(f"Completed {idx + 1}/{len(cases)} cases ({time.monotonic()-start:.1f}s)", flush=True)

    replay_problems: list[str] = []
    for command, original, detail in recorded_failures:
        rerun, rerun_detail = await run_case(
            original.solver, command, suite=original.suite,
            n=original.n, k=original.k, q=original.q,
            strategy=original.strategy, shape=original.shape,
            trial=original.trial, seed=original.seed,
            wall_limit=args.wall_limit, cpu_limit=args.cpu_limit,
            memory_mb=args.memory_mb, replay_trace=detail['trace'],
        )
        if (rerun.reason, rerun.queries, rerun.lies, rerun.score) != (
            original.reason, original.queries, original.lies, original.score
        ) or rerun_detail['answer'] != detail['answer']:
            replay_problems.append(
                f"{original.solver}/{original.strategy}/{original.seed}: "
                f"{original.reason}/{original.queries} -> {rerun.reason}/{rerun.queries} "
                f"{rerun_detail.get('replay_divergence') or ''}"
            )
    with (out_dir / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        writer.writerows(asdict(r) for r in rows)
    (out_dir / "results.json").write_text(json.dumps([asdict(r) for r in rows], indent=2))
    md = render_markdown(rows, artifacts, args.baseline)
    (out_dir / "summary.md").write_text(md)
    print(md)
    if recorded_failures:
        print(f"Exact failure replay: {len(recorded_failures)-len(replay_problems)}/{len(recorded_failures)} matched")
    if replay_problems:
        print("REPLAY VERIFICATION FAILED:", *replay_problems, sep="\n- ")
        return 1
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as f:
            f.write(md + "\n")
    if args.fail_on_protocol:
        protocol_errors = {
            "malformed_query", "invalid_query_indices", "query_limit_exceeded",
            "not_a_permutation", "noninteger_answer", "malformed_protocol_output",
            "exited_without_final_answer", "wall_timeout", "wall_timeout_or_unflushed_output",
            "broken_pipe", "nonzero_exit_after_answer", "did_not_exit_after_answer",
            "output_after_final_answer", "missing_final_answer", "replay_query_diverged", "replay_query_count_mismatch",
        }
        if any(r.reason in protocol_errors or r.reason.startswith("invalid_output:") for r in rows):
            return 1
    return 0


def cli() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver", action="append", required=True, help="NAME=path/to/binary (repeatable)")
    parser.add_argument("--suite", choices=PROFILES.keys(), default="smoke")
    parser.add_argument("--runs", type=int, default=3, help="per configuration and strategy")
    parser.add_argument("--shards", type=int, default=1, help="split repetitions across N CI jobs")
    parser.add_argument("--shard-index", type=int, default=0, help="0-based shard number")
    parser.add_argument("--seed", type=int, default=794)
    parser.add_argument("--output", default="sort-liar-results")
    parser.add_argument("--replay", help="JSON failure file to reproduce")
    parser.add_argument("--replay-mode", choices=("exact", "strategy"), default="exact",
                        help="exact=recorded replies and queries, strategy=adaptive liar with same seed")
    parser.add_argument("--baseline", default="adaptive_v5", help="baseline solver for paired score deltas")
    parser.add_argument("--verify-failures", type=int, default=0,
                        help="exactly replay first N saved WA cases per solver")
    parser.add_argument("--wall-limit", type=float, default=8.0, help="wall guard, seconds")
    parser.add_argument("--cpu-limit", type=int, default=2, help="contestant CPU seconds, Linux")
    parser.add_argument("--memory-mb", type=int, default=256)
    parser.add_argument("--max-failure-traces", type=int, default=12)
    parser.add_argument("--fail-on-protocol", action="store_true")
    args = parser.parse_args()
    if (args.runs < 1 or args.runs > 500 or args.cpu_limit < 1
            or args.wall_limit <= 0 or args.verify_failures < 0
            or not 1 <= args.shards <= args.runs
            or not 0 <= args.shard_index < args.shards):
        parser.error("invalid runs or time limits")
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(cli())))
