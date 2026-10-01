use lesha_types::{EffectId, MonotonicTime, NodeRef, PresenceIncarnation, SendId, SessionId};

use crate::event::CloseReason;
use crate::message::MeshMessage;
use crate::state::{ObservationId, ProbeId};
use crate::timer::TimerId;

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum PeerEvent {
    PeerHealthy(NodeRef),
    PeerSuspect(NodeRef),
    PeerUnreachable(NodeRef),
    PeerRecovered(NodeRef),
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum CoreDiagnostic {
    StaleTimer(TimerId),
    UnknownSession(SessionId),
    StaleAck(ProbeId),
    StaleAlive {
        peer: NodeRef,
        received: PresenceIncarnation,
        known: PresenceIncarnation,
    },
    OldGenerationSessionRejected(NodeRef),
    InvalidMessageSubject(NodeRef),
    PresencePersistenceFailed,
    UnexpectedEventForLifecycle,
    CapacityExceeded,
    SuspicionAboveLocalIncarnation {
        alleged: PresenceIncarnation,
        local: PresenceIncarnation,
    },
    ObservationIgnored(ObservationId),
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum CoreEffectKind {
    LoadDurablePeerState,
    PersistPresence {
        expected_previous: Option<PresenceIncarnation>,
        next: PresenceIncarnation,
    },
    ScheduleTimer {
        timer_id: TimerId,
        deadline: MonotonicTime,
    },
    CancelTimer {
        timer_id: TimerId,
    },
    SendMeshMessage {
        send_id: SendId,
        session_id: SessionId,
        message: MeshMessage,
    },
    CloseSession {
        session_id: SessionId,
        reason: CloseReason,
    },
    EmitPeerEvent {
        event: PeerEvent,
    },
    RecordDiagnostic {
        diagnostic: CoreDiagnostic,
    },
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CoreEffect {
    pub effect_id: EffectId,
    pub kind: CoreEffectKind,
}

#[derive(Debug, Clone, Eq, PartialEq, Default)]
pub struct StepOutput {
    pub effects: Vec<CoreEffect>,
}
