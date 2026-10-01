use lesha_canonical::{sha256_domain, CanonicalAuthorityBytes, CanonicalWriter};
use lesha_types::NodeRef;

use crate::effect::{CoreDiagnostic, CoreEffect, CoreEffectKind, PeerEvent};
use crate::event::{CloseReason, CoreEvent, CoreEventKind, EventSource, PersistenceError};
use crate::message::MeshMessage;
use crate::state::{
    ChoiceDomain, ControlViewM0, DurablePeerStateV0, LifecycleState, MemberRecord, ObservationId,
    PeerHealth, PeerManagerStateM0, PendingPresenceWrite, PendingProbeM0, PresenceWritePurpose,
    ProbeId, ProbePhase, SelectionStateM0, SessionDirection, SessionStateM0, SuspicionM0,
};
use crate::timer::{TimerId, TimerKey};

const MESSAGE_DOMAIN: &[u8] = b"LesHa/MeshMessage/M0\0";
const EVENT_DOMAIN: &[u8] = b"LesHa/CoreEvent/M0\0";
const EFFECTS_DOMAIN: &[u8] = b"LesHa/CoreEffects/M0\0";
const STATE_DOMAIN: &[u8] = b"LesHa/PeerState/M0\0";
const DURABLE_DOMAIN: &[u8] = b"LesHa/DurablePeerState/M0\0";

pub fn canonical_mesh_message(message: &MeshMessage) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    w.array(2);
    w.unsigned(0);
    write_mesh_message(&mut w, message);
    w.finish()
}

pub fn mesh_message_digest(message: &MeshMessage) -> [u8; 32] {
    sha256_domain(MESSAGE_DOMAIN, &canonical_mesh_message(message))
}

pub fn canonical_core_event(event: &CoreEvent) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    w.array(4);
    w.unsigned(0);
    w.unsigned(event.observed_at.0);
    w.unsigned(event_source_tag(event.source));
    write_event_kind(&mut w, &event.kind);
    w.finish()
}

pub fn core_event_digest(event: &CoreEvent) -> [u8; 32] {
    sha256_domain(EVENT_DOMAIN, &canonical_core_event(event))
}

pub fn canonical_core_effect(effect: &CoreEffect) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    w.array(3);
    w.unsigned(0);
    w.unsigned(effect.effect_id.0);
    write_effect_kind(&mut w, &effect.kind);
    w.finish()
}

pub fn canonical_core_effects(effects: &[CoreEffect]) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    w.array(2);
    w.unsigned(0);
    w.array(effects.len());
    for effect in effects {
        w.array(2);
        w.unsigned(effect.effect_id.0);
        write_effect_kind(&mut w, &effect.kind);
    }
    w.finish()
}

pub fn core_effects_digest(effects: &[CoreEffect]) -> [u8; 32] {
    sha256_domain(EFFECTS_DOMAIN, &canonical_core_effects(effects))
}

pub fn canonical_peer_state(state: &PeerManagerStateM0) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    write_peer_state(&mut w, state);
    w.finish()
}

pub fn peer_state_digest(state: &PeerManagerStateM0) -> [u8; 32] {
    sha256_domain(STATE_DOMAIN, &canonical_peer_state(state))
}

pub fn canonical_durable_peer_state(state: &DurablePeerStateV0) -> CanonicalAuthorityBytes {
    let mut w = CanonicalWriter::new();
    w.array(2);
    w.unsigned(0);
    write_durable_state(&mut w, state, true);
    w.finish()
}

pub fn durable_peer_state_integrity_digest(state: &DurablePeerStateV0) -> [u8; 32] {
    let mut w = CanonicalWriter::new();
    w.array(2);
    w.unsigned(0);
    write_durable_state(&mut w, state, false);
    sha256_domain(DURABLE_DOMAIN, &w.finish())
}

fn write_peer_state(w: &mut CanonicalWriter, state: &PeerManagerStateM0) {
    w.array(17);
    w.unsigned(0);
    w.unsigned(lifecycle_tag(state.lifecycle));
    write_node_ref(w, state.self_ref);

    write_option(w, state.durable.as_ref(), |w, durable| {
        write_durable_state(w, durable, false);
    });

    write_option(w, state.pending_load_effect.as_ref(), |w, effect| {
        w.unsigned(effect.0);
    });

    write_option(w, state.pending_presence_write.as_ref(), |w, pending| {
        write_pending_presence(w, pending);
    });

    write_option(w, state.control.as_ref(), write_control_view);

    w.array(state.sessions.len());
    for (session_id, session) in &state.sessions {
        w.array(2);
        w.bytes(&session_id.0);
        write_session_state(w, session);
    }

    w.array(state.peer_presence.len());
    for (peer, incarnation) in &state.peer_presence {
        w.array(2);
        write_node_ref(w, *peer);
        w.unsigned(incarnation.0);
    }

    w.array(state.pending_probes.len());
    for (probe_id, probe) in &state.pending_probes {
        w.array(2);
        write_probe_id(w, probe_id);
        write_pending_probe(w, probe);
    }

    w.array(state.suspicions.len());
    for (peer, suspicion) in &state.suspicions {
        w.array(2);
        write_node_ref(w, *peer);
        write_suspicion(w, suspicion);
    }

    w.array(state.timer_generations.len());
    for (key, generation) in &state.timer_generations {
        w.array(2);
        write_timer_key(w, key);
        w.unsigned(*generation);
    }

    w.unsigned(state.next_effect_id);
    w.unsigned(state.next_send_id);
    w.unsigned(state.next_probe_sequence);
    w.unsigned(state.next_observation_sequence);
    write_selection(w, &state.selection);
}

fn write_mesh_message(w: &mut CanonicalWriter, message: &MeshMessage) {
    match message {
        MeshMessage::Ping {
            probe_id,
            sender_incarnation,
        } => {
            w.array(3);
            w.unsigned(0);
            write_probe_id(w, probe_id);
            w.unsigned(sender_incarnation.0);
        }
        MeshMessage::Ack {
            probe_id,
            responder_incarnation,
        } => {
            w.array(3);
            w.unsigned(1);
            write_probe_id(w, probe_id);
            w.unsigned(responder_incarnation.0);
        }
        MeshMessage::Suspect {
            subject,
            subject_incarnation,
            observation_id,
        } => {
            w.array(4);
            w.unsigned(2);
            write_node_ref(w, *subject);
            w.unsigned(subject_incarnation.0);
            write_observation_id(w, observation_id);
        }
        MeshMessage::Alive {
            subject,
            incarnation,
            nonce,
        } => {
            w.array(4);
            w.unsigned(3);
            write_node_ref(w, *subject);
            w.unsigned(incarnation.0);
            w.bytes(nonce);
        }
    }
}

fn write_event_kind(w: &mut CanonicalWriter, kind: &CoreEventKind) {
    match kind {
        CoreEventKind::StartRequested { selection_seed } => {
            w.array(2);
            w.unsigned(0);
            w.bytes(selection_seed);
        }
        CoreEventKind::DurableStateLoaded { effect_id, state } => {
            w.array(3);
            w.unsigned(1);
            w.unsigned(effect_id.0);
            write_option(w, state.as_ref(), |w, state| {
                write_durable_state(w, state, true);
            });
        }
        CoreEventKind::DurableStateLoadFailed { effect_id, error } => {
            w.array(3);
            w.unsigned(2);
            w.unsigned(effect_id.0);
            w.unsigned(persistence_error_tag(error));
        }
        CoreEventKind::PresencePersisted { effect_id, value } => {
            w.array(3);
            w.unsigned(3);
            w.unsigned(effect_id.0);
            w.unsigned(value.0);
        }
        CoreEventKind::PresencePersistFailed { effect_id, error } => {
            w.array(3);
            w.unsigned(4);
            w.unsigned(effect_id.0);
            w.unsigned(persistence_error_tag(error));
        }
        CoreEventKind::ControlViewReplaced { view } => {
            w.array(2);
            w.unsigned(5);
            write_control_view(w, view);
        }
        CoreEventKind::AuthenticatedSessionEstablished {
            session_id,
            peer,
            direction,
            peer_incarnation,
        } => {
            w.array(5);
            w.unsigned(6);
            w.bytes(&session_id.0);
            write_node_ref(w, *peer);
            w.unsigned(session_direction_tag(*direction));
            w.unsigned(peer_incarnation.0);
        }
        CoreEventKind::SessionClosed { session_id, reason } => {
            w.array(3);
            w.unsigned(7);
            w.bytes(&session_id.0);
            w.unsigned(close_reason_tag(*reason));
        }
        CoreEventKind::MeshMessageReceived {
            session_id,
            message,
        } => {
            w.array(3);
            w.unsigned(8);
            w.bytes(&session_id.0);
            write_mesh_message(w, message);
        }
        CoreEventKind::TimerFired { timer_id } => {
            w.array(2);
            w.unsigned(9);
            write_timer_id(w, timer_id);
        }
        CoreEventKind::ShutdownRequested => {
            w.array(1);
            w.unsigned(10);
        }
    }
}

fn write_effect_kind(w: &mut CanonicalWriter, kind: &CoreEffectKind) {
    match kind {
        CoreEffectKind::LoadDurablePeerState => {
            w.array(1);
            w.unsigned(0);
        }
        CoreEffectKind::PersistPresence {
            expected_previous,
            next,
        } => {
            w.array(3);
            w.unsigned(1);
            write_option(w, expected_previous.as_ref(), |w, value| {
                w.unsigned(value.0);
            });
            w.unsigned(next.0);
        }
        CoreEffectKind::ScheduleTimer { timer_id, deadline } => {
            w.array(3);
            w.unsigned(2);
            write_timer_id(w, timer_id);
            w.unsigned(deadline.0);
        }
        CoreEffectKind::CancelTimer { timer_id } => {
            w.array(2);
            w.unsigned(3);
            write_timer_id(w, timer_id);
        }
        CoreEffectKind::SendMeshMessage {
            send_id,
            session_id,
            message,
        } => {
            w.array(4);
            w.unsigned(4);
            w.unsigned(send_id.0);
            w.bytes(&session_id.0);
            write_mesh_message(w, message);
        }
        CoreEffectKind::CloseSession { session_id, reason } => {
            w.array(3);
            w.unsigned(5);
            w.bytes(&session_id.0);
            w.unsigned(close_reason_tag(*reason));
        }
        CoreEffectKind::EmitPeerEvent { event } => {
            w.array(2);
            w.unsigned(6);
            write_peer_event(w, event);
        }
        CoreEffectKind::RecordDiagnostic { diagnostic } => {
            w.array(2);
            w.unsigned(7);
            write_diagnostic(w, diagnostic);
        }
    }
}

fn write_peer_event(w: &mut CanonicalWriter, event: &PeerEvent) {
    let (tag, peer) = match event {
        PeerEvent::PeerHealthy(peer) => (0, peer),
        PeerEvent::PeerSuspect(peer) => (1, peer),
        PeerEvent::PeerUnreachable(peer) => (2, peer),
        PeerEvent::PeerRecovered(peer) => (3, peer),
    };
    w.array(2);
    w.unsigned(tag);
    write_node_ref(w, *peer);
}

fn write_diagnostic(w: &mut CanonicalWriter, diagnostic: &CoreDiagnostic) {
    match diagnostic {
        CoreDiagnostic::StaleTimer(timer_id) => {
            w.array(2);
            w.unsigned(0);
            write_timer_id(w, timer_id);
        }
        CoreDiagnostic::UnknownSession(session_id) => {
            w.array(2);
            w.unsigned(1);
            w.bytes(&session_id.0);
        }
        CoreDiagnostic::StaleAck(probe_id) => {
            w.array(2);
            w.unsigned(2);
            write_probe_id(w, probe_id);
        }
        CoreDiagnostic::StaleAlive {
            peer,
            received,
            known,
        } => {
            w.array(4);
            w.unsigned(3);
            write_node_ref(w, *peer);
            w.unsigned(received.0);
            w.unsigned(known.0);
        }
        CoreDiagnostic::OldGenerationSessionRejected(peer) => {
            w.array(2);
            w.unsigned(4);
            write_node_ref(w, *peer);
        }
        CoreDiagnostic::InvalidMessageSubject(peer) => {
            w.array(2);
            w.unsigned(5);
            write_node_ref(w, *peer);
        }
        CoreDiagnostic::PresencePersistenceFailed => {
            w.array(1);
            w.unsigned(6);
        }
        CoreDiagnostic::UnexpectedEventForLifecycle => {
            w.array(1);
            w.unsigned(7);
        }
        CoreDiagnostic::CapacityExceeded => {
            w.array(1);
            w.unsigned(8);
        }
        CoreDiagnostic::SuspicionAboveLocalIncarnation { alleged, local } => {
            w.array(3);
            w.unsigned(9);
            w.unsigned(alleged.0);
            w.unsigned(local.0);
        }
        CoreDiagnostic::ObservationIgnored(observation_id) => {
            w.array(2);
            w.unsigned(10);
            write_observation_id(w, observation_id);
        }
    }
}

fn write_durable_state(w: &mut CanonicalWriter, state: &DurablePeerStateV0, include_integrity: bool) {
    w.array(if include_integrity { 5 } else { 4 });
    w.unsigned(u64::from(state.format_version));
    write_node_ref(w, state.self_ref);
    w.unsigned(state.committed_presence.0);
    w.unsigned(state.committed_endpoint_sequence.0);
    if include_integrity {
        w.bytes(&state.integrity_tag);
    }
}

fn write_pending_presence(w: &mut CanonicalWriter, pending: &PendingPresenceWrite) {
    w.array(4);
    w.unsigned(pending.effect_id.0);
    w.unsigned(pending.expected_previous.0);
    w.unsigned(pending.next.0);
    write_presence_write_purpose(w, &pending.purpose);
}

fn write_presence_write_purpose(w: &mut CanonicalWriter, purpose: &PresenceWritePurpose) {
    match purpose {
        PresenceWritePurpose::StartupActivation => {
            w.array(1);
            w.unsigned(0);
        }
        PresenceWritePurpose::RefuteSuspicion {
            source_session,
            observation_id,
        } => {
            w.array(3);
            w.unsigned(1);
            w.bytes(&source_session.0);
            write_observation_id(w, observation_id);
        }
    }
}

fn write_control_view(w: &mut CanonicalWriter, view: &ControlViewM0) {
    w.array(3);
    w.bytes(&view.cluster_id.0);
    w.unsigned(view.epoch);
    w.array(view.members.len());
    for (node_id, member) in &view.members {
        w.array(2);
        w.bytes(&node_id.0);
        write_member(w, member);
    }
}

fn write_member(w: &mut CanonicalWriter, member: &MemberRecord) {
    w.array(4);
    w.bytes(&member.node_id.0);
    w.unsigned(member.current_generation.0);
    w.boolean(member.admitted);
    w.boolean(member.revoked);
}

fn write_session_state(w: &mut CanonicalWriter, session: &SessionStateM0) {
    w.array(5);
    w.bytes(&session.session_id.0);
    write_node_ref(w, session.peer);
    w.unsigned(session_direction_tag(session.direction));
    w.unsigned(session.peer_incarnation.0);
    w.unsigned(peer_health_tag(session.health));
}

fn write_pending_probe(w: &mut CanonicalWriter, probe: &PendingProbeM0) {
    w.array(6);
    write_probe_id(w, &probe.probe_id);
    write_node_ref(w, probe.target);
    write_option(w, probe.target_incarnation.as_ref(), |w, value| {
        w.unsigned(value.0);
    });
    w.unsigned(probe_phase_tag(probe.phase));
    w.unsigned(probe.started_at.0);
    write_timer_id(w, &probe.deadline);
}

fn write_suspicion(w: &mut CanonicalWriter, suspicion: &SuspicionM0) {
    w.array(5);
    write_node_ref(w, suspicion.subject);
    w.unsigned(suspicion.incarnation.0);
    w.unsigned(suspicion.started_at.0);
    write_timer_id(w, &suspicion.deadline);
    write_observation_id(w, &suspicion.local_observation);
}

fn write_selection(w: &mut CanonicalWriter, selection: &SelectionStateM0) {
    w.array(2);
    w.bytes(&selection.seed);
    w.array(selection.counters.len());
    for (domain, counter) in &selection.counters {
        w.array(2);
        w.unsigned(choice_domain_tag(*domain));
        w.unsigned(*counter);
    }
}

fn write_node_ref(w: &mut CanonicalWriter, peer: NodeRef) {
    w.array(3);
    w.bytes(&peer.cluster_id.0);
    w.bytes(&peer.node_id.0);
    w.unsigned(peer.generation.0);
}

fn write_probe_id(w: &mut CanonicalWriter, probe_id: &ProbeId) {
    w.array(3);
    write_node_ref(w, probe_id.origin);
    w.unsigned(probe_id.origin_incarnation.0);
    w.unsigned(probe_id.sequence);
}

fn write_observation_id(w: &mut CanonicalWriter, observation_id: &ObservationId) {
    w.array(3);
    write_node_ref(w, observation_id.observer);
    w.unsigned(observation_id.observer_incarnation.0);
    w.unsigned(observation_id.sequence);
}

fn write_timer_id(w: &mut CanonicalWriter, timer_id: &TimerId) {
    w.array(2);
    write_timer_key(w, &timer_id.key);
    w.unsigned(timer_id.generation);
}

fn write_timer_key(w: &mut CanonicalWriter, key: &TimerKey) {
    match key {
        TimerKey::ProbeInterval(peer) => {
            w.array(2);
            w.unsigned(0);
            write_node_ref(w, *peer);
        }
        TimerKey::ProbeDeadline(probe_id) => {
            w.array(2);
            w.unsigned(1);
            write_probe_id(w, probe_id);
        }
        TimerKey::SuspicionDeadline(peer) => {
            w.array(2);
            w.unsigned(2);
            write_node_ref(w, *peer);
        }
        TimerKey::Maintenance => {
            w.array(1);
            w.unsigned(3);
        }
        TimerKey::Exploration => {
            w.array(1);
            w.unsigned(4);
        }
    }
}

fn write_option<T>(
    w: &mut CanonicalWriter,
    value: Option<&T>,
    write_value: impl FnOnce(&mut CanonicalWriter, &T),
) {
    match value {
        None => {
            w.array(1);
            w.unsigned(0);
        }
        Some(value) => {
            w.array(2);
            w.unsigned(1);
            write_value(w, value);
        }
    }
}

fn event_source_tag(source: EventSource) -> u64 {
    match source {
        EventSource::Runtime => 0,
        EventSource::Persistence => 1,
        EventSource::Transport => 2,
        EventSource::Timer => 3,
        EventSource::Control => 4,
        EventSource::Operator => 5,
    }
}

fn persistence_error_tag(error: &PersistenceError) -> u64 {
    match error {
        PersistenceError::Unavailable => 0,
        PersistenceError::Corrupt => 1,
        PersistenceError::CompareFailed => 2,
        PersistenceError::IoFailure => 3,
        PersistenceError::UnsupportedVersion => 4,
    }
}

fn close_reason_tag(reason: CloseReason) -> u64 {
    match reason {
        CloseReason::LocalShutdown => 0,
        CloseReason::TransportLost => 1,
        CloseReason::NotCurrentMember => 2,
        CloseReason::Revoked => 3,
        CloseReason::GenerationMismatch => 4,
        CloseReason::ProtocolViolation => 5,
        CloseReason::Replaced => 6,
        CloseReason::RecoveryRequired => 7,
    }
}

fn lifecycle_tag(state: LifecycleState) -> u64 {
    match state {
        LifecycleState::Cold => 0,
        LifecycleState::LoadingDurableState => 1,
        LifecycleState::WaitingForPresenceCommit => 2,
        LifecycleState::NetworkActive => 3,
        LifecycleState::ShuttingDown => 4,
        LifecycleState::RecoveryRequired => 5,
    }
}

fn session_direction_tag(direction: SessionDirection) -> u64 {
    match direction {
        SessionDirection::Inbound => 0,
        SessionDirection::Outbound => 1,
    }
}

fn peer_health_tag(health: PeerHealth) -> u64 {
    match health {
        PeerHealth::Healthy => 0,
        PeerHealth::Suspect => 1,
        PeerHealth::Unreachable => 2,
    }
}

fn probe_phase_tag(phase: ProbePhase) -> u64 {
    match phase {
        ProbePhase::Direct => 0,
    }
}

fn choice_domain_tag(domain: ChoiceDomain) -> u64 {
    match domain {
        ChoiceDomain::ProbeTarget => 0,
        ChoiceDomain::BackoffJitter => 1,
        ChoiceDomain::PresenceNonce => 2,
    }
}

#[cfg(test)]
mod tests {
    use lesha_types::{ClusterId, NodeGeneration, NodeId};

    use super::*;

    fn node(byte: u8) -> NodeRef {
        NodeRef {
            cluster_id: ClusterId([1; 16]),
            node_id: NodeId([byte; 32]),
            generation: NodeGeneration(1),
        }
    }

    #[test]
    fn state_digest_changes_with_future_decision_state() {
        let mut left = PeerManagerStateM0::new(node(7));
        let right = left.clone();
        assert_eq!(peer_state_digest(&left), peer_state_digest(&right));

        left.next_probe_sequence += 1;
        assert_ne!(peer_state_digest(&left), peer_state_digest(&right));
    }

    #[test]
    fn message_digest_is_domain_separated_and_stable() {
        let message = MeshMessage::Alive {
            subject: node(9),
            incarnation: lesha_types::PresenceIncarnation(4),
            nonce: [5; 16],
        };
        assert_eq!(mesh_message_digest(&message), mesh_message_digest(&message));
        assert_ne!(mesh_message_digest(&message), core_effects_digest(&[]));
    }
}
