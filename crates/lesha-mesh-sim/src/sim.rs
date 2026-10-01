use std::collections::BTreeMap;

use lesha_peer_core::{
    CloseReason, ControlViewM0, CoreConfig, CoreEffect, CoreEffectKind, CoreEvent, CoreEventKind,
    DurablePeerStateV0, EventSource, LifecycleState, PeerManagerStateM0, PersistenceError,
    SessionDirection,
};
use lesha_types::{
    EndpointSequence, MonoDuration, MonotonicTime, NodeId, NodeRef, PresenceIncarnation, SessionId,
};

use crate::{
    EventQueue, EventTrace, FaultPlan, PresencePersistFault, ScheduledEvent, SimDurableStore,
    SimNode, TraceRecord, VirtualClock,
};

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum SimError {
    UnknownNode(NodeId),
    DuplicateNode(NodeId),
    MissingDurablePresence(NodeId),
    MissingSessionLink { node: NodeId, session_id: SessionId },
    Queue(&'static str),
    StepLimitExceeded(usize),
}

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
struct SessionEndpoint {
    peer_node: NodeId,
    peer_session: SessionId,
}

#[derive(Debug, Default)]
pub struct Simulation {
    pub clock: VirtualClock,
    pub durable: SimDurableStore,
    pub faults: FaultPlan,
    pub trace: EventTrace,
    nodes: BTreeMap<NodeId, SimNode>,
    queue: EventQueue,
    links: BTreeMap<(NodeId, SessionId), SessionEndpoint>,
    next_queue_sequence: u64,
}

impl Simulation {
    pub fn add_node(&mut self, self_ref: NodeRef, config: CoreConfig) -> Result<(), SimError> {
        if self.nodes.contains_key(&self_ref.node_id) {
            return Err(SimError::DuplicateNode(self_ref.node_id));
        }
        self.nodes.insert(
            self_ref.node_id,
            SimNode {
                state: PeerManagerStateM0::new(self_ref),
                config,
                trace_seq: 0,
            },
        );
        Ok(())
    }

    pub fn node(&self, node_id: NodeId) -> Result<&SimNode, SimError> {
        self.nodes
            .get(&node_id)
            .ok_or(SimError::UnknownNode(node_id))
    }

    pub fn node_mut(&mut self, node_id: NodeId) -> Result<&mut SimNode, SimError> {
        self.nodes
            .get_mut(&node_id)
            .ok_or(SimError::UnknownNode(node_id))
    }

    pub fn start_node(&mut self, node_id: NodeId, seed: [u8; 32]) -> Result<(), SimError> {
        self.enqueue_kind(
            node_id,
            self.clock.now(),
            5,
            EventSource::Operator,
            CoreEventKind::StartRequested {
                selection_seed: seed,
            },
        )
    }

    pub fn replace_control(
        &mut self,
        node_id: NodeId,
        view: ControlViewM0,
    ) -> Result<(), SimError> {
        self.enqueue_kind(
            node_id,
            self.clock.now(),
            5,
            EventSource::Control,
            CoreEventKind::ControlViewReplaced { view },
        )
    }

    pub fn connect_authenticated(
        &mut self,
        left: NodeId,
        left_session: SessionId,
        right: NodeId,
        right_session: SessionId,
    ) -> Result<(), SimError> {
        let left_peer_ref = self.node(right)?.state.self_ref;
        let right_peer_ref = self.node(left)?.state.self_ref;
        let left_peer_incarnation = self
            .node(right)?
            .state
            .current_presence()
            .ok_or(SimError::MissingDurablePresence(right))?;
        let right_peer_incarnation = self
            .node(left)?
            .state
            .current_presence()
            .ok_or(SimError::MissingDurablePresence(left))?;

        self.links.insert(
            (left, left_session),
            SessionEndpoint {
                peer_node: right,
                peer_session: right_session,
            },
        );
        self.links.insert(
            (right, right_session),
            SessionEndpoint {
                peer_node: left,
                peer_session: left_session,
            },
        );

        self.enqueue_kind(
            left,
            self.clock.now(),
            5,
            EventSource::Transport,
            CoreEventKind::AuthenticatedSessionEstablished {
                session_id: left_session,
                peer: left_peer_ref,
                direction: SessionDirection::Outbound,
                peer_incarnation: left_peer_incarnation,
            },
        )?;

        self.enqueue_kind(
            right,
            self.clock.now(),
            5,
            EventSource::Transport,
            CoreEventKind::AuthenticatedSessionEstablished {
                session_id: right_session,
                peer: right_peer_ref,
                direction: SessionDirection::Inbound,
                peer_incarnation: right_peer_incarnation,
            },
        )
    }

    pub fn run_next(&mut self) -> Result<bool, SimError> {
        let Some(scheduled) = self.queue.pop_next() else {
            return Ok(false);
        };
        self.clock.advance_to(scheduled.at);

        let target = scheduled.target;
        let event = scheduled.event;
        let output = {
            let node = self.node_mut(target)?;
            node.apply(event.clone())
        };

        let event_index = self.trace.records.len() as u64;
        self.trace.records.push(TraceRecord {
            event_index,
            sim_time: self.clock.now(),
            target,
            event,
            effects: output.effects.clone(),
        });

        for effect in output.effects {
            self.execute_effect(target, effect)?;
        }

        Ok(true)
    }

    pub fn run_steps(&mut self, steps: usize) -> Result<usize, SimError> {
        let mut ran = 0;
        while ran < steps && self.run_next()? {
            ran += 1;
        }
        Ok(ran)
    }

    pub fn run_until_idle(&mut self, max_steps: usize) -> Result<usize, SimError> {
        let mut ran = 0;
        while !self.queue.is_empty() {
            if ran >= max_steps {
                return Err(SimError::StepLimitExceeded(max_steps));
            }
            self.run_next()?;
            ran += 1;
        }
        Ok(ran)
    }

    pub fn run_until<F>(&mut self, max_steps: usize, predicate: F) -> Result<usize, SimError>
    where
        F: Fn(&Self) -> bool,
    {
        if predicate(self) {
            return Ok(0);
        }

        for ran in 1..=max_steps {
            if !self.run_next()? {
                return Ok(ran - 1);
            }
            if predicate(self) {
                return Ok(ran);
            }
        }

        Err(SimError::StepLimitExceeded(max_steps))
    }

    fn enqueue_kind(
        &mut self,
        target: NodeId,
        at: MonotonicTime,
        priority: u16,
        source: EventSource,
        kind: CoreEventKind,
    ) -> Result<(), SimError> {
        if !self.nodes.contains_key(&target) {
            return Err(SimError::UnknownNode(target));
        }

        let sequence = self.next_queue_sequence;
        self.next_queue_sequence = self.next_queue_sequence.saturating_add(1);
        let stable_source = u64::from_be_bytes(
            target.0[..8]
                .try_into()
                .expect("NodeId always has at least eight bytes"),
        );

        self.queue
            .push(ScheduledEvent {
                at,
                priority,
                stable_source,
                source_sequence: sequence,
                target,
                event: CoreEvent {
                    observed_at: at,
                    source,
                    kind,
                },
            })
            .map_err(SimError::Queue)
    }

    fn execute_effect(&mut self, target: NodeId, effect: CoreEffect) -> Result<(), SimError> {
        match effect.kind {
            CoreEffectKind::LoadDurablePeerState => {
                let state = self.durable.load(target);
                self.enqueue_kind(
                    target,
                    self.clock.now(),
                    0,
                    EventSource::Persistence,
                    CoreEventKind::DurableStateLoaded {
                        effect_id: effect.effect_id,
                        state,
                    },
                )?;
            }

            CoreEffectKind::PersistPresence {
                expected_previous,
                next,
            } => {
                if let Some(fault) = self.faults.take_persist_fault(target) {
                    match fault {
                        PresencePersistFault::FailBeforeCommit => {
                            self.enqueue_kind(
                                target,
                                self.clock.now(),
                                0,
                                EventSource::Persistence,
                                CoreEventKind::PresencePersistFailed {
                                    effect_id: effect.effect_id,
                                    error: PersistenceError::IoFailure,
                                },
                            )?;
                            return Ok(());
                        }
                        PresencePersistFault::CommitThenCrash => {
                            self.commit_presence(
                                target,
                                expected_previous,
                                next,
                                effect.effect_id,
                            )?;
                            self.crash_and_restart(target)?;
                            return Ok(());
                        }
                    }
                }

                if !self.commit_presence(target, expected_previous, next, effect.effect_id)? {
                    return Ok(());
                }

                self.enqueue_kind(
                    target,
                    self.clock.now(),
                    0,
                    EventSource::Persistence,
                    CoreEventKind::PresencePersisted {
                        effect_id: effect.effect_id,
                        value: next,
                    },
                )?;
            }

            CoreEffectKind::ScheduleTimer { timer_id, deadline } => {
                self.enqueue_kind(
                    target,
                    deadline,
                    20,
                    EventSource::Timer,
                    CoreEventKind::TimerFired { timer_id },
                )?;
            }

            CoreEffectKind::CancelTimer { .. } => {
                // Deliberately leave the scheduled event in the queue. The core's
                // semantic state and timer generation rules must make it harmless.
            }

            CoreEffectKind::SendMeshMessage {
                session_id,
                message,
                ..
            } => {
                if self.faults.should_drop_message(target, &message) {
                    return Ok(());
                }

                let endpoint = self.links.get(&(target, session_id)).copied().ok_or(
                    SimError::MissingSessionLink {
                        node: target,
                        session_id,
                    },
                )?;
                let delivery_at = self
                    .clock
                    .now()
                    .checked_add(MonoDuration(1))
                    .expect("simulated time overflow");
                self.enqueue_kind(
                    endpoint.peer_node,
                    delivery_at,
                    10,
                    EventSource::Transport,
                    CoreEventKind::MeshMessageReceived {
                        session_id: endpoint.peer_session,
                        message,
                    },
                )?;
            }

            CoreEffectKind::CloseSession { session_id, reason } => {
                self.close_link(target, session_id, reason)?;
            }

            CoreEffectKind::EmitPeerEvent { .. } | CoreEffectKind::RecordDiagnostic { .. } => {}
        }

        Ok(())
    }

    fn commit_presence(
        &mut self,
        target: NodeId,
        expected_previous: Option<PresenceIncarnation>,
        next: PresenceIncarnation,
        effect_id: lesha_types::EffectId,
    ) -> Result<bool, SimError> {
        let current = self.durable.load(target);
        let actual_previous = current.as_ref().map(|state| state.committed_presence);
        if actual_previous != expected_previous {
            self.enqueue_kind(
                target,
                self.clock.now(),
                0,
                EventSource::Persistence,
                CoreEventKind::PresencePersistFailed {
                    effect_id,
                    error: PersistenceError::CompareFailed,
                },
            )?;
            return Ok(false);
        }

        let self_ref = self.node(target)?.state.self_ref;
        let endpoint_sequence = current
            .as_ref()
            .map(|state| state.committed_endpoint_sequence)
            .unwrap_or(EndpointSequence(0));

        self.durable.store(DurablePeerStateV0 {
            format_version: 0,
            self_ref,
            committed_presence: next,
            committed_endpoint_sequence: endpoint_sequence,
            integrity_tag: [0; 32],
        });
        Ok(true)
    }

    fn crash_and_restart(&mut self, target: NodeId) -> Result<(), SimError> {
        let (self_ref, config, seed) = {
            let node = self.node(target)?;
            (
                node.state.self_ref,
                node.config.clone(),
                node.state.selection.seed,
            )
        };
        self.nodes.insert(
            target,
            SimNode {
                state: PeerManagerStateM0::new(self_ref),
                config,
                trace_seq: 0,
            },
        );

        let restart_at = self
            .clock
            .now()
            .checked_add(MonoDuration(1))
            .expect("simulated time overflow");
        self.enqueue_kind(
            target,
            restart_at,
            5,
            EventSource::Operator,
            CoreEventKind::StartRequested {
                selection_seed: seed,
            },
        )
    }

    fn close_link(
        &mut self,
        target: NodeId,
        session_id: SessionId,
        reason: CloseReason,
    ) -> Result<(), SimError> {
        let endpoint = self.links.remove(&(target, session_id));
        self.enqueue_kind(
            target,
            self.clock.now(),
            5,
            EventSource::Transport,
            CoreEventKind::SessionClosed { session_id, reason },
        )?;

        if let Some(endpoint) = endpoint {
            self.links
                .remove(&(endpoint.peer_node, endpoint.peer_session));
            self.enqueue_kind(
                endpoint.peer_node,
                self.clock.now(),
                5,
                EventSource::Transport,
                CoreEventKind::SessionClosed {
                    session_id: endpoint.peer_session,
                    reason,
                },
            )?;
        }
        Ok(())
    }

    pub fn all_network_active(&self) -> bool {
        self.nodes
            .values()
            .all(|node| node.state.lifecycle == LifecycleState::NetworkActive)
    }
}
