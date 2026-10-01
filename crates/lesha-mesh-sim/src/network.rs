use std::collections::BTreeMap;

use lesha_types::{MonoDuration, NodeId};

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct DirectedLinkPolicy {
    pub reachable: bool,
    pub latency: MonoDuration,
}

impl Default for DirectedLinkPolicy {
    fn default() -> Self {
        Self {
            reachable: true,
            latency: MonoDuration(1),
        }
    }
}

#[derive(Debug, Default)]
pub struct SimNetwork {
    policies: BTreeMap<(NodeId, NodeId), DirectedLinkPolicy>,
}

impl SimNetwork {
    pub fn policy(&self, from: NodeId, to: NodeId) -> DirectedLinkPolicy {
        self.policies.get(&(from, to)).copied().unwrap_or_default()
    }

    pub fn set_policy(&mut self, from: NodeId, to: NodeId, policy: DirectedLinkPolicy) {
        self.policies.insert((from, to), policy);
    }

    pub fn set_reachable(&mut self, from: NodeId, to: NodeId, reachable: bool) {
        let mut policy = self.policy(from, to);
        policy.reachable = reachable;
        self.set_policy(from, to, policy);
    }

    pub fn set_latency(&mut self, from: NodeId, to: NodeId, latency: MonoDuration) {
        let mut policy = self.policy(from, to);
        policy.latency = latency;
        self.set_policy(from, to, policy);
    }
}
