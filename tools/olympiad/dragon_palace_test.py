import collections
import random
import subprocess
import sys
import time

BINARY = sys.argv[1]
random.seed(20261117)


def run(n, roads, k, t, timeout=8):
    data = f"{n} {len(roads)} {k} {t}\n"
    data += "".join(f"{u+1} {v+1} {l} {s}\n" for u, v, l, s in roads)
    proc = subprocess.run(
        [BINARY], input=data, text=True, capture_output=True, timeout=timeout, check=True
    )
    out = proc.stdout.strip()
    assert out.isdigit(), (data, proc.stdout, proc.stderr)
    return int(out)


def reference(n, roads, k, t):
    if n == 1:
        return 0

    N = (t + 1) * n + 1
    sink = N - 1
    adj = [[] for _ in range(N)]

    def add(u, v, cap):
        adj[u].append([v, cap, len(adj[v])])
        adj[v].append([u, 0, len(adj[u]) - 1])

    for time in range(t + 1):
        if time > 0:
            for v in range(n):
                add((time - 1) * n + v, time * n + v, k)
        for u, v, l, s in roads:
            if time + l <= t:
                add(time * n + u, (time + l) * n + v, s)

        add(time * n + n - 1, sink, k)

    def flow_limit(deadline):
        # Build a clean graph with only times through deadline.
        nn = (deadline + 1) * n + 1
        target = nn - 1
        graph = [[] for _ in range(nn)]

        def edge(u, v, cap):
            graph[u].append([v, cap, len(graph[v])])
            graph[v].append([u, 0, len(graph[u]) - 1])

        for tt in range(deadline + 1):
            if tt > 0:
                for v in range(n):
                    edge((tt - 1) * n + v, tt * n + v, k)
            for u, v, l, s in roads:
                if tt + l <= deadline:
                    edge(tt * n + u, (tt + l) * n + v, s)
            edge(tt * n + n - 1, target, k)

        total = 0
        while total < k:
            prev = [None] * nn
            prev[0] = (-1, -1)
            q = collections.deque([0])
            while q and prev[target] is None:
                v = q.popleft()
                for ix, (to, cap, _) in enumerate(graph[v]):
                    if cap > 0 and prev[to] is None:
                        prev[to] = (v, ix)
                        q.append(to)
            if prev[target] is None:
                break
            amt = k - total
            cur = target
            while cur != 0:
                v, ix = prev[cur]
                amt = min(amt, graph[v][ix][1])
                cur = v
            cur = target
            while cur != 0:
                v, ix = prev[cur]
                back = graph[v][ix][2]
                graph[v][ix][1] -= amt
                graph[cur][back][1] += amt
                cur = v
            total += amt
        return total

    final = flow_limit(t)
    if final < k:
        return k - final
    for time in range(t + 1):
        if flow_limit(time) == k:
            return time
    raise AssertionError("unreachable")


sample = [(0, 1, 2, 2), (1, 2, 1, 1), (1, 3, 1, 1), (3, 4, 2, 4), (2, 4, 2, 4)]
assert run(5, sample, 10, 10) == 9
assert run(1, [(0, 0, 1, 1)] if False else [], 3, 4) == 0
assert run(2, [(0, 1, 1, 2)], 5, 3) == 3
assert run(2, [(0, 1, 2, 1)], 5, 3) == 3
assert run(2, [(1, 0, 1, 1)], 5, 3) == 5

for test_id in range(1200):
    n = random.randrange(1, 7)
    t = random.randrange(1, 10)
    k = random.randrange(1, 15)
    candidates = [(u, v) for u in range(n) for v in range(n) if u != v]
    random.shuffle(candidates)
    roads = [
        (u, v, random.randrange(1, 5), random.randrange(1, 6))
        for u, v in candidates[:random.randrange(1, min(len(candidates), 12) + 1)]
    ]
    actual = run(n, roads, k, t)
    expected = reference(n, roads, k, t)
    assert actual == expected, (test_id, n, roads, k, t, actual, expected)

print("Reference tests: sample, edges, 1200 random cases PASS")

# Worst permitted number of time-expanded nodes and many road traversals.
# n*t <= 10000 and m <= 10000.
n, t, k = 100, 100, 10000
roads = [(i, i+1, 1, 1) for i in range(99)]
used = {(i, i+1) for i in range(99)}
while len(roads) < 9000:
    u, v = random.randrange(n), random.randrange(n)
    if u == v or (u, v) in used:
        continue
    used.add((u, v))
    roads.append((u, v, random.randint(1, 200), random.randint(1, 3000)))
start = time.perf_counter()
got = run(n, roads, k, t, timeout=25)
duration = time.perf_counter() - start
print(f"Stress: n={n}, m={len(roads)}, t={t}, k={k}, result={got}, wall={duration:.3f}s")
assert duration < 15, "Very slow execution"
