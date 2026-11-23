#!/usr/bin/env python3
"""Heuristic solution for E. Ordering Transactions, Python 3 / PyPy3.

Builds an implicit dependency graph: if transaction i reads a cell written by j,
then i must precede j.  It strips graph sources and sinks and breaks only
remaining cycles.  No O(n^2) dependency graph is created.
"""

from array import array
from time import perf_counter
import os
import sys


def parse_ints(data):
    x = 0
    in_number = False
    for c in data:
        if 48 <= c <= 57:
            x = 10 * x + c - 48
            in_number = True
        elif in_number:
            yield x
            x = 0
            in_number = False
    if in_number:
        yield x


def solve(data):
    beginning = perf_counter()
    ints = parse_ints(data)
    n = next(ints)
    m = next(ints)

    # CSR-like per-transaction lists (contiguous array slices).
    reads = array('i')
    writes = array('i')
    read_start = array('i')
    write_start = array('i')

    # Per-cell linked lists; each membership is represented exactly once.
    head_read = array('i', [-1]) * (m + 1)
    head_write = array('i', [-1]) * (m + 1)
    next_read = array('i')
    next_write = array('i')
    owner_read = array('i')
    owner_write = array('i')

    cnt_read0 = array('i', [0]) * (m + 1)
    cnt_write0 = array('i', [0]) * (m + 1)
    xor_read0 = array('i', [0]) * (m + 1)
    xor_write0 = array('i', [0]) * (m + 1)

    for i in range(1, n + 1):
        r = next(ints)
        w = next(ints)
        read_start.append(len(reads))
        write_start.append(len(writes))
        for _ in range(r):
            loc = next(ints)
            reads.append(loc)
            cnt_read0[loc] += 1
            xor_read0[loc] ^= i
            next_read.append(head_read[loc])
            head_read[loc] = len(owner_read)
            owner_read.append(i)
        for _ in range(w):
            loc = next(ints)
            writes.append(loc)
            cnt_write0[loc] += 1
            xor_write0[loc] ^= i
            next_write.append(head_write[loc])
            head_write[loc] = len(owner_write)
            owner_write.append(i)
    read_start.append(len(reads))
    write_start.append(len(writes))
    del data, ints
    parsing_done = perf_counter()

    # in_block[i] = number of write locations with at least one OTHER reader.
    # out_block[i] = number of read locations with at least one OTHER writer.
    # Degree sums count cell-level incidence pairs for ordering heuristics.
    mark_read = array('i', [0]) * (m + 1)
    mark_write = array('i', [0]) * (m + 1)
    in_block0 = [0] * (n + 1)
    out_block0 = [0] * (n + 1)
    in_degree = [0] * (n + 1)
    out_degree = [0] * (n + 1)
    for i in range(1, n + 1):
        for p in range(read_start[i - 1], read_start[i]):
            mark_read[reads[p]] = i
        for p in range(write_start[i - 1], write_start[i]):
            mark_write[writes[p]] = i
        ib = ob = ideg = odeg = 0
        for p in range(write_start[i - 1], write_start[i]):
            loc = writes[p]
            c = cnt_read0[loc] - (mark_read[loc] == i)
            if c:
                ib += 1
                ideg += c
        for p in range(read_start[i - 1], read_start[i]):
            loc = reads[p]
            c = cnt_write0[loc] - (mark_write[loc] == i)
            if c:
                ob += 1
                odeg += c
        in_block0[i] = ib
        out_block0[i] = ob
        in_degree[i] = ideg
        out_degree[i] = odeg
    del mark_read, mark_write
    degrees_done = perf_counter()

    # On every round, the implicit graph is reduced by monotonic count updates.
    # Cell incidence lists are scanned only when their live count hits 1 or 0.
    def run(drop_order):
        rc = cnt_read0[:]
        wc = cnt_write0[:]
        rx = xor_read0[:]
        wx = xor_write0[:]
        ib = in_block0[:]
        ob = out_block0[:]
        alive = bytearray(b'\x01') * (n + 1)

        sources = [i for i in range(1, n + 1) if ib[i] == 0]
        sinks = [i for i in range(1, n + 1) if ob[i] == 0]
        source_pos = sink_pos = drop_pos = 0
        prefix = []
        suffix = []
        dropped = 0

        for _ in range(n):
            while source_pos < len(sources) and not alive[sources[source_pos]]:
                source_pos += 1
            while sink_pos < len(sinks) and not alive[sinks[sink_pos]]:
                sink_pos += 1

            if source_pos < len(sources):
                i = sources[source_pos]
                source_pos += 1
                prefix.append(i)
            elif sink_pos < len(sinks):
                i = sinks[sink_pos]
                sink_pos += 1
                suffix.append(i)
            else:
                while not alive[drop_order[drop_pos]]:
                    drop_pos += 1
                i = drop_order[drop_pos]
                drop_pos += 1
                dropped += 1

            alive[i] = 0
            # Removing reader i can free writers with no OTHER readers.
            for p in range(read_start[i - 1], read_start[i]):
                loc = reads[p]
                rem = rc[loc] - 1
                rc[loc] = rem
                rx[loc] ^= i
                if rem == 1:
                    only = rx[loc]
                    if alive[only] and wc[loc]:
                        e = head_write[loc]
                        while e != -1:
                            j = owner_write[e]
                            if j == only:
                                ib[j] -= 1
                                if ib[j] == 0:
                                    sources.append(j)
                                break
                            e = next_write[e]
                elif rem == 0 and wc[loc]:
                    e = head_write[loc]
                    while e != -1:
                        j = owner_write[e]
                        if alive[j]:
                            ib[j] -= 1
                            if ib[j] == 0:
                                sources.append(j)
                        e = next_write[e]

            # Removing writer i can free readers with no OTHER writers.
            for p in range(write_start[i - 1], write_start[i]):
                loc = writes[p]
                rem = wc[loc] - 1
                wc[loc] = rem
                wx[loc] ^= i
                if rem == 1:
                    only = wx[loc]
                    if alive[only] and rc[loc]:
                        e = head_read[loc]
                        while e != -1:
                            j = owner_read[e]
                            if j == only:
                                ob[j] -= 1
                                if ob[j] == 0:
                                    sinks.append(j)
                                break
                            e = next_read[e]
                elif rem == 0 and rc[loc]:
                    e = head_read[loc]
                    while e != -1:
                        j = owner_read[e]
                        if alive[j]:
                            ob[j] -= 1
                            if ob[j] == 0:
                                sinks.append(j)
                        e = next_read[e]

        prefix.extend(reversed(suffix))
        return prefix, dropped

    # Vertices initially lacking one type of neighbor cannot belong to a
    # directed cycle; they never need to be chosen for removal.
    cyclic_candidates = [i for i in range(1, n + 1)
                         if in_block0[i] and out_block0[i]]
    # Scores estimate which removal is likeliest to break many cycles.
    # A strong read/write imbalance benefits from trying the appropriate
    # directional degree score BEFORE time runs out.
    scores = {
        'product': lambda i: in_degree[i] * out_degree[i],
        'minimum': lambda i: min(in_degree[i], out_degree[i]),
        'outgoing': lambda i: out_degree[i],
        'incoming': lambda i: in_degree[i],
        'sum': lambda i: in_degree[i] + out_degree[i],
    }
    if len(reads) >= 2 * len(writes):
        priorities = ('incoming', 'product', 'sum', 'outgoing', 'minimum')
    elif len(writes) >= 2 * len(reads):
        priorities = ('outgoing', 'product', 'sum', 'incoming', 'minimum')
    else:
        priorities = ('product', 'sum', 'incoming', 'outgoing', 'minimum')

    order = sorted(cyclic_candidates, key=scores[priorities[0]], reverse=True)
    first_begin = perf_counter()
    best, dropped = run(order)
    first_done = perf_counter()
    debug = os.environ.get('TRANSACTION_DEBUG') == '1'
    if debug:
        print(f'parse={parsing_done-beginning:.3f} degrees={degrees_done-parsing_done:.3f} '
              f'first={first_done-first_begin:.3f} mode={priorities[0]} '
              f'k={len(best)} dropped={dropped}', file=sys.stderr)
    if len(best) == n:
        return best

    # Hard 4 s limit: do not force all five passes on worst inputs.
    budget = float(os.environ.get('TRANSACTION_TIME_BUDGET', '2.80'))
    if os.environ.get('TRANSACTION_TEST_ALL') == '1':
        budget = 1e9
    elapsed = perf_counter() - beginning
    last_round = first_done - first_begin
    for mode in priorities[1:]:
        if elapsed + 1.4 * last_round + 0.15 >= budget:
            break
        before = perf_counter()
        order.sort(key=scores[mode], reverse=True)
        result, _ = run(order)
        if debug:
            print(f'mode={mode} duration={perf_counter()-before:.3f} k={len(result)}', file=sys.stderr)
        if len(result) > len(best):
            best = result
            if len(best) == n:
                break
        after = perf_counter()
        last_round = after - before
        elapsed = after - beginning
    return best


def main():
    result = solve(sys.stdin.buffer.read())
    sys.stdout.write(str(len(result)) + '\n')
    sys.stdout.write(' '.join(map(str, result)) + '\n')


if __name__ == '__main__':
    main()
