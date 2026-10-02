#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};

use lesha_types::{
    ClusterId, ControlAppliedIndex, ControlCommandId, ControlEpoch, NodeId, RecoveryEpoch,
};
use sha2::{Digest, Sha256};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemberRole {
    Learner,
    Voter,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct MemberRecord {
    pub node_id: NodeId,
    pub role: MemberRole,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlCommandKind {
    AddLearner { node_id: NodeId },
    PromoteVoter { node_id: NodeId },
    RevokeNode { node_id: NodeId },
    SetPolicyHash { policy_hash: [u8; 32] },
    AdvanceRecoveryEpoch { next: RecoveryEpoch },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ValidatedControlCommand {
    pub command_id: ControlCommandId,
    pub cluster_id: ClusterId,
    pub expected_control_epoch: ControlEpoch,
    pub expected_recovery_epoch: RecoveryEpoch,
    pub request_hash: [u8; 32],
    pub kind: ControlCommandKind,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedControlReceipt {
    pub command_id: ControlCommandId,
    pub request_hash: [u8; 32],
    pub control_epoch: ControlEpoch,
    pub recovery_epoch: RecoveryEpoch,
    pub state_root: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlCheckpoint {
    pub cluster_id: ClusterId,
    pub applied_index: ControlAppliedIndex,
    pub control_epoch: ControlEpoch,
    pub recovery_epoch: RecoveryEpoch,
    pub state_root: [u8; 32],
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlSnapshotState {
    pub cluster_id: ClusterId,
    pub control_epoch: ControlEpoch,
    pub recovery_epoch: RecoveryEpoch,
    pub members: BTreeMap<NodeId, MemberRecord>,
    pub revoked_nodes: BTreeSet<NodeId>,
    pub policy_hash: [u8; 32],
    pub committed: BTreeMap<ControlCommandId, CommittedControlReceipt>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlSnapshot {
    pub checkpoint: ControlCheckpoint,
    pub state: ControlSnapshotState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlError {
    ClusterMismatch,
    IdempotencyConflict,
    ControlEpochChanged {
        expected: ControlEpoch,
        actual: ControlEpoch,
    },
    RecoveryEpochChanged {
        expected: RecoveryEpoch,
        actual: RecoveryEpoch,
    },
    MemberAlreadyExists(NodeId),
    MemberMissing(NodeId),
    MemberRevoked(NodeId),
    IllegalPromotion(NodeId),
    RecoveryEpochNotMonotonic,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SnapshotInstallError {
    ClusterMismatch,
    CheckpointControlEpochMismatch,
    CheckpointRecoveryEpochMismatch,
    StateRootMismatch,
    ControlEpochRollback {
        current: ControlEpoch,
        incoming: ControlEpoch,
    },
    RecoveryEpochRollback {
        current: RecoveryEpoch,
        incoming: RecoveryEpoch,
    },
    SameEpochFork,
    RevocationInvariantViolation(NodeId),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ControlState {
    pub cluster_id: ClusterId,
    pub control_epoch: ControlEpoch,
    pub recovery_epoch: RecoveryEpoch,
    pub members: BTreeMap<NodeId, MemberRecord>,
    pub revoked_nodes: BTreeSet<NodeId>,
    pub policy_hash: [u8; 32],
    committed: BTreeMap<ControlCommandId, CommittedControlReceipt>,
}

impl ControlState {
    pub fn new(cluster_id: ClusterId) -> Self {
        Self {
            cluster_id,
            control_epoch: ControlEpoch(0),
            recovery_epoch: RecoveryEpoch(0),
            members: BTreeMap::new(),
            revoked_nodes: BTreeSet::new(),
            policy_hash: [0; 32],
            committed: BTreeMap::new(),
        }
    }

    pub fn apply(
        &mut self,
        cmd: ValidatedControlCommand,
    ) -> Result<CommittedControlReceipt, ControlError> {
        if cmd.cluster_id != self.cluster_id {
            return Err(ControlError::ClusterMismatch);
        }

        if let Some(existing) = self.committed.get(&cmd.command_id) {
            return if existing.request_hash == cmd.request_hash {
                Ok(existing.clone())
            } else {
                Err(ControlError::IdempotencyConflict)
            };
        }

        if cmd.expected_control_epoch != self.control_epoch {
            return Err(ControlError::ControlEpochChanged {
                expected: cmd.expected_control_epoch,
                actual: self.control_epoch,
            });
        }
        if cmd.expected_recovery_epoch != self.recovery_epoch {
            return Err(ControlError::RecoveryEpochChanged {
                expected: cmd.expected_recovery_epoch,
                actual: self.recovery_epoch,
            });
        }

        match cmd.kind {
            ControlCommandKind::AddLearner { node_id } => {
                if self.revoked_nodes.contains(&node_id) {
                    return Err(ControlError::MemberRevoked(node_id));
                }
                if self.members.contains_key(&node_id) {
                    return Err(ControlError::MemberAlreadyExists(node_id));
                }
                self.members.insert(
                    node_id,
                    MemberRecord {
                        node_id,
                        role: MemberRole::Learner,
                        revoked: false,
                    },
                );
            }
            ControlCommandKind::PromoteVoter { node_id } => {
                let member = self
                    .members
                    .get_mut(&node_id)
                    .ok_or(ControlError::MemberMissing(node_id))?;
                if member.revoked || self.revoked_nodes.contains(&node_id) {
                    return Err(ControlError::MemberRevoked(node_id));
                }
                if member.role != MemberRole::Learner {
                    return Err(ControlError::IllegalPromotion(node_id));
                }
                member.role = MemberRole::Voter;
            }
            ControlCommandKind::RevokeNode { node_id } => {
                self.revoked_nodes.insert(node_id);
                if let Some(member) = self.members.get_mut(&node_id) {
                    member.revoked = true;
                }
            }
            ControlCommandKind::SetPolicyHash { policy_hash } => {
                self.policy_hash = policy_hash;
            }
            ControlCommandKind::AdvanceRecoveryEpoch { next } => {
                if next.0 <= self.recovery_epoch.0 {
                    return Err(ControlError::RecoveryEpochNotMonotonic);
                }
                self.recovery_epoch = next;
            }
        }

        self.control_epoch = ControlEpoch(self.control_epoch.0 + 1);

        let mut receipt = CommittedControlReceipt {
            command_id: cmd.command_id,
            request_hash: cmd.request_hash,
            control_epoch: self.control_epoch,
            recovery_epoch: self.recovery_epoch,
            state_root: [0; 32],
        };
        self.committed.insert(cmd.command_id, receipt.clone());
        receipt.state_root = self.state_root();
        self.committed.insert(cmd.command_id, receipt.clone());
        Ok(receipt)
    }

    pub fn checkpoint(&self, applied_index: ControlAppliedIndex) -> ControlSnapshot {
        ControlSnapshot {
            checkpoint: ControlCheckpoint {
                cluster_id: self.cluster_id,
                applied_index,
                control_epoch: self.control_epoch,
                recovery_epoch: self.recovery_epoch,
                state_root: self.state_root(),
            },
            state: ControlSnapshotState {
                cluster_id: self.cluster_id,
                control_epoch: self.control_epoch,
                recovery_epoch: self.recovery_epoch,
                members: self.members.clone(),
                revoked_nodes: self.revoked_nodes.clone(),
                policy_hash: self.policy_hash,
                committed: self.committed.clone(),
            },
        }
    }

    pub fn install_snapshot(
        &mut self,
        snapshot: ControlSnapshot,
    ) -> Result<ControlCheckpoint, SnapshotInstallError> {
        validate_snapshot_invariants(&snapshot)?;

        if snapshot.checkpoint.cluster_id != self.cluster_id {
            return Err(SnapshotInstallError::ClusterMismatch);
        }
        if snapshot.checkpoint.control_epoch.0 < self.control_epoch.0 {
            return Err(SnapshotInstallError::ControlEpochRollback {
                current: self.control_epoch,
                incoming: snapshot.checkpoint.control_epoch,
            });
        }
        if snapshot.checkpoint.recovery_epoch.0 < self.recovery_epoch.0 {
            return Err(SnapshotInstallError::RecoveryEpochRollback {
                current: self.recovery_epoch,
                incoming: snapshot.checkpoint.recovery_epoch,
            });
        }

        if snapshot.checkpoint.control_epoch == self.control_epoch
            && snapshot.checkpoint.recovery_epoch == self.recovery_epoch
            && snapshot.checkpoint.state_root != self.state_root()
        {
            return Err(SnapshotInstallError::SameEpochFork);
        }

        self.cluster_id = snapshot.state.cluster_id;
        self.control_epoch = snapshot.state.control_epoch;
        self.recovery_epoch = snapshot.state.recovery_epoch;
        self.members = snapshot.state.members;
        self.revoked_nodes = snapshot.state.revoked_nodes;
        self.policy_hash = snapshot.state.policy_hash;
        self.committed = snapshot.state.committed;

        Ok(snapshot.checkpoint)
    }

    pub fn state_root(&self) -> [u8; 32] {
        state_root_for_parts(
            self.cluster_id,
            self.control_epoch,
            self.recovery_epoch,
            &self.members,
            &self.revoked_nodes,
            self.policy_hash,
            &self.committed,
        )
    }
}

fn validate_snapshot_invariants(snapshot: &ControlSnapshot) -> Result<(), SnapshotInstallError> {
    if snapshot.checkpoint.cluster_id != snapshot.state.cluster_id {
        return Err(SnapshotInstallError::ClusterMismatch);
    }
    if snapshot.checkpoint.control_epoch != snapshot.state.control_epoch {
        return Err(SnapshotInstallError::CheckpointControlEpochMismatch);
    }
    if snapshot.checkpoint.recovery_epoch != snapshot.state.recovery_epoch {
        return Err(SnapshotInstallError::CheckpointRecoveryEpochMismatch);
    }

    for (node_id, member) in &snapshot.state.members {
        if member.node_id != *node_id {
            return Err(SnapshotInstallError::RevocationInvariantViolation(*node_id));
        }
        if member.revoked != snapshot.state.revoked_nodes.contains(node_id) {
            return Err(SnapshotInstallError::RevocationInvariantViolation(*node_id));
        }
    }

    let root = state_root_for_parts(
        snapshot.state.cluster_id,
        snapshot.state.control_epoch,
        snapshot.state.recovery_epoch,
        &snapshot.state.members,
        &snapshot.state.revoked_nodes,
        snapshot.state.policy_hash,
        &snapshot.state.committed,
    );
    if root != snapshot.checkpoint.state_root {
        return Err(SnapshotInstallError::StateRootMismatch);
    }

    Ok(())
}

fn state_root_for_parts(
    cluster_id: ClusterId,
    control_epoch: ControlEpoch,
    recovery_epoch: RecoveryEpoch,
    members: &BTreeMap<NodeId, MemberRecord>,
    revoked_nodes: &BTreeSet<NodeId>,
    policy_hash: [u8; 32],
    committed: &BTreeMap<ControlCommandId, CommittedControlReceipt>,
) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"LesHa/ControlState/C0\0");
    h.update(cluster_id.0);
    h.update(control_epoch.0.to_be_bytes());
    h.update(recovery_epoch.0.to_be_bytes());
    h.update(policy_hash);

    for (node_id, member) in members {
        h.update(node_id.0);
        h.update([match member.role {
            MemberRole::Learner => 0,
            MemberRole::Voter => 1,
        }]);
        h.update([member.revoked as u8]);
    }
    for node_id in revoked_nodes {
        h.update(node_id.0);
    }
    for (command_id, receipt) in committed {
        h.update(command_id.0);
        h.update(receipt.request_hash);
        h.update(receipt.control_epoch.0.to_be_bytes());
        h.update(receipt.recovery_epoch.0.to_be_bytes());
    }

    let digest = h.finalize();
    let mut out = [0; 32];
    out.copy_from_slice(&digest);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cluster() -> ClusterId {
        ClusterId([1; 16])
    }

    fn other_cluster() -> ClusterId {
        ClusterId([2; 16])
    }

    fn node(tag: u8) -> NodeId {
        NodeId([tag; 32])
    }

    fn command(tag: u8, state: &ControlState, kind: ControlCommandKind) -> ValidatedControlCommand {
        ValidatedControlCommand {
            command_id: ControlCommandId([tag; 16]),
            cluster_id: state.cluster_id,
            expected_control_epoch: state.control_epoch,
            expected_recovery_epoch: state.recovery_epoch,
            request_hash: [tag; 32],
            kind,
        }
    }

    #[test]
    fn learner_must_be_explicitly_promoted() {
        let mut state = ControlState::new(cluster());
        state
            .apply(command(
                1,
                &state,
                ControlCommandKind::AddLearner { node_id: node(7) },
            ))
            .unwrap();
        assert_eq!(state.members[&node(7)].role, MemberRole::Learner);

        state
            .apply(command(
                2,
                &state,
                ControlCommandKind::PromoteVoter { node_id: node(7) },
            ))
            .unwrap();
        assert_eq!(state.members[&node(7)].role, MemberRole::Voter);
    }

    #[test]
    fn revoked_node_cannot_be_readded_or_promoted() {
        let mut state = ControlState::new(cluster());
        state
            .apply(command(
                1,
                &state,
                ControlCommandKind::AddLearner { node_id: node(7) },
            ))
            .unwrap();
        state
            .apply(command(
                2,
                &state,
                ControlCommandKind::RevokeNode { node_id: node(7) },
            ))
            .unwrap();

        assert_eq!(
            state.apply(command(
                3,
                &state,
                ControlCommandKind::PromoteVoter { node_id: node(7) }
            )),
            Err(ControlError::MemberRevoked(node(7)))
        );

        state.members.remove(&node(7));
        assert_eq!(
            state.apply(command(
                4,
                &state,
                ControlCommandKind::AddLearner { node_id: node(7) }
            )),
            Err(ControlError::MemberRevoked(node(7)))
        );
    }

    #[test]
    fn command_id_is_idempotent_but_request_hash_is_bound() {
        let mut state = ControlState::new(cluster());
        let cmd = command(
            1,
            &state,
            ControlCommandKind::SetPolicyHash {
                policy_hash: [9; 32],
            },
        );
        let first = state.apply(cmd.clone()).unwrap();
        let second = state.apply(cmd.clone()).unwrap();
        assert_eq!(first, second);
        assert_eq!(state.control_epoch, ControlEpoch(1));

        let mut conflict = cmd;
        conflict.request_hash = [8; 32];
        assert_eq!(
            state.apply(conflict),
            Err(ControlError::IdempotencyConflict)
        );
    }

    #[test]
    fn stale_epoch_preconditions_fail_closed() {
        let mut state = ControlState::new(cluster());
        let stale = command(
            1,
            &state,
            ControlCommandKind::SetPolicyHash {
                policy_hash: [2; 32],
            },
        );
        state
            .apply(command(
                2,
                &state,
                ControlCommandKind::SetPolicyHash {
                    policy_hash: [3; 32],
                },
            ))
            .unwrap();

        assert_eq!(
            state.apply(stale),
            Err(ControlError::ControlEpochChanged {
                expected: ControlEpoch(0),
                actual: ControlEpoch(1)
            })
        );
    }

    #[test]
    fn recovery_epoch_is_strictly_monotonic() {
        let mut state = ControlState::new(cluster());
        state
            .apply(command(
                1,
                &state,
                ControlCommandKind::AdvanceRecoveryEpoch {
                    next: RecoveryEpoch(2),
                },
            ))
            .unwrap();

        assert_eq!(
            state.apply(command(
                2,
                &state,
                ControlCommandKind::AdvanceRecoveryEpoch {
                    next: RecoveryEpoch(2),
                },
            )),
            Err(ControlError::RecoveryEpochNotMonotonic)
        );
    }

    #[test]
    fn identical_command_sequence_produces_identical_state_root() {
        let mut left = ControlState::new(cluster());
        let mut right = ControlState::new(cluster());

        for tag in 1..=3 {
            let kind = match tag {
                1 => ControlCommandKind::AddLearner { node_id: node(7) },
                2 => ControlCommandKind::PromoteVoter { node_id: node(7) },
                _ => ControlCommandKind::SetPolicyHash {
                    policy_hash: [6; 32],
                },
            };
            let left_cmd = command(tag, &left, kind.clone());
            let right_cmd = command(tag, &right, kind);
            left.apply(left_cmd).unwrap();
            right.apply(right_cmd).unwrap();
        }

        assert_eq!(left, right);
        assert_eq!(left.state_root(), right.state_root());
    }

    #[test]
    fn checkpoint_install_preserves_idempotency_and_learner_role() {
        let mut source = ControlState::new(cluster());
        let add = command(
            1,
            &source,
            ControlCommandKind::AddLearner { node_id: node(7) },
        );
        let prior = source.apply(add.clone()).unwrap();
        let snapshot = source.checkpoint(ControlAppliedIndex(11));

        let mut learner = ControlState::new(cluster());
        let checkpoint = learner.install_snapshot(snapshot).unwrap();

        assert_eq!(checkpoint.applied_index, ControlAppliedIndex(11));
        assert_eq!(learner.members[&node(7)].role, MemberRole::Learner);
        assert_eq!(learner.apply(add).unwrap(), prior);
        assert_eq!(learner.control_epoch, ControlEpoch(1));
    }

    #[test]
    fn stale_checkpoint_cannot_roll_back_control_epoch() {
        let mut source = ControlState::new(cluster());
        source
            .apply(command(
                1,
                &source,
                ControlCommandKind::SetPolicyHash {
                    policy_hash: [1; 32],
                },
            ))
            .unwrap();
        let stale = source.checkpoint(ControlAppliedIndex(1));

        source
            .apply(command(
                2,
                &source,
                ControlCommandKind::SetPolicyHash {
                    policy_hash: [2; 32],
                },
            ))
            .unwrap();

        assert_eq!(
            source.install_snapshot(stale),
            Err(SnapshotInstallError::ControlEpochRollback {
                current: ControlEpoch(2),
                incoming: ControlEpoch(1)
            })
        );
    }

    #[test]
    fn bad_checkpoint_state_root_is_rejected() {
        let source = ControlState::new(cluster());
        let mut snapshot = source.checkpoint(ControlAppliedIndex(0));
        snapshot.checkpoint.state_root[0] ^= 0xff;

        let mut target = ControlState::new(cluster());
        assert_eq!(
            target.install_snapshot(snapshot),
            Err(SnapshotInstallError::StateRootMismatch)
        );
    }

    #[test]
    fn same_epoch_different_state_is_a_fork() {
        let mut left = ControlState::new(cluster());
        let mut right = ControlState::new(cluster());

        left.apply(command(
            1,
            &left,
            ControlCommandKind::SetPolicyHash {
                policy_hash: [1; 32],
            },
        ))
        .unwrap();
        right
            .apply(command(
                2,
                &right,
                ControlCommandKind::SetPolicyHash {
                    policy_hash: [2; 32],
                },
            ))
            .unwrap();

        let incoming = right.checkpoint(ControlAppliedIndex(1));
        assert_eq!(
            left.install_snapshot(incoming),
            Err(SnapshotInstallError::SameEpochFork)
        );
    }

    #[test]
    fn checkpoint_from_another_cluster_is_rejected() {
        let source = ControlState::new(other_cluster());
        let snapshot = source.checkpoint(ControlAppliedIndex(0));

        let mut target = ControlState::new(cluster());
        assert_eq!(
            target.install_snapshot(snapshot),
            Err(SnapshotInstallError::ClusterMismatch)
        );
    }

    #[test]
    fn snapshot_recovery_epoch_cannot_go_backwards() {
        let old = ControlState::new(cluster());
        let snapshot = old.checkpoint(ControlAppliedIndex(0));

        let mut target = ControlState::new(cluster());
        target
            .apply(command(
                1,
                &target,
                ControlCommandKind::AdvanceRecoveryEpoch {
                    next: RecoveryEpoch(2),
                },
            ))
            .unwrap();

        assert_eq!(
            target.install_snapshot(snapshot),
            Err(SnapshotInstallError::ControlEpochRollback {
                current: ControlEpoch(1),
                incoming: ControlEpoch(0)
            })
        );
    }
}
