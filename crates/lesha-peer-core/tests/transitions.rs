use std::collections::BTreeMap;

use lesha_peer_core::*;
use lesha_types::*;

fn node(byte: u8, generation: u64) -> NodeRef {
    NodeRef {
        cluster_id: ClusterId([1; 16]),
        node_id: NodeId([byte; 32]),
        generation: NodeGeneration(generation),
    }
}

fn control(a: NodeRef, b: NodeRef) -> ControlViewM0 {
    let mut members = BTreeMap::new();
    for n in [a, b] {
        members.insert(
            n.node_id,
            MemberRecord {
                node_id: n.node_id,
                current_generation: n.generation,
                admitted: true,
                revoked: false,
            },
        );
    }
    ControlViewM0 {
        cluster_id: a.cluster_id,
        epoch: 1,
        members,
    }
}

fn event(at: u64, kind: CoreEventKind) -> CoreEvent {
    CoreEvent {
        observed_at: MonotonicTime(at),
        source: EventSource::Runtime,
        kind,
    }
}

#[test]
fn start_emits_load_only() {
    let a = node(10, 1);
    let cfg = CoreConfig::default();
    let mut state = PeerManagerStateM0::new(a);
    let out = step(
        &cfg,
        &mut state,
        event(0, CoreEventKind::StartRequested { selection_seed: [7; 32] }),
    );
    assert_eq!(state.lifecycle, LifecycleState::LoadingDurableState);
    assert_eq!(out.effects.len(), 1);
    assert!(matches!(&out.effects[0].kind, CoreEffectKind::LoadDurablePeerState));
}

#[test]
fn liveness_does_not_mutate_control_view() {
    let a = node(10, 1);
    let b = node(11, 1);
    let cfg = CoreConfig::default();
    let mut state = PeerManagerStateM0::new(a);
    state.lifecycle = LifecycleState::NetworkActive;
    state.durable = Some(DurablePeerStateV0 {
        format_version: 0,
        self_ref: a,
        committed_presence: PresenceIncarnation(1),
        committed_endpoint_sequence: EndpointSequence(0),
        integrity_tag: [0; 32],
    });
    state.control = Some(control(a, b));
    let before = state.control.clone();
    let _ = step(
        &cfg,
        &mut state,
        event(
            0,
            CoreEventKind::AuthenticatedSessionEstablished {
                session_id: SessionId([2; 32]),
                peer: b,
                direction: SessionDirection::Outbound,
                peer_incarnation: PresenceIncarnation(1),
            },
        ),
    );
    assert_eq!(before, state.control);
}
