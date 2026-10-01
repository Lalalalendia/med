use std::collections::BTreeMap;

use lesha_peer_core::DurablePeerStateV0;
use lesha_types::{NodeId, PresenceIncarnation};

#[derive(Debug, Default)]
pub struct SimDurableStore {
    states: BTreeMap<NodeId, DurablePeerStateV0>,
}

impl SimDurableStore {
    pub fn load(&self, node_id: NodeId) -> Option<DurablePeerStateV0> {
        self.states.get(&node_id).cloned()
    }

    pub fn store(&mut self, state: DurablePeerStateV0) {
        self.states.insert(state.self_ref.node_id, state);
    }

    pub fn committed_presence(&self, node_id: NodeId) -> Option<PresenceIncarnation> {
        self.states.get(&node_id).map(|state| state.committed_presence)
    }
}
