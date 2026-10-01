use lesha_types::{NodeRef, PresenceIncarnation};

use crate::state::{ObservationId, ProbeId};

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum MeshMessage {
    Ping {
        probe_id: ProbeId,
        sender_incarnation: PresenceIncarnation,
    },
    Ack {
        probe_id: ProbeId,
        responder_incarnation: PresenceIncarnation,
    },
    Suspect {
        subject: NodeRef,
        subject_incarnation: PresenceIncarnation,
        observation_id: ObservationId,
    },
    Alive {
        subject: NodeRef,
        incarnation: PresenceIncarnation,
        nonce: [u8; 16],
    },
}
