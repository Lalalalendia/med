use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::io::{self, Read};

const INF: i64 = i64::MAX / 4;

#[derive(Clone, Copy)]
struct Road {
    from: usize,
    to: usize,
    time: usize,
    capacity: i64,
}

struct Arc {
    to: usize,
    reverse: usize,
    capacity: i64,
    cost: i64,
}

fn add_edge(graph: &mut [Vec<Arc>], from: usize, to: usize, capacity: i64, cost: i64) {
    let fi = graph[from].len();
    let ri = graph[to].len();
    graph[from].push(Arc { to, reverse: ri, capacity, cost });
    graph[to].push(Arc { to: from, reverse: fi, capacity: 0, cost: -cost });
}

// Ford-Fulkerson maximum flow over time theorem.
// Maximal arrivals by deadline = sum over augmenting static flows
// of capacity * (deadline + 1 - path travel time), for paths
// whose residual shortest cost is below deadline + 1.
fn delivered(n: usize, roads: &[Road], k: i64, deadline: usize) -> i64 {
    if n == 1 {
        return k;
    }
    let mut graph: Vec<Vec<Arc>> = (0..n).map(|_| Vec::new()).collect();
    for r in roads {
        if r.time <= deadline {
            add_edge(&mut graph, r.from, r.to, r.capacity, r.time as i64);
        }
    }
    let mut potential = vec![0i64; n];
    let mut answer = 0i64;
    let duration = deadline as i64 + 1;

    loop {
        let mut dist = vec![INF; n];
        let mut parent = vec![(usize::MAX, usize::MAX); n];
        let mut pq = BinaryHeap::new();
        dist[0] = 0;
        pq.push(Reverse((0i64, 0usize)));

        while let Some(Reverse((d, u))) = pq.pop() {
            if d != dist[u] {
                continue;
            }
            for (index, edge) in graph[u].iter().enumerate() {
                if edge.capacity <= 0 {
                    continue;
                }
                let reduced = edge.cost + potential[u] - potential[edge.to];
                let candidate = d + reduced;
                if candidate < dist[edge.to] {
                    dist[edge.to] = candidate;
                    parent[edge.to] = (u, index);
                    pq.push(Reverse((candidate, edge.to)));
                }
            }
        }

        if dist[n - 1] == INF {
            break;
        }
        for v in 0..n {
            if dist[v] < INF {
                potential[v] += dist[v];
            }
        }
        let path_time = potential[n - 1] - potential[0];
        if path_time >= duration {
            break;
        }

        let mut amount = i64::MAX;
        let mut v = n - 1;
        while v != 0 {
            let (u, ix) = parent[v];
            amount = amount.min(graph[u][ix].capacity);
            v = u;
        }
        v = n - 1;
        while v != 0 {
            let (u, ix) = parent[v];
            let rev = graph[u][ix].reverse;
            graph[u][ix].capacity -= amount;
            graph[v][rev].capacity += amount;
            v = u;
        }
        answer += amount * (duration - path_time);
        if answer >= k {
            return k;
        }
    }
    answer
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut it = input.split_ascii_whitespace();
    let n: usize = it.next().unwrap().parse().unwrap();
    let m: usize = it.next().unwrap().parse().unwrap();
    let k: i64 = it.next().unwrap().parse().unwrap();
    let t: usize = it.next().unwrap().parse().unwrap();
    let mut roads = Vec::with_capacity(m);
    for _ in 0..m {
        let u = it.next().unwrap().parse::<usize>().unwrap() - 1;
        let v = it.next().unwrap().parse::<usize>().unwrap() - 1;
        let l = it.next().unwrap().parse().unwrap();
        let s = it.next().unwrap().parse().unwrap();
        roads.push(Road { from: u, to: v, time: l, capacity: s });
    }

    let received = delivered(n, &roads, k, t);
    if received < k {
        println!("{}", k - received);
        return;
    }

    let mut low = 0;
    let mut high = t;
    while low < high {
        let mid = low + (high - low) / 2;
        if delivered(n, &roads, k, mid) >= k {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    println!("{low}");
}
