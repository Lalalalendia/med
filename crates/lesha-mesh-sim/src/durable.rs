use std::collections::BTreeMap;

use lesha_peer_core::{
    durable_peer_state_integrity_digest, DurablePeerStateV0, PersistenceError,
};
use lesha_types::{NodeId, PresenceIncarnation};

#[derive(Debug, Default)]
pub struct SimDurableStore {
    states: BTreeMap<NodeId, DurablePeerStateV0>,
}

impl SimDurableStore {
    pub fn load(&self, node_id: NodeId) -> Option<DurablePeerStateV0> {
        self.states.get(&node_id).cloned()
    }

    pub fn load_verified(
        &self,
        node_id: NodeId,
    ) -> Result<Option<DurablePeerStateV0>, PersistenceError> {
        let Some(state) = self.load(node_id) else {
            return Ok(None);
        };
        if state.integrity_tag != durable_peer_state_integrity_digest(&state) {
            return Err(PersistenceError::Corrupt);
        }
        Ok(Some(state))
    }

    pub fn store(&mut self, mut state: DurablePeerStateV0) {
        state.integrity_tag = durable_peer_state_integrity_digest(&state);
        self.states.insert(state.self_ref.node_id, state);
    }

    pub fn corrupt_integrity_for_test(&mut self, node_id: NodeId) -> bool {
        let Some(state) = self.states.get_mut(&node_id) else {
            return false;
        };
        state.integrity_tag[0] ^= 0x01;
        true
    }

    pub fn committed_presence(&self, node_id: NodeId) -> Option<PresenceIncarnation> {
        self.states
            .get(&node_id)
            .map(|state| state.committed_presence)
    }
}
