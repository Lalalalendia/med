use std::collections::{BTreeMap, VecDeque};

use lesha_peer_core::MeshMessage;
use lesha_types::NodeId;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum PresencePersistFault {
    FailBeforeCommit,
    CommitThenCrash,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd)]
pub enum MeshMessageKind {
    Ping,
    Ack,
    Suspect,
    Alive,
}

impl From<&MeshMessage> for MeshMessageKind {
    fn from(value: &MeshMessage) -> Self {
        match value {
            MeshMessage::Ping { .. } => Self::Ping,
            MeshMessage::Ack { .. } => Self::Ack,
            MeshMessage::Suspect { .. } => Self::Suspect,
            MeshMessage::Alive { .. } => Self::Alive,
        }
    }
}

#[derive(Debug, Default)]
pub struct FaultPlan {
    persist_faults: BTreeMap<NodeId, VecDeque<PresencePersistFault>>,
    dropped_messages: BTreeMap<(NodeId, MeshMessageKind), u64>,
}

impl FaultPlan {
    pub fn push_persist_fault(&mut self, node: NodeId, fault: PresencePersistFault) {
        self.persist_faults.entry(node).or_default().push_back(fault);
    }

    pub fn take_persist_fault(&mut self, node: NodeId) -> Option<PresencePersistFault> {
        let queue = self.persist_faults.get_mut(&node)?;
        let fault = queue.pop_front();
        if queue.is_empty() {
            self.persist_faults.remove(&node);
        }
        fault
    }

    pub fn drop_next_message(&mut self, from: NodeId, kind: MeshMessageKind) {
        let count = self.dropped_messages.entry((from, kind)).or_insert(0);
        *count = count.saturating_add(1);
    }

    pub fn should_drop_message(&mut self, from: NodeId, message: &MeshMessage) -> bool {
        let key = (from, MeshMessageKind::from(message));
        let Some(count) = self.dropped_messages.get_mut(&key) else {
            return false;
        };
        if *count == 0 {
            return false;
        }
        *count -= 1;
        if *count == 0 {
            self.dropped_messages.remove(&key);
        }
        true
    }
}
