"""Independent, offline specification and output validator for contest task B.

No sockets, processes or real-world spreading: this module operates on integers.
Time in solutions is ABSOLUTE, starting at the given x, not relative to x.
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from pathlib import Path


class InvalidInput(ValueError):
    pass


class InvalidSolution(ValueError):
    pass


@dataclass(slots=True)
class Problem:
    n: int
    p: int                   # zero-based internally
    k: int
    x: int
    m: int
    a: list[int]
    b: list[int]
    t: list[int]
    adj: list[list[int]]     # zero-based internally

    @classmethod
    def parse(cls, data: str | bytes, *, strict: bool = True) -> 'Problem':
        if isinstance(data, bytes):
            data = data.decode('ascii')
        try:
            it = iter(map(int, data.split()))
            n, p, k = next(it), next(it), next(it)
            x, m = next(it), next(it)
            a, b = [], []
            for _ in range(n):
                aa, bb = next(it), next(it)
                a.append(aa)
                b.append(bb)
            t = [next(it) for _ in range(n)]
            adj = []
            for _ in range(n):
                row = []
                while True:
                    v = next(it)
                    if v == 0:
                        break
                    row.append(v - 1)
                adj.append(row)
            if strict:
                try:
                    next(it)
                except StopIteration:
                    pass
                else:
                    raise InvalidInput('Unexpected trailing input')
        except (StopIteration, ValueError) as exc:
            if isinstance(exc, InvalidInput):
                raise
            raise InvalidInput('Malformed input') from exc
        p -= 1
        obj = cls(n, p, k, x, m, a, b, t, adj)
        obj.validate_definition()
        return obj

    def validate_definition(self) -> None:
        if not (1 <= self.n <= 100_000 and 0 <= self.p < self.n):
            raise InvalidInput('Invalid n or initial vertex')
        if not (1 <= self.k <= self.n and 0 <= self.x <= 23 and 1 <= self.m <= 1_000_000):
            raise InvalidInput('Invalid k, x or m')
        if self.n * self.m > 1_000_000:
            raise InvalidInput('n*m exceeds 1,000,000')
        if not all(len(arr) == self.n for arr in (self.a, self.b, self.t, self.adj)):
            raise InvalidInput('Incorrect number of rows')
        if not all(0 <= a <= 23 for a in self.a):
            raise InvalidInput('Invalid opening hour')
        if not all(1 <= b <= 23 for b in self.b):
            raise InvalidInput('Invalid working period')
        if not all(1 <= t <= 23 for t in self.t):
            raise InvalidInput('Invalid unpacking time')
        if not self.is_on(self.p, self.x):
            raise InvalidInput('Starting computer is not on at x')
        edges = 0
        row_sets = []
        for u, row in enumerate(self.adj):
            if len(row) != len(set(row)) or any(v == u or v < 0 or v >= self.n for v in row):
                raise InvalidInput(f'Invalid or duplicate neighbor in row {u+1}')
            edges += len(row)
            row_sets.append(set(row))
        if edges > 1_000_000:
            raise InvalidInput('Too many directed edge entries')
        for u, row in enumerate(self.adj):
            for v in row:
                if u not in row_sets[v]:
                    raise InvalidInput(f'Graph is not undirected: {u+1}-{v+1}')

    def is_on(self, v: int, time: int) -> bool:
        return (time - self.a[v]) % 24 <= self.b[v]

    def eligible_start(self, v: int, time: int) -> bool:
        return (time - self.a[v]) % 24 + self.t[v] <= self.b[v]

    def to_text(self) -> str:
        lines = [f'{self.n} {self.p+1} {self.k}', f'{self.x} {self.m}']
        lines.extend(f'{a} {b}' for a, b in zip(self.a, self.b))
        lines.extend(map(str, self.t))
        for row in self.adj:
            lines.extend(str(v+1) for v in row)
            lines.append('0')
        return '\n'.join(lines) + '\n'


def parse_solution(raw: str | bytes, *, max_events: int) -> tuple[int, list[tuple[int, int, int]]]:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode('ascii')
        except UnicodeDecodeError as exc:
            raise InvalidSolution('Output must be ASCII text') from exc
    tokens = raw.split()
    if not tokens:
        raise InvalidSolution('Missing first line with A')
    try:
        reported = int(tokens[0])
    except ValueError as exc:
        raise InvalidSolution('A is not an integer') from exc
    if not 1 <= reported <= max_events:
        raise InvalidSolution(f'A must be in [1, {max_events}], got {reported}')
    if len(tokens) != 1 + 3 * (reported - 1):
        raise InvalidSolution(f'Expected {reported-1} triples, got {(len(tokens)-1)//3}')
    try:
        ints = map(int, tokens[1:])
        triples = list(zip(ints, ints, ints))
    except ValueError as exc:
        raise InvalidSolution('Noninteger event field') from exc
    return reported, triples


def validate_output(problem: Problem, raw: str | bytes) -> dict:
    """Verify ALL stated rules, including concurrent starts and repeated infections.

    The output is allowed to be unordered. Only successful transmissions are
    listed; absent transmissions are interpreted as never having been sent.
    """
    n, x, m = problem.n, problem.x, problem.m
    reported, events = parse_solution(raw, max_events=n*m)
    events.sort(key=lambda item: item[2])  # send times are absolute
    available_at = [x] * n
    # A bit for each (relative hour, computer), at most one completion per cell.
    active = bytearray(n*m)
    active[problem.p] = 1   # activation at hour x
    quotas = array('I', [0]) * (n*m)
    neighbors = [set(row) for row in problem.adj]
    last = x + m - 1
    for idx, (u1, v1, s) in enumerate(events, 1):
        u, v = u1-1, v1-1
        if not (0 <= u < n and 0 <= v < n):
            raise InvalidSolution(f'Event {idx}: vertex out of range')
        if not (x <= s <= last):
            raise InvalidSolution(f'Event {idx}: dispatch time {s} outside horizon [{x},{last}]')
        if v not in neighbors[u]:
            raise InvalidSolution(f'Event {idx}: no edge {u1}-{v1}')
        state = (s-x)*n + u
        if not active[state]:
            raise InvalidSolution(f'Event {idx}: source {u1} did not activate at time {s}')
        quotas[state] += 1
        if quotas[state] > problem.k:
            raise InvalidSolution(f'Event {idx}: source {u1} sent more than k copies at {s}')
        if s < available_at[v]:
            raise InvalidSolution(f'Event {idx}: target {v1} is occupied until {available_at[v]}')
        if not problem.eligible_start(v, s):
            raise InvalidSolution(f'Event {idx}: target {v1} would be off before completion')
        completion = s + problem.t[v]
        if completion > last:
            raise InvalidSolution(f'Event {idx}: completion at {completion} outside horizon')
        completion_state = (completion-x)*n + v
        if active[completion_state]:
            raise InvalidSolution(f'Event {idx}: second activation of {v1} at {completion}')
        active[completion_state] = 1
        available_at[v] = completion  # available at the exact completion instant
    return {'A': reported, 'transmissions': len(events),
            'utilization_of_space_time': reported/(n*m), 'n': n, 'm': m}


def validate_files(problem_path: Path, output_path: Path) -> dict:
    return validate_output(Problem.parse(problem_path.read_bytes()), output_path.read_bytes())
