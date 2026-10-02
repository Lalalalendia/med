#![forbid(unsafe_code)]

use std::collections::BTreeMap;

use lesha_types::{
    CheckpointId, ControlFrontierHash, DeltaHash, NamespaceId, ProducerSequence,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ControlContext {
    pub epoch: u64,
    pub frontier_hash: ControlFrontierHash,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CheckpointRef {
    pub checkpoint_id: CheckpointId,
    pub producer_sequence_head: ProducerSequence,
    pub producer_delta_hash: Option<DeltaHash>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NamespaceSummary {
    pub namespace_id: NamespaceId,
    pub checkpoint: Option<CheckpointRef>,
    pub delta_floor: Option<ProducerSequence>,
    pub delta_head: Option<ProducerSequence>,
    pub bucket_root_set_hash: [u8; 32],
    pub control: ControlContext,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReceiverPosition {
    pub namespace_id: NamespaceId,
    pub last_applied: Option<ProducerSequence>,
    pub control: ControlContext,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncPlan {
    CaughtUp {
        at: Option<ProducerSequence>,
    },
    Incremental {
        from_inclusive: ProducerSequence,
        to_inclusive: ProducerSequence,
    },
    Checkpoint {
        checkpoint: CheckpointRef,
        tail_from_inclusive: Option<ProducerSequence>,
        to_inclusive: Option<ProducerSequence>,
    },
    NeedsCheckpoint {
        sender_head: Option<ProducerSequence>,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SyncPlanError {
    NamespaceMismatch,
    InvalidSenderSummary,
    ControlForkAtSameEpoch,
    ReceiverAhead {
        receiver: ProducerSequence,
        sender: Option<ProducerSequence>,
    },
    SequenceOverflow,
}

pub fn plan_sync(
    sender: &NamespaceSummary,
    receiver: &ReceiverPosition,
) -> Result<SyncPlan, SyncPlanError> {
    if sender.namespace_id != receiver.namespace_id {
        return Err(SyncPlanError::NamespaceMismatch);
    }
    validate_sender_summary(sender)?;

    if sender.control.epoch == receiver.control.epoch
        && sender.control.frontier_hash != receiver.control.frontier_hash
    {
        return Err(SyncPlanError::ControlForkAtSameEpoch);
    }

    let Some(receiver_head) = receiver.last_applied else {
        return checkpoint_or_need(sender);
    };

    let Some(sender_head) = sender.delta_head else {
        return Err(SyncPlanError::ReceiverAhead {
            receiver: receiver_head,
            sender: None,
        });
    };

    if receiver_head == sender_head {
        return Ok(SyncPlan::CaughtUp {
            at: Some(sender_head),
        });
    }
    if receiver_head > sender_head {
        return Err(SyncPlanError::ReceiverAhead {
            receiver: receiver_head,
            sender: Some(sender_head),
        });
    }

    let next = ProducerSequence(
        receiver_head
            .0
            .checked_add(1)
            .ok_or(SyncPlanError::SequenceOverflow)?,
    );
    let floor = sender
        .delta_floor
        .ok_or(SyncPlanError::InvalidSenderSummary)?;

    if next >= floor {
        Ok(SyncPlan::Incremental {
            from_inclusive: next,
            to_inclusive: sender_head,
        })
    } else {
        checkpoint_or_need(sender)
    }
}

fn validate_sender_summary(sender: &NamespaceSummary) -> Result<(), SyncPlanError> {
    match (sender.delta_floor, sender.delta_head) {
        (None, None) => {}
        (Some(floor), Some(head)) if floor <= head => {}
        _ => return Err(SyncPlanError::InvalidSenderSummary),
    }

    if let Some(checkpoint) = sender.checkpoint {
        match sender.delta_head {
            Some(head) if checkpoint.producer_sequence_head <= head => {}
            None if checkpoint.producer_sequence_head == ProducerSequence(0) => {}
            _ => return Err(SyncPlanError::InvalidSenderSummary),
        }

        if checkpoint.producer_sequence_head == ProducerSequence(0)
            && checkpoint.producer_delta_hash.is_some()
        {
            return Err(SyncPlanError::InvalidSenderSummary);
        }
        if checkpoint.producer_sequence_head != ProducerSequence(0)
            && checkpoint.producer_delta_hash.is_none()
        {
            return Err(SyncPlanError::InvalidSenderSummary);
        }
    }

    Ok(())
}

fn checkpoint_or_need(sender: &NamespaceSummary) -> Result<SyncPlan, SyncPlanError> {
    let Some(checkpoint) = sender.checkpoint else {
        if sender.delta_head.is_none() {
            return Ok(SyncPlan::CaughtUp { at: None });
        }
        return Ok(SyncPlan::NeedsCheckpoint {
            sender_head: sender.delta_head,
        });
    };

    let tail_from_inclusive = match sender.delta_head {
        Some(head) if checkpoint.producer_sequence_head < head => Some(ProducerSequence(
            checkpoint
                .producer_sequence_head
                .0
                .checked_add(1)
                .ok_or(SyncPlanError::SequenceOverflow)?,
        )),
        _ => None,
    };

    Ok(SyncPlan::Checkpoint {
        checkpoint,
        tail_from_inclusive,
        to_inclusive: sender.delta_head,
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeltaEnvelopeHeader {
    pub sequence: ProducerSequence,
    pub previous_delta_hash: Option<DeltaHash>,
    pub envelope_hash: DeltaHash,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeltaAccept {
    Applied {
        new_head: ProducerSequence,
    },
    Duplicate {
        sequence: ProducerSequence,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeltaValidationError {
    InvalidBaseline,
    InvalidReplayWindow,
    SequenceOverflow,
    GapDetected {
        expected: ProducerSequence,
        received: ProducerSequence,
    },
    PreviousHashMismatch,
    SequenceEquivocation {
        sequence: ProducerSequence,
    },
    ReplayOutsideWindow {
        sequence: ProducerSequence,
    },
}

#[derive(Clone, Debug)]
pub struct DeltaChainValidator {
    last_sequence: Option<ProducerSequence>,
    last_hash: Option<DeltaHash>,
    accepted: BTreeMap<ProducerSequence, DeltaHash>,
    replay_window: usize,
}

impl DeltaChainValidator {
    pub fn new(
        last_sequence: Option<ProducerSequence>,
        last_hash: Option<DeltaHash>,
        replay_window: usize,
    ) -> Result<Self, DeltaValidationError> {
        if last_sequence.is_some() != last_hash.is_some() {
            return Err(DeltaValidationError::InvalidBaseline);
        }
        if replay_window == 0 {
            return Err(DeltaValidationError::InvalidReplayWindow);
        }

        Ok(Self {
            last_sequence,
            last_hash,
            accepted: BTreeMap::new(),
            replay_window,
        })
    }

    pub fn last_sequence(&self) -> Option<ProducerSequence> {
        self.last_sequence
    }

    pub fn last_hash(&self) -> Option<DeltaHash> {
        self.last_hash
    }

    pub fn accept(
        &mut self,
        header: DeltaEnvelopeHeader,
    ) -> Result<DeltaAccept, DeltaValidationError> {
        if let Some(known_hash) = self.accepted.get(&header.sequence) {
            return if *known_hash == header.envelope_hash {
                Ok(DeltaAccept::Duplicate {
                    sequence: header.sequence,
                })
            } else {
                Err(DeltaValidationError::SequenceEquivocation {
                    sequence: header.sequence,
                })
            };
        }

        if self.last_sequence == Some(header.sequence) {
            return if self.last_hash == Some(header.envelope_hash) {
                Ok(DeltaAccept::Duplicate {
                    sequence: header.sequence,
                })
            } else {
                Err(DeltaValidationError::SequenceEquivocation {
                    sequence: header.sequence,
                })
            };
        }

        let expected = match self.last_sequence {
            Some(last) => ProducerSequence(
                last.0
                    .checked_add(1)
                    .ok_or(DeltaValidationError::SequenceOverflow)?,
            ),
            None => ProducerSequence(1),
        };

        if header.sequence < expected {
            return Err(DeltaValidationError::ReplayOutsideWindow {
                sequence: header.sequence,
            });
        }
        if header.sequence > expected {
            return Err(DeltaValidationError::GapDetected {
                expected,
                received: header.sequence,
            });
        }

        match (self.last_hash, header.previous_delta_hash) {
            (None, None) => {}
            (Some(expected_hash), Some(received_hash)) if expected_hash == received_hash => {}
            _ => return Err(DeltaValidationError::PreviousHashMismatch),
        }

        self.last_sequence = Some(header.sequence);
        self.last_hash = Some(header.envelope_hash);
        self.accepted.insert(header.sequence, header.envelope_hash);

        while self.accepted.len() > self.replay_window {
            let Some(oldest) = self.accepted.keys().next().copied() else {
                break;
            };
            self.accepted.remove(&oldest);
        }

        Ok(DeltaAccept::Applied {
            new_head: header.sequence,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ns(byte: u8) -> NamespaceId {
        NamespaceId([byte; 16])
    }

    fn hash(byte: u8) -> DeltaHash {
        DeltaHash([byte; 32])
    }

    fn control(epoch: u64, byte: u8) -> ControlContext {
        ControlContext {
            epoch,
            frontier_hash: ControlFrontierHash([byte; 32]),
        }
    }

    fn checkpoint(sequence: u64, byte: u8) -> CheckpointRef {
        CheckpointRef {
            checkpoint_id: CheckpointId([byte; 32]),
            producer_sequence_head: ProducerSequence(sequence),
            producer_delta_hash: if sequence == 0 {
                None
            } else {
                Some(hash(byte))
            },
        }
    }

    fn summary(floor: u64, head: u64) -> NamespaceSummary {
        NamespaceSummary {
            namespace_id: ns(1),
            checkpoint: Some(checkpoint(floor.saturating_sub(1), 9)),
            delta_floor: Some(ProducerSequence(floor)),
            delta_head: Some(ProducerSequence(head)),
            bucket_root_set_hash: [7; 32],
            control: control(5, 8),
        }
    }

    fn receiver(last: Option<u64>) -> ReceiverPosition {
        ReceiverPosition {
            namespace_id: ns(1),
            last_applied: last.map(ProducerSequence),
            control: control(5, 8),
        }
    }

    #[test]
    fn planner_returns_caught_up_at_exact_head() {
        assert_eq!(
            plan_sync(&summary(6, 10), &receiver(Some(10))),
            Ok(SyncPlan::CaughtUp {
                at: Some(ProducerSequence(10))
            })
        );
    }

    #[test]
    fn planner_uses_incremental_inside_retention_window() {
        assert_eq!(
            plan_sync(&summary(6, 10), &receiver(Some(7))),
            Ok(SyncPlan::Incremental {
                from_inclusive: ProducerSequence(8),
                to_inclusive: ProducerSequence(10),
            })
        );
    }

    #[test]
    fn planner_switches_stale_or_new_peer_to_checkpoint() {
        let sender = summary(6, 10);
        assert!(matches!(
            plan_sync(&sender, &receiver(Some(3))),
            Ok(SyncPlan::Checkpoint { .. })
        ));
        assert!(matches!(
            plan_sync(&sender, &receiver(None)),
            Ok(SyncPlan::Checkpoint { .. })
        ));
    }

    #[test]
    fn planner_needs_checkpoint_when_history_is_too_old_and_none_exists() {
        let mut sender = summary(6, 10);
        sender.checkpoint = None;
        assert_eq!(
            plan_sync(&sender, &receiver(Some(3))),
            Ok(SyncPlan::NeedsCheckpoint {
                sender_head: Some(ProducerSequence(10))
            })
        );
    }

    #[test]
    fn planner_rejects_receiver_ahead_and_same_epoch_control_fork() {
        assert_eq!(
            plan_sync(&summary(6, 10), &receiver(Some(11))),
            Err(SyncPlanError::ReceiverAhead {
                receiver: ProducerSequence(11),
                sender: Some(ProducerSequence(10)),
            })
        );

        let sender = summary(6, 10);
        let mut forked = receiver(Some(8));
        forked.control.frontier_hash = ControlFrontierHash([99; 32]);
        assert_eq!(
            plan_sync(&sender, &forked),
            Err(SyncPlanError::ControlForkAtSameEpoch)
        );
    }

    #[test]
    fn planner_rejects_invalid_sender_window() {
        let mut sender = summary(6, 10);
        sender.delta_floor = Some(ProducerSequence(11));
        assert_eq!(
            plan_sync(&sender, &receiver(Some(8))),
            Err(SyncPlanError::InvalidSenderSummary)
        );
    }

    #[test]
    fn delta_chain_accepts_linear_sequence_and_duplicate() {
        let mut validator = DeltaChainValidator::new(None, None, 8).unwrap();

        let first = DeltaEnvelopeHeader {
            sequence: ProducerSequence(1),
            previous_delta_hash: None,
            envelope_hash: hash(1),
        };
        assert_eq!(
            validator.accept(first),
            Ok(DeltaAccept::Applied {
                new_head: ProducerSequence(1)
            })
        );
        assert_eq!(
            validator.accept(first),
            Ok(DeltaAccept::Duplicate {
                sequence: ProducerSequence(1)
            })
        );

        let second = DeltaEnvelopeHeader {
            sequence: ProducerSequence(2),
            previous_delta_hash: Some(hash(1)),
            envelope_hash: hash(2),
        };
        assert_eq!(
            validator.accept(second),
            Ok(DeltaAccept::Applied {
                new_head: ProducerSequence(2)
            })
        );
    }

    #[test]
    fn delta_chain_rejects_equivocation_without_advancing() {
        let mut validator = DeltaChainValidator::new(None, None, 8).unwrap();
        validator
            .accept(DeltaEnvelopeHeader {
                sequence: ProducerSequence(1),
                previous_delta_hash: None,
                envelope_hash: hash(1),
            })
            .unwrap();

        assert_eq!(
            validator.accept(DeltaEnvelopeHeader {
                sequence: ProducerSequence(1),
                previous_delta_hash: None,
                envelope_hash: hash(9),
            }),
            Err(DeltaValidationError::SequenceEquivocation {
                sequence: ProducerSequence(1)
            })
        );
        assert_eq!(validator.last_sequence(), Some(ProducerSequence(1)));
        assert_eq!(validator.last_hash(), Some(hash(1)));
    }

    #[test]
    fn delta_chain_rejects_gap_and_bad_previous_hash_without_advancing() {
        let mut validator =
            DeltaChainValidator::new(Some(ProducerSequence(5)), Some(hash(5)), 8).unwrap();

        assert_eq!(
            validator.accept(DeltaEnvelopeHeader {
                sequence: ProducerSequence(7),
                previous_delta_hash: Some(hash(5)),
                envelope_hash: hash(7),
            }),
            Err(DeltaValidationError::GapDetected {
                expected: ProducerSequence(6),
                received: ProducerSequence(7),
            })
        );
        assert_eq!(validator.last_sequence(), Some(ProducerSequence(5)));

        assert_eq!(
            validator.accept(DeltaEnvelopeHeader {
                sequence: ProducerSequence(6),
                previous_delta_hash: Some(hash(4)),
                envelope_hash: hash(6),
            }),
            Err(DeltaValidationError::PreviousHashMismatch)
        );
        assert_eq!(validator.last_sequence(), Some(ProducerSequence(5)));
    }

    #[test]
    fn delta_chain_forgets_old_replay_beyond_window() {
        let mut validator = DeltaChainValidator::new(None, None, 2).unwrap();
        for seq in 1..=3 {
            validator
                .accept(DeltaEnvelopeHeader {
                    sequence: ProducerSequence(seq),
                    previous_delta_hash: if seq == 1 {
                        None
                    } else {
                        Some(hash((seq - 1) as u8))
                    },
                    envelope_hash: hash(seq as u8),
                })
                .unwrap();
        }

        assert_eq!(
            validator.accept(DeltaEnvelopeHeader {
                sequence: ProducerSequence(1),
                previous_delta_hash: None,
                envelope_hash: hash(1),
            }),
            Err(DeltaValidationError::ReplayOutsideWindow {
                sequence: ProducerSequence(1)
            })
        );
    }
}
