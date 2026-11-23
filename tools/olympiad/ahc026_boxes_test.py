import random
import statistics
import subprocess
import sys
import time

BINARY = sys.argv[1]
N, M = 200, 10


def valid_and_energy(initial, output):
    stacks = [list(stack) for stack in initial]
    expected_removal = 1
    energy = 0
    lines = output.strip().splitlines()
    assert 200 <= len(lines) <= 5000, len(lines)
    for line in lines:
        a = line.split()
        assert len(a) == 2, line
        value, to = map(int, a)
        assert 1 <= value <= N and 0 <= to <= M
        if to == 0:
            assert value == expected_removal, (value, expected_removal)
            assert any(stack and stack[-1] == value for stack in stacks), value
            for stack in stacks:
                if stack and stack[-1] == value:
                    stack.pop()
                    break
            expected_removal += 1
        else:
            source = next(
                (i for i, stack in enumerate(stacks) if value in stack),
                None,
            )
            assert source is not None and source != to - 1, (value, to)
            position = stacks[source].index(value)
            moved = stacks[source][position:]
            del stacks[source][position:]
            stacks[to - 1].extend(moved)
            energy += len(moved) + 1
    assert expected_removal == 201 and not any(stacks)
    return energy, len(lines)


def shortest_stack_baseline(initial):
    stacks = [list(stack) for stack in initial]
    spent = 0
    for value in range(1, N + 1):
        source = next(i for i in range(M) if value in stacks[i])
        position = stacks[source].index(value)
        if position + 1 < len(stacks[source]):
            destination = min(
                (i for i in range(M) if i != source),
                key=lambda i: (len(stacks[i]), i),
            )
            moving = stacks[source][position + 1:]
            del stacks[source][position + 1:]
            stacks[destination].extend(moving)
            spent += len(moving) + 1
        assert stacks[source].pop() == value
    return spent


rng = random.Random(20261117)
energy_base = []
energy_smart = []
operations = []
elapsed = 0.0
for test_case in range(150):
    boxes = list(range(1, N + 1))
    rng.shuffle(boxes)
    initial = [boxes[i * 20:(i + 1) * 20] for i in range(M)]
    case_input = "200 10\n" + "".join(
        " ".join(map(str, stack)) + "\n" for stack in initial
    )

    start = time.perf_counter()
    result = subprocess.run(
        [BINARY],
        input=case_input,
        text=True,
        capture_output=True,
        timeout=2,
        check=True,
    )
    elapsed += time.perf_counter() - start
    optimized, count = valid_and_energy(initial, result.stdout)
    baseline = shortest_stack_baseline(initial)
    assert optimized <= baseline, (test_case, optimized, baseline)
    energy_base.append(baseline)
    energy_smart.append(optimized)
    operations.append(count)

base_avg = statistics.mean(energy_base)
smart_avg = statistics.mean(energy_smart)
saved = (base_avg - smart_avg) / base_avg * 100
print(f"VALID: 150/150 seeds; output moves 200..{max(operations)}")
print(f"BASELINE energy mean: {base_avg:.2f}; score: {10000-base_avg:.2f}")
print(f"IMPROVED energy mean: {smart_avg:.2f}; score: {10000-smart_avg:.2f}")
print(f"IMPROVEMENT mean-energy: {saved:.2f}%")
print(f"TOTAL WALL TIME 150 runs: {elapsed:.3f}s")
assert saved > 10, saved
