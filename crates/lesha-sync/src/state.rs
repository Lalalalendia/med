use lesha_types::{CheckpointId, NamespaceId, ProducerSequence};

use crate::{
    plan_sync, CheckpointRef, NamespaceSummary, ReceiverPosition, SyncPlan, SyncPlanError,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncState {
    Disconnected,
    Negotiating,
    InitialCheckpoint {
        checkpoint: CheckpointRef,
        tail_from_inclusive: Option<ProducerSequence>,
        target: Option<ProducerSequence>,
    },
    IncrementalFollowing {
        next: ProducerSequence,
        target: ProducerSequence,
    },
    Verifying {
        target: Option<ProducerSequence>,
    },
    CaughtUp {
        at: Option<ProducerSequence>,
    },
    NeedsCheckpoint {
        sender_head: Option<ProducerSequence>,
    },
    Quarantined {
        reason: SyncQuarantineReason,
    },
    Error {
        reason: SyncFatalError,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncQuarantineReason {
    ControlForkAtSameEpoch,
    ReceiverAhead {
        receiver: ProducerSequence,
        sender: Option<ProducerSequence>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncFatalError {
    NamespaceMismatch,
    InvalidSenderSummary,
    SequenceOverflow,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncTransitionError {
    InvalidTransition,
    UnexpectedSequence {
        expected: ProducerSequence,
        received: ProducerSequence,
    },
    CheckpointMismatch {
        expected: CheckpointId,
        received: CheckpointId,
    },
    SequenceOverflow,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SyncSession {
    namespace_id: NamespaceId,
    state: SyncState,
}

impl SyncSession {
    pub fn new(namespace_id: NamespaceId) -> Self {
        Self {
            namespace_id,
            state: SyncState::Disconnected,
        }
    }

    pub fn namespace_id(&self) -> NamespaceId {
        self.namespace_id
    }

    pub fn state(&self) -> SyncState {
        self.state
    }

    pub fn authenticated(&mut self) -> Result<(), SyncTransitionError> {
        if self.state != SyncState::Disconnected {
            return Err(SyncTransitionError::InvalidTransition);
        }
        self.state = SyncState::Negotiating;
        Ok(())
    }

    pub fn negotiate(
        &mut self,
        sender: &NamespaceSummary,
        receiver: &ReceiverPosition,
    ) -> Result<(), SyncTransitionError> {
        if self.state != SyncState::Negotiating {
            return Err(SyncTransitionError::InvalidTransition);
        }

        if sender.namespace_id != self.namespace_id || receiver.namespace_id != self.namespace_id {
            self.state = SyncState::Error {
                reason: SyncFatalError::NamespaceMismatch,
            };
            return Ok(());
        }

        match plan_sync(sender, receiver) {
            Ok(plan) => self.apply_plan(plan),
            Err(error) => {
                self.state = state_for_plan_error(error);
            }
        }
        Ok(())
    }

    pub fn checkpoint_applied(
        &mut self,
        checkpoint_id: CheckpointId,
    ) -> Result<(), SyncTransitionError> {
        let SyncState::InitialCheckpoint {
            checkpoint,
            tail_from_inclusive,
            target,
        } = self.state
        else {
            return Err(SyncTransitionError::InvalidTransition);
        };

        if checkpoint.checkpoint_id != checkpoint_id {
            return Err(SyncTransitionError::CheckpointMismatch {
                expected: checkpoint.checkpoint_id,
                received: checkpoint_id,
            });
        }

        self.state = match (tail_from_inclusive, target) {
            (Some(next), Some(target)) => SyncState::IncrementalFollowing { next, target },
            (None, target) => SyncState::Verifying { target },
            (Some(_), None) => SyncState::Error {
                reason: SyncFatalError::InvalidSenderSummary,
            },
        };
        Ok(())
    }

    pub fn delta_applied(
        &mut self,
        sequence: ProducerSequence,
    ) -> Result<(), SyncTransitionError> {
        let SyncState::IncrementalFollowing { next, target } = self.state else {
            return Err(SyncTransitionError::InvalidTransition);
        };

        if sequence != next {
            return Err(SyncTransitionError::UnexpectedSequence {
                expected: next,
                received: sequence,
            });
        }

        if sequence == target {
            self.state = SyncState::Verifying {
                target: Some(target),
            };
            return Ok(());
        }

        self.state = SyncState::IncrementalFollowing {
            next: ProducerSequence(
                next.0
                    .checked_add(1)
                    .ok_or(SyncTransitionError::SequenceOverflow)?,
            ),
            target,
        };
        Ok(())
    }

    pub fn verification_complete(&mut self) -> Result<(), SyncTransitionError> {
        let SyncState::Verifying { target } = self.state else {
            return Err(SyncTransitionError::InvalidTransition);
        };
        self.state = SyncState::CaughtUp { at: target };
        Ok(())
    }

    pub fn disconnect(&mut self) {
        self.state = SyncState::Disconnected;
    }

    fn apply_plan(&mut self, plan: SyncPlan) {
        self.state = match plan {
            SyncPlan::CaughtUp { at } => SyncState::CaughtUp { at },
            SyncPlan::Incremental {
                from_inclusive,
                to_inclusive,
            } => SyncState::IncrementalFollowing {
                next: from_inclusive,
                target: to_inclusive,
            },
            SyncPlan::Checkpoint {
                checkpoint,
                tail_from_inclusive,
                to_inclusive,
            } => SyncState::InitialCheckpoint {
                checkpoint,
                tail_from_inclusive,
                target: to_inclusive,
            },
            SyncPlan::NeedsCheckpoint { sender_head } => {
                SyncState::NeedsCheckpoint { sender_head }
            }
        };
    }
}

fn state_for_plan_error(error: SyncPlanError) -> SyncState {
    match error {
        SyncPlanError::ControlForkAtSameEpoch => SyncState::Quarantined {
            reason: SyncQuarantineReason::ControlForkAtSameEpoch,
        },
        SyncPlanError::ReceiverAhead { receiver, sender } => SyncState::Quarantined {
            reason: SyncQuarantineReason::ReceiverAhead { receiver, sender },
        },
        SyncPlanError::NamespaceMismatch => SyncState::Error {
            reason: SyncFatalError::NamespaceMismatch,
        },
        SyncPlanError::InvalidSenderSummary => SyncState::Error {
            reason: SyncFatalError::InvalidSenderSummary,
        },
        SyncPlanError::SequenceOverflow => SyncState::Error {
            reason: SyncFatalError::SequenceOverflow,
        },
    }
}

#[cfg(test)]
mod tests {
    use lesha_types::{ControlFrontierHash, DeltaHash};

    use super::*;
    use crate::{ControlContext, NamespaceSummary};

    fn ns(byte: u8) -> NamespaceId {
        NamespaceId([byte; 16])
    }

    fn control(epoch: u64, byte: u8) -> ControlContext {
        ControlContext {
            epoch,
            frontier_hash: ControlFrontierHash([byte; 32]),
        }
    }

    fn checkpoint(sequence: u64) -> CheckpointRef {
        CheckpointRef {
            checkpoint_id: CheckpointId([9; 32]),
            producer_sequence_head: ProducerSequence(sequence),
            producer_delta_hash: if sequence == 0 {
                None
            } else {
                Some(DeltaHash([sequence as u8; 32]))
            },
        }
    }

    fn summary() -> NamespaceSummary {
        NamespaceSummary {
            namespace_id: ns(1),
            checkpoint: Some(checkpoint(5)),
            delta_floor: Some(ProducerSequence(6)),
            delta_head: Some(ProducerSequence(10)),
            bucket_root_set_hash: [7; 32],
            control: control(4, 8),
        }
    }

    fn receiver(last: Option<u64>) -> ReceiverPosition {
        ReceiverPosition {
            namespace_id: ns(1),
            last_applied: last.map(ProducerSequence),
            control: control(4, 8),
        }
    }

    #[test]
    fn incremental_path_requires_verification_before_caught_up() {
        let mut session = SyncSession::new(ns(1));
        session.authenticated().unwrap();
        session
            .negotiate(&summary(), &receiver(Some(7)))
            .unwrap();
        assert_eq!(
            session.state(),
            SyncState::IncrementalFollowing {
                next: ProducerSequence(8),
                target: ProducerSequence(10),
            }
        );

        for seq in 8..=10 {
            session.delta_applied(ProducerSequence(seq)).unwrap();
        }
        assert_eq!(
            session.state(),
            SyncState::Verifying {
                target: Some(ProducerSequence(10))
            }
        );

        session.verification_complete().unwrap();
        assert_eq!(
            session.state(),
            SyncState::CaughtUp {
                at: Some(ProducerSequence(10))
            }
        );
    }

    #[test]
    fn checkpoint_path_transitions_to_tail_then_verification() {
        let mut session = SyncSession::new(ns(1));
        session.authenticated().unwrap();
        session
            .negotiate(&summary(), &receiver(Some(2)))
            .unwrap();

        assert!(matches!(
            session.state(),
            SyncState::InitialCheckpoint { .. }
        ));
        session.checkpoint_applied(CheckpointId([9; 32])).unwrap();
        assert_eq!(
            session.state(),
            SyncState::IncrementalFollowing {
                next: ProducerSequence(6),
                target: ProducerSequence(10),
            }
        );

        for seq in 6..=10 {
            session.delta_applied(ProducerSequence(seq)).unwrap();
        }
        session.verification_complete().unwrap();
        assert_eq!(
            session.state(),
            SyncState::CaughtUp {
                at: Some(ProducerSequence(10))
            }
        );
    }

    #[test]
    fn no_checkpoint_for_stale_peer_is_explicit() {
        let mut sender = summary();
        sender.checkpoint = None;

        let mut session = SyncSession::new(ns(1));
        session.authenticated().unwrap();
        session.negotiate(&sender, &receiver(Some(2))).unwrap();

        assert_eq!(
            session.state(),
            SyncState::NeedsCheckpoint {
                sender_head: Some(ProducerSequence(10))
            }
        );
    }

    #[test]
    fn same_epoch_control_fork_quarantines_session() {
        let sender = summary();
        let mut position = receiver(Some(7));
        position.control.frontier_hash = ControlFrontierHash([99; 32]);

        let mut session = SyncSession::new(ns(1));
        session.authenticated().unwrap();
        session.negotiate(&sender, &position).unwrap();

        assert_eq!(
            session.state(),
            SyncState::Quarantined {
                reason: SyncQuarantineReason::ControlForkAtSameEpoch
            }
        );
    }

    #[test]
    fn unexpected_delta_or_checkpoint_does_not_advance() {
        let mut incremental = SyncSession::new(ns(1));
        incremental.authenticated().unwrap();
        incremental
            .negotiate(&summary(), &receiver(Some(7)))
            .unwrap();
        let before = incremental.state();
        assert_eq!(
            incremental.delta_applied(ProducerSequence(9)),
            Err(SyncTransitionError::UnexpectedSequence {
                expected: ProducerSequence(8),
                received: ProducerSequence(9),
            })
        );
        assert_eq!(incremental.state(), before);

        let mut checkpoint_session = SyncSession::new(ns(1));
        checkpoint_session.authenticated().unwrap();
        checkpoint_session
            .negotiate(&summary(), &receiver(Some(2)))
            .unwrap();
        let before = checkpoint_session.state();
        assert_eq!(
            checkpoint_session.checkpoint_applied(CheckpointId([77; 32])),
            Err(SyncTransitionError::CheckpointMismatch {
                expected: CheckpointId([9; 32]),
                received: CheckpointId([77; 32]),
            })
        );
        assert_eq!(checkpoint_session.state(), before);
    }
}
