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

#[derive(Debug, Clone, Eq, PartialEq, Default)]
pub struct EventTrace {
    pub records: Vec<TraceRecord>,
}

impl EventTrace {
    /// Deterministic test fingerprint. This is intentionally not a cryptographic
    /// or wire-format hash and must not be used as durable protocol integrity.
    pub fn stable_digest64(&self) -> u64 {
        const OFFSET: u64 = 0xcbf29ce484222325;
        const PRIME: u64 = 0x100000001b3;

        let mut hash = OFFSET;
        for record in &self.records {
            let rendered = format!("{record:?}");
            for byte in rendered.as_bytes() {
                hash ^= u64::from(*byte);
                hash = hash.wrapping_mul(PRIME);
            }
        }
        hash
    }
}
