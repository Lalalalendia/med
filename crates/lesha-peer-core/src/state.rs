use std::collections::BTreeMap;

use lesha_types::{
    ClusterId, EffectId, EndpointSequence, MonotonicTime, NodeGeneration, NodeId, NodeRef,
    PresenceIncarnation, SessionId,
};

use crate::timer::TimerId;
use crate::timer::TimerKey;

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct ProbeId {
    pub origin: NodeRef,
    pub origin_incarnation: PresenceIncarnation,
    pub sequence: u64,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct ObservationId {
    pub observer: NodeRef,
    pub observer_incarnation: PresenceIncarnation,
    pub sequence: u64,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum LifecycleState {
    Cold,
    LoadingDurableState,
    WaitingForPresenceCommit,
    NetworkActive,
    ShuttingDown,
    RecoveryRequired,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct DurablePeerStateV0 {
    pub format_version: u16,
    pub self_ref: NodeRef,
    pub committed_presence: PresenceIncarnation,
    pub committed_endpoint_sequence: EndpointSequence,
    pub integrity_tag: [u8; 32],
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum PresenceWritePurpose {
    StartupActivation,
    RefuteSuspicion {
        source_session: SessionId,
        observation_id: ObservationId,
    },
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct PendingPresenceWrite {
    pub effect_id: EffectId,
    pub expected_previous: PresenceIncarnation,
    pub next: PresenceIncarnation,
    pub purpose: PresenceWritePurpose,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct MemberRecord {
    pub node_id: NodeId,
    pub current_generation: NodeGeneration,
    pub admitted: bool,
    pub revoked: bool,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ControlViewM0 {
    pub cluster_id: ClusterId,
    pub epoch: u64,
    pub members: BTreeMap<NodeId, MemberRecord>,
}

impl ControlViewM0 {
    pub fn is_current_member(&self, peer: NodeRef) -> bool {
        if peer.cluster_id != self.cluster_id {
            return false;
        }
        self.members
            .get(&peer.node_id)
            .map(|m| m.admitted && !m.revoked && m.current_generation == peer.generation)
            .unwrap_or(false)
    }

    pub fn member(&self, node_id: NodeId) -> Option<&MemberRecord> {
        self.members.get(&node_id)
    }
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum SessionDirection {
    Inbound,
    Outbound,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum PeerHealth {
    Healthy,
    Suspect,
    Unreachable,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SessionStateM0 {
    pub session_id: SessionId,
    pub peer: NodeRef,
    pub direction: SessionDirection,
    pub peer_incarnation: PresenceIncarnation,
    pub health: PeerHealth,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum ProbePhase {
    Direct,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct PendingProbeM0 {
    pub probe_id: ProbeId,
    pub target: NodeRef,
    pub target_incarnation: Option<PresenceIncarnation>,
    pub phase: ProbePhase,
    pub started_at: MonotonicTime,
    pub deadline: TimerId,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SuspicionM0 {
    pub subject: NodeRef,
    pub incarnation: PresenceIncarnation,
    pub started_at: MonotonicTime,
    pub deadline: TimerId,
    pub local_observation: ObservationId,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub enum ChoiceDomain {
    ProbeTarget,
    BackoffJitter,
    PresenceNonce,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct SelectionStateM0 {
    pub seed: [u8; 32],
    pub counters: BTreeMap<ChoiceDomain, u64>,
}

impl Default for SelectionStateM0 {
    fn default() -> Self {
        Self {
            seed: [0; 32],
            counters: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct PeerManagerStateM0 {
    pub lifecycle: LifecycleState,
    pub self_ref: NodeRef,
    pub durable: Option<DurablePeerStateV0>,
    pub pending_load_effect: Option<EffectId>,
    pub pending_presence_write: Option<PendingPresenceWrite>,
    pub control: Option<ControlViewM0>,
    pub sessions: BTreeMap<SessionId, SessionStateM0>,
    pub peer_presence: BTreeMap<NodeRef, PresenceIncarnation>,
    pub pending_probes: BTreeMap<ProbeId, PendingProbeM0>,
    pub suspicions: BTreeMap<NodeRef, SuspicionM0>,
    pub timer_generations: BTreeMap<TimerKey, u64>,
    pub next_effect_id: u64,
    pub next_send_id: u64,
    pub next_probe_sequence: u64,
    pub next_observation_sequence: u64,
    pub selection: SelectionStateM0,
}

impl PeerManagerStateM0 {
    pub fn new(self_ref: NodeRef) -> Self {
        Self {
            lifecycle: LifecycleState::Cold,
            self_ref,
            durable: None,
            pending_load_effect: None,
            pending_presence_write: None,
            control: None,
            sessions: BTreeMap::new(),
            peer_presence: BTreeMap::new(),
            pending_probes: BTreeMap::new(),
            suspicions: BTreeMap::new(),
            timer_generations: BTreeMap::new(),
            next_effect_id: 1,
            next_send_id: 1,
            next_probe_sequence: 1,
            next_observation_sequence: 1,
            selection: SelectionStateM0::default(),
        }
    }

    pub fn current_presence(&self) -> Option<PresenceIncarnation> {
        self.durable.as_ref().map(|d| d.committed_presence)
    }
}
