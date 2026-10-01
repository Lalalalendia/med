use lesha_peer_core::{
    invariant::{
        check_membership_immutable_for_non_control, check_no_network_before_activation,
        InvariantViolation as CoreInvariantViolation,
    },
    CoreEffect, CoreEvent, PeerManagerStateM0,
};
use lesha_types::NodeId;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum SimInvariantId {
    NetworkEffectBeforeActivation,
    MembershipChangedByNonControlEvent,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct InvariantFailure {
    pub event_index: u64,
    pub target: NodeId,
    pub invariant: SimInvariantId,
    pub input_digest: [u8; 32],
    pub pre_state_digest: [u8; 32],
    pub effects_digest: [u8; 32],
    pub post_state_digest: [u8; 32],
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct TransitionEvidence {
    pub event_index: u64,
    pub target: NodeId,
    pub input_digest: [u8; 32],
    pub pre_state_digest: [u8; 32],
    pub effects_digest: [u8; 32],
    pub post_state_digest: [u8; 32],
}

#[derive(Debug, Default)]
pub struct InvariantMonitor {
    first_failure: Option<InvariantFailure>,
}

impl InvariantMonitor {
    pub fn observe_transition(
        &mut self,
        evidence: TransitionEvidence,
        before: &PeerManagerStateM0,
        event: &CoreEvent,
        effects: &[CoreEffect],
        after: &PeerManagerStateM0,
    ) -> Option<InvariantFailure> {
        if let Some(existing) = &self.first_failure {
            return Some(existing.clone());
        }

        let violation = check_no_network_before_activation(before, effects)
            .err()
            .or_else(|| check_membership_immutable_for_non_control(before, event, after).err());

        let invariant = match violation? {
            CoreInvariantViolation::NetworkEffectBeforeActivation => {
                SimInvariantId::NetworkEffectBeforeActivation
            }
            CoreInvariantViolation::MembershipChangedByNonControlEvent => {
                SimInvariantId::MembershipChangedByNonControlEvent
            }
        };

        let failure = InvariantFailure {
            event_index: evidence.event_index,
            target: evidence.target,
            invariant,
            input_digest: evidence.input_digest,
            pre_state_digest: evidence.pre_state_digest,
            effects_digest: evidence.effects_digest,
            post_state_digest: evidence.post_state_digest,
        };
        self.first_failure = Some(failure.clone());
        Some(failure)
    }

    pub fn first_failure(&self) -> Option<&InvariantFailure> {
        self.first_failure.as_ref()
    }

    pub fn is_clean(&self) -> bool {
        self.first_failure.is_none()
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use lesha_peer_core::{ControlViewM0, CoreEventKind, EventSource, PeerManagerStateM0};
    use lesha_types::{ClusterId, MonotonicTime, NodeGeneration, NodeId, NodeRef};

    use super::*;

    fn node() -> NodeRef {
        NodeRef {
            cluster_id: ClusterId([1; 16]),
            node_id: NodeId([7; 32]),
            generation: NodeGeneration(1),
        }
    }

    #[test]
    fn monitor_keeps_first_causative_transition() {
        let before = PeerManagerStateM0::new(node());
        let mut after = before.clone();
        after.control = Some(ControlViewM0 {
            cluster_id: node().cluster_id,
            epoch: 1,
            members: BTreeMap::new(),
        });

        let event = CoreEvent {
            observed_at: MonotonicTime(5),
            source: EventSource::Timer,
            kind: CoreEventKind::ShutdownRequested,
        };

        let mut monitor = InvariantMonitor::default();
        let first = monitor
            .observe_transition(
                TransitionEvidence {
                    event_index: 7,
                    target: node().node_id,
                    input_digest: [1; 32],
                    pre_state_digest: [2; 32],
                    effects_digest: [3; 32],
                    post_state_digest: [4; 32],
                },
                &before,
                &event,
                &[],
                &after,
            )
            .unwrap();

        assert_eq!(first.event_index, 7);
        assert_eq!(
            first.invariant,
            SimInvariantId::MembershipChangedByNonControlEvent
        );

        let repeated = monitor
            .observe_transition(
                TransitionEvidence {
                    event_index: 8,
                    target: node().node_id,
                    input_digest: [9; 32],
                    pre_state_digest: [9; 32],
                    effects_digest: [9; 32],
                    post_state_digest: [9; 32],
                },
                &before,
                &event,
                &[],
                &after,
            )
            .unwrap();
        assert_eq!(repeated, first);
        assert_eq!(monitor.first_failure(), Some(&first));
    }
}
