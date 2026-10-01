use std::collections::BTreeMap;

use lesha_peer_core::CoreEvent;
use lesha_types::{MonotonicTime, NodeId};

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ScheduledEvent {
    pub at: MonotonicTime,
    pub priority: u16,
    pub stable_source: u64,
    pub source_sequence: u64,
    pub target: NodeId,
    pub event: CoreEvent,
}

#[derive(Debug, Default)]
pub struct EventQueue {
    entries: BTreeMap<(MonotonicTime, u16, u64, u64), ScheduledEvent>,
}

impl EventQueue {
    pub fn push(&mut self, event: ScheduledEvent) -> Result<(), &'static str> {
        let key = (
            event.at,
            event.priority,
            event.stable_source,
            event.source_sequence,
        );
        if self.entries.insert(key, event).is_some() {
            return Err("duplicate total-order event key");
        }
        Ok(())
    }

    pub fn pop_next(&mut self) -> Option<ScheduledEvent> {
        let key = self.entries.keys().next().cloned()?;
        self.entries.remove(&key)
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
}
