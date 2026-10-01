pub mod canonical;
pub mod config;
pub mod effect;
pub mod event;
pub mod invariant;
pub mod message;
pub mod state;
pub mod timer;

use lesha_types::{
    EffectId, EndpointSequence, MonotonicTime, PresenceIncarnation, SendId, SessionId,
};

pub use canonical::*;
pub use config::*;
pub use effect::*;
pub use event::*;
pub use message::*;
pub use state::*;
pub use timer::*;

fn alloc_effect_id(state: &mut PeerManagerStateM0) -> Option<EffectId> {
    let id = EffectId(state.next_effect_id);
    state.next_effect_id = state.next_effect_id.checked_add(1)?;
    Some(id)
}

fn alloc_send_id(state: &mut PeerManagerStateM0) -> Option<SendId> {
    let id = SendId(state.next_send_id);
    state.next_send_id = state.next_send_id.checked_add(1)?;
    Some(id)
}

fn push_effect(state: &mut PeerManagerStateM0, out: &mut StepOutput, kind: CoreEffectKind) {
    if let Some(effect_id) = alloc_effect_id(state) {
        out.effects.push(CoreEffect { effect_id, kind });
    } else {
        state.lifecycle = LifecycleState::RecoveryRequired;
    }
}

fn arm_timer(
    state: &mut PeerManagerStateM0,
    out: &mut StepOutput,
    key: TimerKey,
    deadline: MonotonicTime,
) -> Option<TimerId> {
    let current = state.timer_generations.get(&key).copied().unwrap_or(0);
    let generation = current.checked_add(1)?;
    state.timer_generations.insert(key.clone(), generation);
    let timer_id = TimerId { key, generation };
    push_effect(
        state,
        out,
        CoreEffectKind::ScheduleTimer {
            timer_id: timer_id.clone(),
            deadline,
        },
    );
    Some(timer_id)
}

fn current_timer(state: &PeerManagerStateM0, timer_id: &TimerId) -> bool {
    state
        .timer_generations
        .get(&timer_id.key)
        .map(|g| *g == timer_id.generation)
        .unwrap_or(false)
}

fn current_session_for_peer(
    state: &PeerManagerStateM0,
    peer: lesha_types::NodeRef,
) -> Option<SessionId> {
    state
        .sessions
        .iter()
        .find_map(|(id, session)| (session.peer == peer).then_some(*id))
}

fn derive_nonce(state: &mut PeerManagerStateM0) -> [u8; 16] {
    let seed = state.selection.seed;
    let counter = state
        .selection
        .counters
        .entry(ChoiceDomain::PresenceNonce)
        .or_insert(0);
    let c = *counter;
    *counter = c.saturating_add(1);
    let mut out = [0u8; 16];
    for i in 0..16 {
        let seed_byte = seed[i] as u64;
        let mixed = seed_byte
            .wrapping_add(c.rotate_left((i % 8) as u32))
            .wrapping_add((i as u64).wrapping_mul(0x9d));
        out[i] = mixed as u8;
    }
    out
}

fn enter_recovery(state: &mut PeerManagerStateM0, out: &mut StepOutput) {
    state.lifecycle = LifecycleState::RecoveryRequired;
    let sessions: Vec<SessionId> = state.sessions.keys().copied().collect();
    for session_id in sessions {
        push_effect(
            state,
            out,
            CoreEffectKind::CloseSession {
                session_id,
                reason: CloseReason::RecoveryRequired,
            },
        );
    }
}

pub fn step(cfg: &CoreConfig, state: &mut PeerManagerStateM0, event: CoreEvent) -> StepOutput {
    let mut out = StepOutput::default();

    match event.kind {
        CoreEventKind::StartRequested { selection_seed } => {
            if state.lifecycle != LifecycleState::Cold {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::RecordDiagnostic {
                        diagnostic: CoreDiagnostic::UnexpectedEventForLifecycle,
                    },
                );
                return out;
            }
            state.selection.seed = selection_seed;
            state.lifecycle = LifecycleState::LoadingDurableState;
            if let Some(effect_id) = alloc_effect_id(state) {
                state.pending_load_effect = Some(effect_id);
                out.effects.push(CoreEffect {
                    effect_id,
                    kind: CoreEffectKind::LoadDurablePeerState,
                });
            } else {
                state.lifecycle = LifecycleState::RecoveryRequired;
            }
        }

        CoreEventKind::DurableStateLoaded {
            effect_id,
            state: loaded,
        } => {
            if state.lifecycle != LifecycleState::LoadingDurableState
                || state.pending_load_effect != Some(effect_id)
            {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::RecordDiagnostic {
                        diagnostic: CoreDiagnostic::UnexpectedEventForLifecycle,
                    },
                );
                return out;
            }
            state.pending_load_effect = None;
            let expected_previous = loaded.as_ref().map(|d| d.committed_presence);
            let previous = match loaded.as_ref() {
                Some(durable) if durable.self_ref == state.self_ref => durable.committed_presence,
                Some(_) => {
                    enter_recovery(state, &mut out);
                    return out;
                }
                None => PresenceIncarnation(0),
            };
            state.durable = loaded;
            let next = match previous.0.checked_add(1) {
                Some(v) => PresenceIncarnation(v),
                None => {
                    enter_recovery(state, &mut out);
                    return out;
                }
            };
            let effect_id = match alloc_effect_id(state) {
                Some(id) => id,
                None => {
                    enter_recovery(state, &mut out);
                    return out;
                }
            };
            state.pending_presence_write = Some(PendingPresenceWrite {
                effect_id,
                expected_previous: previous,
                next,
                purpose: PresenceWritePurpose::StartupActivation,
            });
            state.lifecycle = LifecycleState::WaitingForPresenceCommit;
            out.effects.push(CoreEffect {
                effect_id,
                kind: CoreEffectKind::PersistPresence {
                    expected_previous,
                    next,
                },
            });
        }

        CoreEventKind::DurableStateLoadFailed { effect_id, .. } => {
            if state.pending_load_effect == Some(effect_id) {
                state.pending_load_effect = None;
                enter_recovery(state, &mut out);
            }
        }

        CoreEventKind::PresencePersisted { effect_id, value } => {
            let pending = match state.pending_presence_write.clone() {
                Some(p) if p.effect_id == effect_id && p.next == value => p,
                _ => {
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::RecordDiagnostic {
                            diagnostic: CoreDiagnostic::UnexpectedEventForLifecycle,
                        },
                    );
                    return out;
                }
            };
            let endpoint_sequence = state
                .durable
                .as_ref()
                .map(|d| d.committed_endpoint_sequence)
                .unwrap_or(EndpointSequence(0));
            state.durable = Some(DurablePeerStateV0 {
                format_version: 0,
                self_ref: state.self_ref,
                committed_presence: value,
                committed_endpoint_sequence: endpoint_sequence,
                integrity_tag: [0; 32],
            });
            state.pending_presence_write = None;
            match pending.purpose {
                PresenceWritePurpose::StartupActivation => {
                    state.lifecycle = LifecycleState::NetworkActive;
                }
                PresenceWritePurpose::RefuteSuspicion { source_session, .. } => {
                    if state.lifecycle == LifecycleState::NetworkActive
                        && state.sessions.contains_key(&source_session)
                    {
                        let nonce = derive_nonce(state);
                        if let Some(send_id) = alloc_send_id(state) {
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::SendMeshMessage {
                                    send_id,
                                    session_id: source_session,
                                    message: MeshMessage::Alive {
                                        subject: state.self_ref,
                                        incarnation: value,
                                        nonce,
                                    },
                                },
                            );
                        }
                    }
                }
            }
        }

        CoreEventKind::PresencePersistFailed { effect_id, .. } => {
            if state
                .pending_presence_write
                .as_ref()
                .map(|p| p.effect_id == effect_id)
                .unwrap_or(false)
            {
                state.pending_presence_write = None;
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::RecordDiagnostic {
                        diagnostic: CoreDiagnostic::PresencePersistenceFailed,
                    },
                );
                enter_recovery(state, &mut out);
            }
        }

        CoreEventKind::ControlViewReplaced { view } => {
            state.control = Some(view);
            let session_ids: Vec<SessionId> = state.sessions.keys().copied().collect();
            for session_id in session_ids {
                let session = match state.sessions.get(&session_id) {
                    Some(s) => s.clone(),
                    None => continue,
                };
                let control = match state.control.as_ref() {
                    Some(c) => c,
                    None => continue,
                };
                if control.is_current_member(session.peer) {
                    continue;
                }
                let reason = match control.member(session.peer.node_id) {
                    Some(m) if m.revoked => CloseReason::Revoked,
                    Some(m) if m.current_generation != session.peer.generation => {
                        CloseReason::GenerationMismatch
                    }
                    _ => CloseReason::NotCurrentMember,
                };
                state.sessions.remove(&session_id);
                state.suspicions.remove(&session.peer);
                state.peer_presence.remove(&session.peer);
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::CloseSession { session_id, reason },
                );
            }
        }

        CoreEventKind::AuthenticatedSessionEstablished {
            session_id,
            peer,
            direction,
            peer_incarnation,
        } => {
            if state.lifecycle != LifecycleState::NetworkActive {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::CloseSession {
                        session_id,
                        reason: CloseReason::ProtocolViolation,
                    },
                );
                return out;
            }
            let membership_decision = match state.control.as_ref() {
                None => Err(CloseReason::NotCurrentMember),
                Some(control) if control.is_current_member(peer) => Ok(()),
                Some(control) => {
                    let reason = match control.member(peer.node_id) {
                        Some(m) if m.revoked => CloseReason::Revoked,
                        Some(m) if m.current_generation != peer.generation => {
                            CloseReason::GenerationMismatch
                        }
                        _ => CloseReason::NotCurrentMember,
                    };
                    Err(reason)
                }
            };
            if let Err(reason) = membership_decision {
                if reason == CloseReason::GenerationMismatch {
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::RecordDiagnostic {
                            diagnostic: CoreDiagnostic::OldGenerationSessionRejected(peer),
                        },
                    );
                }
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::CloseSession { session_id, reason },
                );
                return out;
            }
            if state.sessions.len() >= cfg.max_sessions as usize {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::RecordDiagnostic {
                        diagnostic: CoreDiagnostic::CapacityExceeded,
                    },
                );
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::CloseSession {
                        session_id,
                        reason: CloseReason::Replaced,
                    },
                );
                return out;
            }
            state.peer_presence.insert(peer, peer_incarnation);
            state.sessions.insert(
                session_id,
                SessionStateM0 {
                    session_id,
                    peer,
                    direction,
                    peer_incarnation,
                    health: PeerHealth::Healthy,
                },
            );
            let deadline = match event.observed_at.checked_add(cfg.probe_interval) {
                Some(t) => t,
                None => {
                    enter_recovery(state, &mut out);
                    return out;
                }
            };
            let _ = arm_timer(state, &mut out, TimerKey::ProbeInterval(peer), deadline);
            push_effect(
                state,
                &mut out,
                CoreEffectKind::EmitPeerEvent {
                    event: PeerEvent::PeerHealthy(peer),
                },
            );
        }

        CoreEventKind::SessionClosed { session_id, .. } => {
            if let Some(session) = state.sessions.remove(&session_id) {
                state.pending_probes.retain(|_, p| p.target != session.peer);
            }
        }

        CoreEventKind::MeshMessageReceived {
            session_id,
            message,
        } => {
            let session = match state.sessions.get(&session_id).cloned() {
                Some(s) => s,
                None => {
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::RecordDiagnostic {
                            diagnostic: CoreDiagnostic::UnknownSession(session_id),
                        },
                    );
                    return out;
                }
            };
            match message {
                MeshMessage::Ping {
                    probe_id,
                    sender_incarnation,
                } => {
                    let known = state
                        .peer_presence
                        .get(&session.peer)
                        .copied()
                        .unwrap_or(PresenceIncarnation(0));
                    if sender_incarnation >= known {
                        state.peer_presence.insert(session.peer, sender_incarnation);
                    }
                    let local = state.current_presence();
                    if let Some(local) = local {
                        if let Some(send_id) = alloc_send_id(state) {
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::SendMeshMessage {
                                    send_id,
                                    session_id,
                                    message: MeshMessage::Ack {
                                        probe_id,
                                        responder_incarnation: local,
                                    },
                                },
                            );
                        }
                    }
                }

                MeshMessage::Ack {
                    probe_id,
                    responder_incarnation,
                } => {
                    let pending = match state.pending_probes.get(&probe_id).cloned() {
                        Some(p) if p.target == session.peer => p,
                        _ => {
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::RecordDiagnostic {
                                    diagnostic: CoreDiagnostic::StaleAck(probe_id),
                                },
                            );
                            return out;
                        }
                    };
                    let known = state
                        .peer_presence
                        .get(&session.peer)
                        .copied()
                        .unwrap_or(PresenceIncarnation(0));
                    if responder_incarnation < known {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::StaleAlive {
                                    peer: session.peer,
                                    received: responder_incarnation,
                                    known,
                                },
                            },
                        );
                        return out;
                    }
                    state
                        .peer_presence
                        .insert(session.peer, responder_incarnation);
                    state.pending_probes.remove(&probe_id);
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::CancelTimer {
                            timer_id: pending.deadline,
                        },
                    );
                    let was_unhealthy = state
                        .sessions
                        .get(&session_id)
                        .map(|s| s.health != PeerHealth::Healthy)
                        .unwrap_or(false);
                    if let Some(s) = state.sessions.get_mut(&session_id) {
                        s.peer_incarnation = responder_incarnation;
                        s.health = PeerHealth::Healthy;
                    }
                    if was_unhealthy {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::EmitPeerEvent {
                                event: PeerEvent::PeerRecovered(session.peer),
                            },
                        );
                    }
                }

                MeshMessage::Suspect {
                    subject,
                    subject_incarnation,
                    observation_id,
                } => {
                    if subject != state.self_ref {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::InvalidMessageSubject(subject),
                            },
                        );
                        return out;
                    }
                    let local = match state.current_presence() {
                        Some(v) => v,
                        None => return out,
                    };
                    if subject_incarnation < local {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::ObservationIgnored(observation_id),
                            },
                        );
                        return out;
                    }
                    if subject_incarnation > local {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::SuspicionAboveLocalIncarnation {
                                    alleged: subject_incarnation,
                                    local,
                                },
                            },
                        );
                        return out;
                    }
                    if state.pending_presence_write.is_some() {
                        return out;
                    }
                    let next = match local.0.checked_add(1) {
                        Some(v) => PresenceIncarnation(v),
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    let effect_id = match alloc_effect_id(state) {
                        Some(id) => id,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    state.pending_presence_write = Some(PendingPresenceWrite {
                        effect_id,
                        expected_previous: local,
                        next,
                        purpose: PresenceWritePurpose::RefuteSuspicion {
                            source_session: session_id,
                            observation_id,
                        },
                    });
                    out.effects.push(CoreEffect {
                        effect_id,
                        kind: CoreEffectKind::PersistPresence {
                            expected_previous: Some(local),
                            next,
                        },
                    });
                }

                MeshMessage::Alive {
                    subject,
                    incarnation,
                    ..
                } => {
                    if session.peer != subject {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::InvalidMessageSubject(subject),
                            },
                        );
                        return out;
                    }
                    if !state
                        .control
                        .as_ref()
                        .map(|c| c.is_current_member(subject))
                        .unwrap_or(false)
                    {
                        return out;
                    }
                    let known = state
                        .peer_presence
                        .get(&subject)
                        .copied()
                        .unwrap_or(PresenceIncarnation(0));
                    if incarnation < known {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::StaleAlive {
                                    peer: subject,
                                    received: incarnation,
                                    known,
                                },
                            },
                        );
                        return out;
                    }
                    let suspected = state.suspicions.get(&subject).cloned();
                    state.peer_presence.insert(subject, incarnation);
                    if let Some(suspicion) = suspected {
                        if incarnation > suspicion.incarnation {
                            state.suspicions.remove(&subject);
                            if let Some(s) = state.sessions.get_mut(&session_id) {
                                s.peer_incarnation = incarnation;
                                s.health = PeerHealth::Healthy;
                            }
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::CancelTimer {
                                    timer_id: suspicion.deadline,
                                },
                            );
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::EmitPeerEvent {
                                    event: PeerEvent::PeerRecovered(subject),
                                },
                            );
                        }
                    }
                }
            }
        }

        CoreEventKind::TimerFired { timer_id } => {
            if !current_timer(state, &timer_id) {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::RecordDiagnostic {
                        diagnostic: CoreDiagnostic::StaleTimer(timer_id),
                    },
                );
                return out;
            }
            match timer_id.key.clone() {
                TimerKey::ProbeInterval(peer) => {
                    if state.lifecycle != LifecycleState::NetworkActive {
                        return out;
                    }
                    if state.pending_probes.len() >= cfg.max_pending_probes as usize {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::RecordDiagnostic {
                                diagnostic: CoreDiagnostic::CapacityExceeded,
                            },
                        );
                        return out;
                    }
                    let session_id = match current_session_for_peer(state, peer) {
                        Some(id) => id,
                        None => return out,
                    };
                    let local_incarnation = match state.current_presence() {
                        Some(v) => v,
                        None => return out,
                    };
                    let sequence = state.next_probe_sequence;
                    state.next_probe_sequence = match sequence.checked_add(1) {
                        Some(v) => v,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    let probe_id = ProbeId {
                        origin: state.self_ref,
                        origin_incarnation: local_incarnation,
                        sequence,
                    };
                    let deadline_at = match event.observed_at.checked_add(cfg.probe_timeout) {
                        Some(v) => v,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    let deadline = match arm_timer(
                        state,
                        &mut out,
                        TimerKey::ProbeDeadline(probe_id),
                        deadline_at,
                    ) {
                        Some(t) => t,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    state.pending_probes.insert(
                        probe_id,
                        PendingProbeM0 {
                            probe_id,
                            target: peer,
                            target_incarnation: state.peer_presence.get(&peer).copied(),
                            phase: ProbePhase::Direct,
                            started_at: event.observed_at,
                            deadline,
                        },
                    );
                    if let Some(send_id) = alloc_send_id(state) {
                        push_effect(
                            state,
                            &mut out,
                            CoreEffectKind::SendMeshMessage {
                                send_id,
                                session_id,
                                message: MeshMessage::Ping {
                                    probe_id,
                                    sender_incarnation: local_incarnation,
                                },
                            },
                        );
                    }
                    if let Some(next_at) = event.observed_at.checked_add(cfg.probe_interval) {
                        let _ = arm_timer(state, &mut out, TimerKey::ProbeInterval(peer), next_at);
                    }
                }

                TimerKey::ProbeDeadline(probe_id) => {
                    let pending = match state.pending_probes.remove(&probe_id) {
                        Some(p) if p.deadline == timer_id => p,
                        _ => return out,
                    };
                    let incarnation = state
                        .peer_presence
                        .get(&pending.target)
                        .copied()
                        .or(pending.target_incarnation)
                        .unwrap_or(PresenceIncarnation(0));
                    let sequence = state.next_observation_sequence;
                    state.next_observation_sequence = match sequence.checked_add(1) {
                        Some(v) => v,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    let observation_id = ObservationId {
                        observer: state.self_ref,
                        observer_incarnation: state
                            .current_presence()
                            .unwrap_or(PresenceIncarnation(0)),
                        sequence,
                    };
                    let suspicion_deadline_at =
                        match event.observed_at.checked_add(cfg.suspicion_timeout) {
                            Some(v) => v,
                            None => {
                                enter_recovery(state, &mut out);
                                return out;
                            }
                        };
                    let suspicion_deadline = match arm_timer(
                        state,
                        &mut out,
                        TimerKey::SuspicionDeadline(pending.target),
                        suspicion_deadline_at,
                    ) {
                        Some(t) => t,
                        None => {
                            enter_recovery(state, &mut out);
                            return out;
                        }
                    };
                    state.suspicions.insert(
                        pending.target,
                        SuspicionM0 {
                            subject: pending.target,
                            incarnation,
                            started_at: event.observed_at,
                            deadline: suspicion_deadline,
                            local_observation: observation_id,
                        },
                    );
                    let target_session_id = current_session_for_peer(state, pending.target);
                    if let Some(target_session_id) = target_session_id {
                        if let Some(s) = state.sessions.get_mut(&target_session_id) {
                            s.health = PeerHealth::Suspect;
                        }
                    }
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::EmitPeerEvent {
                            event: PeerEvent::PeerSuspect(pending.target),
                        },
                    );
                    if let Some(session_id) = target_session_id {
                        if let Some(send_id) = alloc_send_id(state) {
                            push_effect(
                                state,
                                &mut out,
                                CoreEffectKind::SendMeshMessage {
                                    send_id,
                                    session_id,
                                    message: MeshMessage::Suspect {
                                        subject: pending.target,
                                        subject_incarnation: incarnation,
                                        observation_id,
                                    },
                                },
                            );
                        }
                    }
                }

                TimerKey::SuspicionDeadline(peer) => {
                    let suspicion = match state.suspicions.get(&peer) {
                        Some(s) if s.deadline == timer_id => s.clone(),
                        _ => return out,
                    };
                    let _ = suspicion;
                    if let Some(session_id) = current_session_for_peer(state, peer) {
                        if let Some(session) = state.sessions.get_mut(&session_id) {
                            session.health = PeerHealth::Unreachable;
                        }
                    }
                    push_effect(
                        state,
                        &mut out,
                        CoreEffectKind::EmitPeerEvent {
                            event: PeerEvent::PeerUnreachable(peer),
                        },
                    );
                }

                TimerKey::Maintenance | TimerKey::Exploration => {}
            }
        }

        CoreEventKind::ShutdownRequested => {
            state.lifecycle = LifecycleState::ShuttingDown;
            let sessions: Vec<SessionId> = state.sessions.keys().copied().collect();
            for session_id in sessions {
                push_effect(
                    state,
                    &mut out,
                    CoreEffectKind::CloseSession {
                        session_id,
                        reason: CloseReason::LocalShutdown,
                    },
                );
            }
        }
    }

    if out.effects.len() > cfg.max_effects_per_step as usize {
        out.effects.truncate(cfg.max_effects_per_step as usize);
        state.lifecycle = LifecycleState::RecoveryRequired;
    }

    out
}
