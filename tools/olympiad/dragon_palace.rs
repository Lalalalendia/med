use std::cmp::Reverse;
use std::collections::BinaryHeap;
use std::io::{self, Read};

const NONE: i32 = -1;

struct Edge {
    to: u32,
    next: i32,
    cap: i32,
}

struct Dinic {
    source: usize,
    sink: usize,
    head: Vec<i32>,
    level: Vec<i32>,
    ptr: Vec<i32>,
    queue: Vec<usize>,
    edges: Vec<Edge>,
}

impl Dinic {
    fn new(nodes: usize, source: usize, sink: usize, max_edges: usize) -> Self {
        Self {
            source,
            sink,
            head: vec![NONE; nodes],
            level: vec![-1; nodes],
            ptr: vec![NONE; nodes],
            queue: vec![0; nodes],
            edges: Vec::with_capacity(max_edges * 2),
        }
    }

    fn add_edge(&mut self, u: usize, v: usize, cap: i32) {
        let e = self.edges.len() as i32;
        self.edges.push(Edge {
            to: v as u32,
            next: self.head[u],
            cap,
        });
        self.head[u] = e;
        self.edges.push(Edge {
            to: u as u32,
            next: self.head[v],
            cap: 0,
        });
        self.head[v] = e + 1;
    }

    fn bfs(&mut self) -> bool {
        self.level.fill(-1);
        let mut first = 0;
        let mut last = 1;
        self.queue[0] = self.source;
        self.level[self.source] = 0;

        while first < last {
            let v = self.queue[first];
            first += 1;
            if self.level[self.sink] >= 0 && self.level[v] >= self.level[self.sink] {
                break;
            }
            let mut e = self.head[v];
            while e != NONE {
                let idx = e as usize;
                let to = self.edges[idx].to as usize;
                if self.edges[idx].cap > 0 && self.level[to] == -1 {
                    self.level[to] = self.level[v] + 1;
                    self.queue[last] = to;
                    last += 1;
                }
                e = self.edges[idx].next;
            }
        }
        self.level[self.sink] >= 0
    }

    fn dfs(&mut self, v: usize, limit: i32) -> i32 {
        if v == self.sink {
            return limit;
        }
        while self.ptr[v] != NONE {
            let e = self.ptr[v] as usize;
            let to = self.edges[e].to as usize;
            if self.edges[e].cap > 0 && self.level[to] == self.level[v] + 1 {
                let capacity = self.edges[e].cap;
                let pushed = self.dfs(to, limit.min(capacity));
                if pushed > 0 {
                    self.edges[e].cap -= pushed;
                    self.edges[e ^ 1].cap += pushed;
                    return pushed;
                }
            }
            self.ptr[v] = self.edges[e].next;
        }
        0
    }

    fn max_flow(&mut self, limit: i32) -> i32 {
        let mut sent = 0;
        while sent < limit && self.bfs() {
            self.ptr.copy_from_slice(&self.head);
            while sent < limit {
                let pushed = self.dfs(self.source, limit - sent);
                if pushed == 0 {
                    break;
                }
                sent += pushed;
            }
        }
        sent
    }
}

#[derive(Clone, Copy)]
struct Road {
    from: usize,
    to: usize,
    time: usize,
    capacity: i32,
}

fn delivered(n: usize, roads: &[Road], k: i32, deadline: usize) -> i32 {
    let sink = (deadline + 1) * n;
    let mut flow = Dinic::new(
        sink + 1,
        0,
        sink,
        roads.len() * (deadline + 1) + n * deadline + deadline + 1,
    );

    for time in 0..=deadline {
        if time > 0 {
            for v in 0..n {
                flow.add_edge((time - 1) * n + v, time * n + v, k);
            }
        }
        for r in roads {
            if time + r.time <= deadline {
                flow.add_edge(time * n + r.from, (time + r.time) * n + r.to, r.capacity);
            }
        }
        flow.add_edge(time * n + n - 1, sink, k);
    }
    flow.max_flow(k)
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut it = input.split_ascii_whitespace();
    let n: usize = it.next().unwrap().parse().unwrap();
    let m: usize = it.next().unwrap().parse().unwrap();
    let k: i32 = it.next().unwrap().parse().unwrap();
    let t: usize = it.next().unwrap().parse().unwrap();

    let mut roads = Vec::with_capacity(m);
    let mut adj = vec![Vec::<(usize, usize)>::new(); n];
    for _ in 0..m {
        let u: usize = it.next().unwrap().parse::<usize>().unwrap() - 1;
        let v: usize = it.next().unwrap().parse::<usize>().unwrap() - 1;
        let l: usize = it.next().unwrap().parse().unwrap();
        let s: i32 = it.next().unwrap().parse().unwrap();
        roads.push(Road { from: u, to: v, time: l, capacity: s });
        adj[u].push((v, l));
    }

    if n == 1 {
        println!("0");
        return;
    }

    // Shortest travel time ignoring queues.
    let inf = usize::MAX / 4;
    let mut dist = vec![inf; n];
    let mut pq = BinaryHeap::new();
    dist[0] = 0;
    pq.push(Reverse((0_usize, 0_usize)));
    while let Some(Reverse((d, u))) = pq.pop() {
        if d != dist[u] {
            continue;
        }
        for &(v, l) in &adj[u] {
            if d + l < dist[v] {
                dist[v] = d + l;
                pq.push(Reverse((dist[v], v)));
            }
        }
    }
    if dist[n - 1] > t {
        println!("{k}");
        return;
    }

    let full = delivered(n, &roads, k, t);
    if full < k {
        println!("{}", k - full);
        return;
    }

    let mut low = dist[n - 1];
    let mut high = t;
    while low < high {
        let mid = low + (high - low) / 2;
        if delivered(n, &roads, k, mid) == k {
            high = mid;
        } else {
            low = mid + 1;
        }
    }
    println!("{low}");
}
