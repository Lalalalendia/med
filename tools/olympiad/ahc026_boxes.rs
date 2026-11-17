use std::io::{self, Read};

const N: usize = 200;
const M: usize = 10;

fn plan(initial: &[Vec<usize>], mode: usize) -> (usize, Vec<(usize, usize)>) {
    let mut stacks = initial.to_vec();
    let mut operations = Vec::with_capacity(700);
    let mut cost = 0usize;

    for box_number in 1..=N {
        let (source, position) = stacks
            .iter()
            .enumerate()
            .find_map(|(i, stack)| {
                stack.iter().position(|&v| v == box_number).map(|p| (i, p))
            })
            .expect("each remaining box exists in exactly one stack");

        if position + 1 < stacks[source].len() {
            // All boxes above the desired box must leave this stack.
            let first_moved = position + 1;
            let moved_count = stacks[source].len() - first_moved;
            let smallest_moved = *stacks[source][first_moved..].iter().min().unwrap();

            let mut destination = usize::MAX;
            let mut best_score = f64::INFINITY;
            for (j, candidate) in stacks.iter().enumerate() {
                if j == source {
                    continue;
                }

                // Baseline: move onto the shortest stack.
                // Improvements: prefer a stack whose smallest box is large;
                // burying smaller boxes is likely to require another move.
                let score = if mode == 0 {
                    candidate.len() as f64
                } else {
                    let min_existing = candidate.iter().copied().min().unwrap_or(N + 1);
                    let caution = match mode {
                        1 => 0.0,
                        2 => 25.0,
                        3 => 50.0,
                        4 => 100.0,
                        5 => 200.0,
                        _ => 75.0,
                    };
                    let buried_urgency: f64 = candidate
                        .iter()
                        .filter(|&&x| x < smallest_moved)
                        .map(|&x| 1.0 / (x - box_number + 1) as f64)
                        .sum();
                    -(min_existing as f64)
                        + caution * buried_urgency
                        + if mode == 6 { candidate.len() as f64 } else { 0.0 }
                };

                if score < best_score {
                    best_score = score;
                    destination = j;
                }
            }

            let moved = stacks[source].split_off(first_moved);
            debug_assert_eq!(moved.len(), moved_count);
            let first_box = moved[0];
            stacks[destination].extend(moved);
            operations.push((first_box, destination + 1));
            cost += moved_count + 1;
        }

        assert_eq!(stacks[source].pop(), Some(box_number));
        operations.push((box_number, 0));
    }

    (cost, operations)
}

fn main() {
    let mut input = String::new();
    io::stdin().read_to_string(&mut input).unwrap();
    let mut it = input.split_ascii_whitespace();
    let n: usize = it.next().unwrap().parse().unwrap();
    let m: usize = it.next().unwrap().parse().unwrap();
    assert_eq!(n, N);
    assert_eq!(m, M);

    let mut initial = vec![Vec::with_capacity(n / m); m];
    for stack in &mut initial {
        for _ in 0..n / m {
            stack.push(it.next().unwrap().parse().unwrap());
        }
    }

    let mut best = plan(&initial, 0);
    for mode in 1..=6 {
        let candidate = plan(&initial, mode);
        if candidate.0 < best.0 {
            best = candidate;
        }
    }
    assert!(best.1.len() <= 5000);
    for (v, i) in best.1 {
        println!("{v} {i}");
    }
}
