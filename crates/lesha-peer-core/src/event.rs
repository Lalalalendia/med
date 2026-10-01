use lesha_types::{EffectId, MonotonicTime, NodeRef, PresenceIncarnation, SessionId};

use crate::message::MeshMessage;
use crate::state::{ControlViewM0, DurablePeerStateV0, SessionDirection};
use crate::timer::TimerId;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum EventSource {
    Runtime,
    Persistence,
    Transport,
    Timer,
    Control,
    Operator,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum PersistenceError {
    Unavailable,
    Corrupt,
    CompareFailed,
    IoFailure,
    UnsupportedVersion,
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub enum CloseReason {
    LocalShutdown,
    TransportLost,
    NotCurrentMember,
    Revoked,
    GenerationMismatch,
    ProtocolViolation,
    Replaced,
    RecoveryRequired,
}

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum CoreEventKind {
    StartRequested {
        selection_seed: [u8; 32],
    },
    DurableStateLoaded {
        effect_id: EffectId,
        state: Option<DurablePeerStateV0>,
    },
    DurableStateLoadFailed {
        effect_id: EffectId,
        error: PersistenceError,
    },
    PresencePersisted {
        effect_id: EffectId,
        value: PresenceIncarnation,
    },
    PresencePersistFailed {
        effect_id: EffectId,
        error: PersistenceError,
    },
    ControlViewReplaced {
        view: ControlViewM0,
    },
    AuthenticatedSessionEstablished {
        session_id: SessionId,
        peer: NodeRef,
        direction: SessionDirection,
        peer_incarnation: PresenceIncarnation,
    },
    SessionClosed {
        session_id: SessionId,
        reason: CloseReason,
    },
    MeshMessageReceived {
        session_id: SessionId,
        message: MeshMessage,
    },
    TimerFired {
        timer_id: TimerId,
    },
    ShutdownRequested,
}
#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CoreEvent {
    pub observed_at: MonotonicTime,
    pub source: EventSource,
    pub kind: CoreEventKind,
}
