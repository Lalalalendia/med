use lesha_mesh_sim::{EventQueue, ScheduledEvent};
use lesha_peer_core::{CoreEvent, CoreEventKind, EventSource};
use lesha_types::{MonotonicTime, NodeId};

#[test]
fn queue_uses_total_order_key() {
    let mut q = EventQueue::default();
    let mk = |seq| ScheduledEvent {
        at: MonotonicTime(10),
        priority: 2,
        stable_source: 7,
        source_sequence: seq,
        target: NodeId([1; 32]),
        event: CoreEvent {
            observed_at: MonotonicTime(10),
            source: EventSource::Operator,
            kind: CoreEventKind::ShutdownRequested,
        },
    };
    q.push(mk(2)).unwrap();
    q.push(mk(1)).unwrap();
    assert_eq!(q.pop_next().unwrap().source_sequence, 1);
    assert_eq!(q.pop_next().unwrap().source_sequence, 2);
}
