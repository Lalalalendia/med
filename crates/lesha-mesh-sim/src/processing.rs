use std::collections::BTreeMap;

use lesha_types::{MonotonicTime, NodeId};

#[derive(Debug, Default)]
pub struct SimProcessing {
    paused_until: BTreeMap<NodeId, MonotonicTime>,
}

impl SimProcessing {
    pub fn pause_until(&mut self, node: NodeId, until: MonotonicTime) {
        self.paused_until.insert(node, until);
    }

    pub fn resume(&mut self, node: NodeId) {
        self.paused_until.remove(&node);
    }

    pub fn ready_at(&self, node: NodeId, scheduled_at: MonotonicTime) -> MonotonicTime {
        match self.paused_until.get(&node).copied() {
            Some(until) if until > scheduled_at => until,
            _ => scheduled_at,
        }
    }

    pub fn is_paused(&self, node: NodeId, now: MonotonicTime) -> bool {
        self.paused_until
            .get(&node)
            .map(|until| *until > now)
            .unwrap_or(false)
    }

    pub fn clear_if_reached(&mut self, node: NodeId, now: MonotonicTime) {
        if self
            .paused_until
            .get(&node)
            .map(|until| *until <= now)
            .unwrap_or(false)
        {
            self.paused_until.remove(&node);
        }
    }
}
