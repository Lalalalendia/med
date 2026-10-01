use lesha_canonical::{sha256_domain, CanonicalWriter};
use lesha_peer_core::{CoreEffect, CoreEvent};
use lesha_types::{MonotonicTime, NodeId};

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct TraceRecord {
    pub event_index: u64,
    pub sim_time: MonotonicTime,
    pub target: NodeId,
    pub event: CoreEvent,
    pub effects: Vec<CoreEffect>,
    pub input_digest: [u8; 32],
    pub pre_state_digest: [u8; 32],
    pub effects_digest: [u8; 32],
    pub post_state_digest: [u8; 32],
}

#[derive(Debug, Clone, Eq, PartialEq, Default)]
pub struct EventTrace {
    pub records: Vec<TraceRecord>,
}

impl EventTrace {
    pub fn trace_root(&self) -> [u8; 32] {
        let mut writer = CanonicalWriter::new();
        writer.array(2);
        writer.unsigned(0);
        writer.array(self.records.len());

        for record in &self.records {
            writer.array(7);
            writer.unsigned(record.event_index);
            writer.unsigned(record.sim_time.0);
            writer.bytes(&record.target.0);
            writer.bytes(&record.input_digest);
            writer.bytes(&record.pre_state_digest);
            writer.bytes(&record.effects_digest);
            writer.bytes(&record.post_state_digest);
        }

        sha256_domain(b"LesHa/MeshTrace/M0\0", &writer.finish())
    }

    /// Legacy regression fingerprint. Prefer trace_root() for durable evidence.
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
