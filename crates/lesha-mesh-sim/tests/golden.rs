use std::collections::BTreeMap;

use lesha_mesh_sim::{verify_exact_replay, MeshMessageKind, PresencePersistFault, Simulation};
use lesha_peer_core::{
    CloseReason, ControlViewM0, CoreConfig, CoreEffectKind, CoreEventKind, LifecycleState,
    MemberRecord, MeshMessage, PeerHealth,
};
use lesha_types::{
    ClusterId, MonoDuration, NodeGeneration, NodeId, NodeRef, PresenceIncarnation, SessionId,
};

fn node(byte: u8) -> NodeRef {
    NodeRef {
        cluster_id: ClusterId([1; 16]),
        node_id: NodeId([byte; 32]),
        generation: NodeGeneration(1),
    }
}

fn control(a: NodeRef, b: NodeRef) -> ControlViewM0 {
    let mut members = BTreeMap::new();
    for peer in [a, b] {
        members.insert(
            peer.node_id,
            MemberRecord {
                node_id: peer.node_id,
                current_generation: peer.generation,
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

fn run_golden() -> Simulation {
    let a = node(10);
    let b = node(11);

    let a_config = CoreConfig {
        probe_interval: MonoDuration(10),
        probe_timeout: MonoDuration(5),
        suspicion_timeout: MonoDuration(20),
        ..Default::default()
    };

    let b_config = CoreConfig {
        probe_interval: MonoDuration(1_000),
        ..a_config.clone()
    };

    let mut sim = Simulation::default();
    sim.add_node(a, a_config).unwrap();
    sim.add_node(b, b_config).unwrap();

    sim.start_node(a.node_id, [0xAA; 32]).unwrap();
    sim.start_node(b.node_id, [0xBB; 32]).unwrap();
    sim.run_until_idle(32).unwrap();
    assert!(sim.all_network_active());

    let view = control(a, b);
    sim.replace_control(a.node_id, view.clone()).unwrap();
    sim.replace_control(b.node_id, view).unwrap();
    sim.run_until_idle(8).unwrap();

    let a_session = SessionId([0xA1; 32]);
    let b_session = SessionId([0xB1; 32]);
    sim.connect_authenticated(a.node_id, a_session, b.node_id, b_session)
        .unwrap();
    assert_eq!(sim.run_steps(2).unwrap(), 2);

    // First probe succeeds.
    assert_eq!(sim.run_steps(3).unwrap(), 3);
    assert!(sim.node(a.node_id).unwrap().state.pending_probes.is_empty());

    // Drop exactly the next ACK from B. The next direct probe must become
    // SUSPECT, B must durably bump its incarnation, then ALIVE must refute it.
    sim.faults
        .drop_next_message(b.node_id, MeshMessageKind::Ack);

    sim.run_until(20, |sim| {
        sim.durable.committed_presence(b.node_id) == Some(PresenceIncarnation(2))
            && sim
                .node(a.node_id)
                .ok()
                .and_then(|node| node.state.peer_presence.get(&b).copied())
                == Some(PresenceIncarnation(2))
            && !sim
                .node(a.node_id)
                .map(|node| node.state.suspicions.contains_key(&b))
                .unwrap_or(true)
    })
    .unwrap();

    let a_state = &sim.node(a.node_id).unwrap().state;
    let b_state = &sim.node(b.node_id).unwrap().state;

    assert_eq!(b_state.current_presence(), Some(PresenceIncarnation(2)));
    assert_eq!(a_state.peer_presence.get(&b), Some(&PresenceIncarnation(2)));
    assert!(a_state
        .sessions
        .values()
        .any(|session| session.peer == b && session.health == PeerHealth::Healthy));

    let saw_suspect = sim.trace.records.iter().any(|record| {
        record.effects.iter().any(|effect| {
            matches!(
                &effect.kind,
                CoreEffectKind::SendMeshMessage {
                    message: MeshMessage::Suspect { subject, .. },
                    ..
                } if *subject == b
            )
        })
    });
    let saw_alive = sim.trace.records.iter().any(|record| {
        record.effects.iter().any(|effect| {
            matches!(
                &effect.kind,
                CoreEffectKind::SendMeshMessage {
                    message: MeshMessage::Alive {
                        subject,
                        incarnation,
                        ..
                    },
                    ..
                } if *subject == b && *incarnation == PresenceIncarnation(2)
            )
        })
    });

    assert!(saw_suspect);
    assert!(saw_alive);
    assert_eq!(a_state.control.as_ref().unwrap().epoch, 1);
    assert_eq!(b_state.control.as_ref().unwrap().epoch, 1);

    sim
}

fn setup_connected_after_first_probe() -> (Simulation, NodeRef, NodeRef) {
    let a = node(10);
    let b = node(11);

    let a_config = CoreConfig {
        probe_interval: MonoDuration(10),
        probe_timeout: MonoDuration(5),
        suspicion_timeout: MonoDuration(20),
        ..Default::default()
    };

    let b_config = CoreConfig {
        probe_interval: MonoDuration(1_000),
        ..a_config.clone()
    };

    let mut sim = Simulation::default();
    sim.add_node(a, a_config).unwrap();
    sim.add_node(b, b_config).unwrap();

    sim.start_node(a.node_id, [0xAA; 32]).unwrap();
    sim.start_node(b.node_id, [0xBB; 32]).unwrap();
    sim.run_until_idle(32).unwrap();

    let view = control(a, b);
    sim.replace_control(a.node_id, view.clone()).unwrap();
    sim.replace_control(b.node_id, view).unwrap();
    sim.run_until_idle(8).unwrap();

    sim.connect_authenticated(
        a.node_id,
        SessionId([0xA1; 32]),
        b.node_id,
        SessionId([0xB1; 32]),
    )
    .unwrap();
    assert_eq!(sim.run_steps(2).unwrap(), 2);

    assert_eq!(sim.run_steps(3).unwrap(), 3);
    assert!(sim.node(a.node_id).unwrap().state.pending_probes.is_empty());

    (sim, a, b)
}

#[test]
fn two_node_suspect_refutation_golden_trace() {
    let sim = run_golden();
    assert_ne!(sim.trace.trace_root(), [0; 32]);
}

#[test]
fn same_seed_and_fault_plan_replays_exactly() {
    let first = run_golden();
    let second = run_golden();

    assert_eq!(first.trace.trace_root(), second.trace.trace_root());
    verify_exact_replay(&first.trace, &second.trace).unwrap();
}

#[test]
fn fail_before_presence_commit_never_advances_durable_state() {
    let b = node(11);
    let mut sim = Simulation::default();
    sim.add_node(b, CoreConfig::default()).unwrap();
    sim.faults
        .push_persist_fault(b.node_id, PresencePersistFault::FailBeforeCommit);

    sim.start_node(b.node_id, [0xBB; 32]).unwrap();
    sim.run_until_idle(16).unwrap();

    assert_eq!(sim.durable.committed_presence(b.node_id), None);
    assert_eq!(
        sim.node(b.node_id).unwrap().state.lifecycle,
        LifecycleState::RecoveryRequired
    );
}

#[test]
fn commit_then_crash_never_reuses_committed_incarnation() {
    let b = node(11);
    let mut sim = Simulation::default();
    sim.add_node(b, CoreConfig::default()).unwrap();
    sim.faults
        .push_persist_fault(b.node_id, PresencePersistFault::CommitThenCrash);

    sim.start_node(b.node_id, [0xBB; 32]).unwrap();
    sim.run_until(16, |sim| {
        sim.node(b.node_id)
            .map(|node| node.state.lifecycle == LifecycleState::NetworkActive)
            .unwrap_or(false)
    })
    .unwrap();

    assert_eq!(
        sim.durable.committed_presence(b.node_id),
        Some(PresenceIncarnation(2))
    );
    assert_eq!(
        sim.node(b.node_id).unwrap().state.current_presence(),
        Some(PresenceIncarnation(2))
    );

    let acknowledged_first_commit = sim.trace.records.iter().any(|record| {
        matches!(
            &record.event.kind,
            CoreEventKind::PresencePersisted { value, .. }
                if *value == PresenceIncarnation(1)
        )
    });
    assert!(!acknowledged_first_commit);
}

#[test]
fn refutation_fail_before_commit_never_sends_uncommitted_alive() {
    let (mut sim, _a, b) = setup_connected_after_first_probe();

    sim.faults
        .push_persist_fault(b.node_id, PresencePersistFault::FailBeforeCommit);
    sim.faults
        .drop_next_message(b.node_id, MeshMessageKind::Ack);

    sim.run_until(24, |sim| {
        sim.node(b.node_id)
            .map(|node| node.state.lifecycle == LifecycleState::RecoveryRequired)
            .unwrap_or(false)
    })
    .unwrap();

    assert_eq!(
        sim.durable.committed_presence(b.node_id),
        Some(PresenceIncarnation(1))
    );

    let sent_uncommitted_alive = sim.trace.records.iter().any(|record| {
        record.effects.iter().any(|effect| {
            matches!(
                &effect.kind,
                CoreEffectKind::SendMeshMessage {
                    message: MeshMessage::Alive {
                        subject,
                        incarnation,
                        ..
                    },
                    ..
                } if *subject == b && *incarnation == PresenceIncarnation(2)
            )
        })
    });
    assert!(!sent_uncommitted_alive);
}

#[test]
fn refutation_commit_then_crash_skips_to_next_incarnation_without_alive() {
    let (mut sim, a, b) = setup_connected_after_first_probe();

    sim.faults
        .push_persist_fault(b.node_id, PresencePersistFault::CommitThenCrash);
    sim.faults
        .drop_next_message(b.node_id, MeshMessageKind::Ack);

    sim.run_until(32, |sim| {
        sim.durable.committed_presence(b.node_id) == Some(PresenceIncarnation(3))
            && sim
                .node(b.node_id)
                .map(|node| node.state.lifecycle == LifecycleState::NetworkActive)
                .unwrap_or(false)
    })
    .unwrap();

    assert_eq!(
        sim.node(b.node_id).unwrap().state.current_presence(),
        Some(PresenceIncarnation(3))
    );

    let acknowledged_crashed_commit = sim.trace.records.iter().any(|record| {
        matches!(
            &record.event.kind,
            CoreEventKind::PresencePersisted { value, .. }
                if *value == PresenceIncarnation(2)
        )
    });
    assert!(!acknowledged_crashed_commit);

    let sent_crashed_incarnation_alive = sim.trace.records.iter().any(|record| {
        record.effects.iter().any(|effect| {
            matches!(
                &effect.kind,
                CoreEffectKind::SendMeshMessage {
                    message: MeshMessage::Alive {
                        subject,
                        incarnation,
                        ..
                    },
                    ..
                } if *subject == b && *incarnation == PresenceIncarnation(2)
            )
        })
    });
    assert!(!sent_crashed_incarnation_alive);

    assert!(!sim
        .node(a.node_id)
        .unwrap()
        .state
        .sessions
        .values()
        .any(|session| session.peer == b));

    let peer_observed_transport_loss = sim.trace.records.iter().any(|record| {
        record.target == a.node_id
            && matches!(
                &record.event.kind,
                CoreEventKind::SessionClosed {
                    reason: CloseReason::TransportLost,
                    ..
                }
            )
    });
    assert!(peer_observed_transport_loss);
}


#[test]
fn same_seed_repeats_100_times_with_identical_trace_root() {
    let expected = run_golden().trace.trace_root();
    for _ in 1..100 {
        assert_eq!(run_golden().trace.trace_root(), expected);
    }
}
