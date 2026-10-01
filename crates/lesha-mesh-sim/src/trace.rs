use lesha_peer_core::{CoreEffect, CoreEvent};
use lesha_types::{MonotonicTime, NodeId};

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct TraceRecord {
    pub event_index: u64,
    pub sim_time: MonotonicTime,
    pub target: NodeId,
    pub event: CoreEvent,
    pub effects: Vec<CoreEffect>,
}

#[derive(Debug, Default)]
pub struct EventTrace {
    pub records: Vec<TraceRecord>,
}
