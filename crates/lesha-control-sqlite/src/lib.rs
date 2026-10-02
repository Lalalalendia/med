#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use lesha_control_core::{
    CommittedControlReceipt, ControlCheckpoint, ControlError, ControlSnapshot,
    ControlSnapshotState, ControlState, MemberRecord, MemberRole, SnapshotInstallError,
    ValidatedControlCommand,
};
use lesha_types::{
    ClusterId, ControlAppliedIndex, ControlCommandId, ControlEpoch, NodeId, RecoveryEpoch,
};
use rusqlite::{params, Connection, OptionalExtension, Transaction};

const SCHEMA_VERSION: i64 = 1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ControlStoreFailPoint {
    AfterStateWriteBeforeCommit,
    AfterCommitBeforeReply,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlStoreError {
    Storage(String),
    Control(ControlError),
    Snapshot(SnapshotInstallError),
    ClusterMismatch,
    AppliedIndexGap {
        expected: ControlAppliedIndex,
        received: ControlAppliedIndex,
    },
    AppliedIndexRollback {
        current: ControlAppliedIndex,
        incoming: ControlAppliedIndex,
    },
    AppliedIndexConflict(ControlAppliedIndex),
    AppliedIndexCompacted(ControlAppliedIndex),
    PersistentStateInvalid(String),
    InjectedFailure(ControlStoreFailPoint),
    ReplyLostAfterCommit,
}

pub struct SqliteControlStore {
    conn: Connection,
    state: ControlState,
    applied_index: ControlAppliedIndex,
    failpoint: Option<ControlStoreFailPoint>,
}

impl SqliteControlStore {
    pub fn open(path: impl AsRef<Path>, cluster_id: ClusterId) -> Result<Self, ControlStoreError> {
        let mut conn = Connection::open(path).map_err(storage)?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA synchronous=FULL;
             PRAGMA foreign_keys=ON;",
        )
        .map_err(storage)?;
        create_schema(&conn)?;

        let existing = load_snapshot(&conn)?;
        let (state, applied_index) = if let Some(snapshot) = existing {
            if snapshot.checkpoint.cluster_id != cluster_id {
                return Err(ControlStoreError::ClusterMismatch);
            }
            let applied_index = snapshot.checkpoint.applied_index;
            let mut state = ControlState::new(cluster_id);
            state
                .install_snapshot(snapshot)
                .map_err(ControlStoreError::Snapshot)?;
            (state, applied_index)
        } else {
            let state = ControlState::new(cluster_id);
            let snapshot = state.checkpoint(ControlAppliedIndex(0));
            let tx = conn.transaction().map_err(storage)?;
            write_snapshot_state(&tx, &snapshot)?;
            tx.commit().map_err(storage)?;
            (state, ControlAppliedIndex(0))
        };

        Ok(Self {
            conn,
            state,
            applied_index,
            failpoint: None,
        })
    }

    pub fn state(&self) -> &ControlState {
        &self.state
    }

    pub fn applied_index(&self) -> ControlAppliedIndex {
        self.applied_index
    }

    pub fn set_failpoint_for_test(&mut self, failpoint: ControlStoreFailPoint) {
        self.failpoint = Some(failpoint);
    }

    pub fn apply_committed(
        &mut self,
        applied_index: ControlAppliedIndex,
        cmd: ValidatedControlCommand,
    ) -> Result<CommittedControlReceipt, ControlStoreError> {
        if applied_index.0 <= self.applied_index.0 {
            return self.replay_applied(applied_index, &cmd);
        }

        let expected =
            ControlAppliedIndex(self.applied_index.0.checked_add(1).ok_or_else(|| {
                ControlStoreError::PersistentStateInvalid("applied index overflow".into())
            })?);
        if applied_index != expected {
            return Err(ControlStoreError::AppliedIndexGap {
                expected,
                received: applied_index,
            });
        }

        let mut next = self.state.clone();
        let receipt = next
            .apply(cmd.clone())
            .map_err(ControlStoreError::Control)?;
        let snapshot = next.checkpoint(applied_index);
        let failpoint = self.failpoint.take();

        let tx = self.conn.transaction().map_err(storage)?;
        write_snapshot_state(&tx, &snapshot)?;
        tx.execute(
            "INSERT INTO control_applied_log
                (applied_index, command_id, request_hash, resulting_state_root)
             VALUES (?1, ?2, ?3, ?4)",
            params![
                to_i64(applied_index.0)?,
                cmd.command_id.0.as_slice(),
                cmd.request_hash.as_slice(),
                snapshot.checkpoint.state_root.as_slice(),
            ],
        )
        .map_err(storage)?;

        if failpoint == Some(ControlStoreFailPoint::AfterStateWriteBeforeCommit) {
            return Err(ControlStoreError::InjectedFailure(
                ControlStoreFailPoint::AfterStateWriteBeforeCommit,
            ));
        }

        tx.commit().map_err(storage)?;
        self.state = next;
        self.applied_index = applied_index;

        if failpoint == Some(ControlStoreFailPoint::AfterCommitBeforeReply) {
            return Err(ControlStoreError::ReplyLostAfterCommit);
        }

        Ok(receipt)
    }

    pub fn install_snapshot(
        &mut self,
        snapshot: ControlSnapshot,
    ) -> Result<ControlCheckpoint, ControlStoreError> {
        let incoming = snapshot.checkpoint.applied_index;

        if incoming.0 < self.applied_index.0 {
            return Err(ControlStoreError::AppliedIndexRollback {
                current: self.applied_index,
                incoming,
            });
        }
        if incoming == self.applied_index {
            if snapshot.checkpoint.state_root == self.state.state_root()
                && snapshot.checkpoint.control_epoch == self.state.control_epoch
                && snapshot.checkpoint.recovery_epoch == self.state.recovery_epoch
            {
                return Ok(snapshot.checkpoint);
            }
            return Err(ControlStoreError::AppliedIndexConflict(incoming));
        }

        let mut next = self.state.clone();
        next.install_snapshot(snapshot.clone())
            .map_err(ControlStoreError::Snapshot)?;
        let failpoint = self.failpoint.take();

        let tx = self.conn.transaction().map_err(storage)?;
        write_snapshot_state(&tx, &snapshot)?;
        tx.execute("DELETE FROM control_applied_log", [])
            .map_err(storage)?;

        if failpoint == Some(ControlStoreFailPoint::AfterStateWriteBeforeCommit) {
            return Err(ControlStoreError::InjectedFailure(
                ControlStoreFailPoint::AfterStateWriteBeforeCommit,
            ));
        }

        tx.commit().map_err(storage)?;
        self.state = next;
        self.applied_index = incoming;

        if failpoint == Some(ControlStoreFailPoint::AfterCommitBeforeReply) {
            return Err(ControlStoreError::ReplyLostAfterCommit);
        }

        Ok(snapshot.checkpoint)
    }

    fn replay_applied(
        &self,
        applied_index: ControlAppliedIndex,
        cmd: &ValidatedControlCommand,
    ) -> Result<CommittedControlReceipt, ControlStoreError> {
        let row = self
            .conn
            .query_row(
                "SELECT command_id, request_hash
                   FROM control_applied_log
                  WHERE applied_index = ?1",
                params![to_i64(applied_index.0)?],
                |row| Ok((row.get::<_, Vec<u8>>(0)?, row.get::<_, Vec<u8>>(1)?)),
            )
            .optional()
            .map_err(storage)?;

        let Some((command_id, request_hash)) = row else {
            return Err(ControlStoreError::AppliedIndexCompacted(applied_index));
        };
        if fixed::<16>(command_id, "applied command id")? != cmd.command_id.0
            || fixed::<32>(request_hash, "applied request hash")? != cmd.request_hash
        {
            return Err(ControlStoreError::AppliedIndexConflict(applied_index));
        }

        let snapshot = self.state.checkpoint(self.applied_index);
        snapshot
            .state
            .committed
            .get(&cmd.command_id)
            .cloned()
            .ok_or_else(|| {
                ControlStoreError::PersistentStateInvalid(
                    "applied log references missing command receipt".into(),
                )
            })
    }
}

fn create_schema(conn: &Connection) -> Result<(), ControlStoreError> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS control_schema (
             version INTEGER NOT NULL
         );
         CREATE TABLE IF NOT EXISTS control_meta (
             singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
             cluster_id BLOB NOT NULL,
             applied_index INTEGER NOT NULL,
             control_epoch INTEGER NOT NULL,
             recovery_epoch INTEGER NOT NULL,
             policy_hash BLOB NOT NULL,
             state_root BLOB NOT NULL
         );
         CREATE TABLE IF NOT EXISTS control_members (
             node_id BLOB PRIMARY KEY,
             role INTEGER NOT NULL,
             revoked INTEGER NOT NULL
         );
         CREATE TABLE IF NOT EXISTS control_revocations (
             node_id BLOB PRIMARY KEY
         );
         CREATE TABLE IF NOT EXISTS control_commands (
             command_id BLOB PRIMARY KEY,
             request_hash BLOB NOT NULL,
             control_epoch INTEGER NOT NULL,
             recovery_epoch INTEGER NOT NULL,
             state_root BLOB NOT NULL
         );
         CREATE TABLE IF NOT EXISTS control_applied_log (
             applied_index INTEGER PRIMARY KEY,
             command_id BLOB NOT NULL,
             request_hash BLOB NOT NULL,
             resulting_state_root BLOB NOT NULL
         );",
    )
    .map_err(storage)?;

    let current: Option<i64> = conn
        .query_row("SELECT version FROM control_schema LIMIT 1", [], |row| {
            row.get(0)
        })
        .optional()
        .map_err(storage)?;

    match current {
        None => {
            conn.execute(
                "INSERT INTO control_schema(version) VALUES (?1)",
                params![SCHEMA_VERSION],
            )
            .map_err(storage)?;
        }
        Some(version) if version == SCHEMA_VERSION => {}
        Some(version) => {
            return Err(ControlStoreError::PersistentStateInvalid(format!(
                "unsupported control schema version {version}"
            )));
        }
    }

    Ok(())
}

fn write_snapshot_state(
    tx: &Transaction<'_>,
    snapshot: &ControlSnapshot,
) -> Result<(), ControlStoreError> {
    tx.execute(
        "INSERT INTO control_meta
            (singleton, cluster_id, applied_index, control_epoch, recovery_epoch, policy_hash, state_root)
         VALUES (1, ?1, ?2, ?3, ?4, ?5, ?6)
         ON CONFLICT(singleton) DO UPDATE SET
            cluster_id = excluded.cluster_id,
            applied_index = excluded.applied_index,
            control_epoch = excluded.control_epoch,
            recovery_epoch = excluded.recovery_epoch,
            policy_hash = excluded.policy_hash,
            state_root = excluded.state_root",
        params![
            snapshot.state.cluster_id.0.as_slice(),
            to_i64(snapshot.checkpoint.applied_index.0)?,
            to_i64(snapshot.state.control_epoch.0)?,
            to_i64(snapshot.state.recovery_epoch.0)?,
            snapshot.state.policy_hash.as_slice(),
            snapshot.checkpoint.state_root.as_slice(),
        ],
    )
    .map_err(storage)?;

    tx.execute("DELETE FROM control_members", [])
        .map_err(storage)?;
    tx.execute("DELETE FROM control_revocations", [])
        .map_err(storage)?;
    tx.execute("DELETE FROM control_commands", [])
        .map_err(storage)?;

    for (node_id, member) in &snapshot.state.members {
        tx.execute(
            "INSERT INTO control_members(node_id, role, revoked) VALUES (?1, ?2, ?3)",
            params![
                node_id.0.as_slice(),
                match member.role {
                    MemberRole::Learner => 0_i64,
                    MemberRole::Voter => 1_i64,
                },
                i64::from(member.revoked),
            ],
        )
        .map_err(storage)?;
    }

    for node_id in &snapshot.state.revoked_nodes {
        tx.execute(
            "INSERT INTO control_revocations(node_id) VALUES (?1)",
            params![node_id.0.as_slice()],
        )
        .map_err(storage)?;
    }

    for (command_id, receipt) in &snapshot.state.committed {
        tx.execute(
            "INSERT INTO control_commands
                (command_id, request_hash, control_epoch, recovery_epoch, state_root)
             VALUES (?1, ?2, ?3, ?4, ?5)",
            params![
                command_id.0.as_slice(),
                receipt.request_hash.as_slice(),
                to_i64(receipt.control_epoch.0)?,
                to_i64(receipt.recovery_epoch.0)?,
                receipt.state_root.as_slice(),
            ],
        )
        .map_err(storage)?;
    }

    Ok(())
}

fn load_snapshot(conn: &Connection) -> Result<Option<ControlSnapshot>, ControlStoreError> {
    let meta = conn
        .query_row(
            "SELECT cluster_id, applied_index, control_epoch, recovery_epoch, policy_hash, state_root
               FROM control_meta
              WHERE singleton = 1",
            [],
            |row| {
                Ok((
                    row.get::<_, Vec<u8>>(0)?,
                    row.get::<_, i64>(1)?,
                    row.get::<_, i64>(2)?,
                    row.get::<_, i64>(3)?,
                    row.get::<_, Vec<u8>>(4)?,
                    row.get::<_, Vec<u8>>(5)?,
                ))
            },
        )
        .optional()
        .map_err(storage)?;

    let Some((cluster_id, applied_index, control_epoch, recovery_epoch, policy_hash, state_root)) =
        meta
    else {
        return Ok(None);
    };

    let cluster_id = ClusterId(fixed::<16>(cluster_id, "cluster id")?);
    let applied_index = ControlAppliedIndex(from_i64(applied_index, "applied index")?);
    let control_epoch = ControlEpoch(from_i64(control_epoch, "control epoch")?);
    let recovery_epoch = RecoveryEpoch(from_i64(recovery_epoch, "recovery epoch")?);
    let policy_hash = fixed::<32>(policy_hash, "policy hash")?;
    let state_root = fixed::<32>(state_root, "state root")?;

    let mut members = BTreeMap::new();
    {
        let mut stmt = conn
            .prepare("SELECT node_id, role, revoked FROM control_members ORDER BY node_id")
            .map_err(storage)?;
        let mut rows = stmt.query([]).map_err(storage)?;
        while let Some(row) = rows.next().map_err(storage)? {
            let node_id = NodeId(fixed::<32>(
                row.get::<_, Vec<u8>>(0).map_err(storage)?,
                "member node id",
            )?);
            let role = match row.get::<_, i64>(1).map_err(storage)? {
                0 => MemberRole::Learner,
                1 => MemberRole::Voter,
                other => {
                    return Err(ControlStoreError::PersistentStateInvalid(format!(
                        "invalid member role {other}"
                    )));
                }
            };
            let revoked = match row.get::<_, i64>(2).map_err(storage)? {
                0 => false,
                1 => true,
                other => {
                    return Err(ControlStoreError::PersistentStateInvalid(format!(
                        "invalid revoked flag {other}"
                    )));
                }
            };
            members.insert(
                node_id,
                MemberRecord {
                    node_id,
                    role,
                    revoked,
                },
            );
        }
    }

    let mut revoked_nodes = BTreeSet::new();
    {
        let mut stmt = conn
            .prepare("SELECT node_id FROM control_revocations ORDER BY node_id")
            .map_err(storage)?;
        let mut rows = stmt.query([]).map_err(storage)?;
        while let Some(row) = rows.next().map_err(storage)? {
            revoked_nodes.insert(NodeId(fixed::<32>(
                row.get::<_, Vec<u8>>(0).map_err(storage)?,
                "revoked node id",
            )?));
        }
    }

    let mut committed = BTreeMap::new();
    {
        let mut stmt = conn
            .prepare(
                "SELECT command_id, request_hash, control_epoch, recovery_epoch, state_root
                   FROM control_commands
                  ORDER BY command_id",
            )
            .map_err(storage)?;
        let mut rows = stmt.query([]).map_err(storage)?;
        while let Some(row) = rows.next().map_err(storage)? {
            let command_id = ControlCommandId(fixed::<16>(
                row.get::<_, Vec<u8>>(0).map_err(storage)?,
                "command id",
            )?);
            let request_hash =
                fixed::<32>(row.get::<_, Vec<u8>>(1).map_err(storage)?, "request hash")?;
            let receipt = CommittedControlReceipt {
                command_id,
                request_hash,
                control_epoch: ControlEpoch(from_i64(
                    row.get::<_, i64>(2).map_err(storage)?,
                    "receipt control epoch",
                )?),
                recovery_epoch: RecoveryEpoch(from_i64(
                    row.get::<_, i64>(3).map_err(storage)?,
                    "receipt recovery epoch",
                )?),
                state_root: fixed::<32>(
                    row.get::<_, Vec<u8>>(4).map_err(storage)?,
                    "receipt state root",
                )?,
            };
            committed.insert(command_id, receipt);
        }
    }

    Ok(Some(ControlSnapshot {
        checkpoint: ControlCheckpoint {
            cluster_id,
            applied_index,
            control_epoch,
            recovery_epoch,
            state_root,
        },
        state: ControlSnapshotState {
            cluster_id,
            control_epoch,
            recovery_epoch,
            members,
            revoked_nodes,
            policy_hash,
            committed,
        },
    }))
}

fn fixed<const N: usize>(bytes: Vec<u8>, label: &str) -> Result<[u8; N], ControlStoreError> {
    bytes.try_into().map_err(|bytes: Vec<u8>| {
        ControlStoreError::PersistentStateInvalid(format!(
            "{label} has length {}, expected {N}",
            bytes.len()
        ))
    })
}

fn to_i64(value: u64) -> Result<i64, ControlStoreError> {
    i64::try_from(value).map_err(|_| {
        ControlStoreError::PersistentStateInvalid(format!(
            "value {value} does not fit SQLite INTEGER"
        ))
    })
}

fn from_i64(value: i64, label: &str) -> Result<u64, ControlStoreError> {
    u64::try_from(value).map_err(|_| {
        ControlStoreError::PersistentStateInvalid(format!(
            "{label} must be non-negative, got {value}"
        ))
    })
}

fn storage(error: rusqlite::Error) -> ControlStoreError {
    ControlStoreError::Storage(error.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use lesha_control_core::ControlCommandKind;
    use tempfile::TempDir;

    fn cluster() -> ClusterId {
        ClusterId([1; 16])
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
    fn reopen_restores_exact_applied_state() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        let cmd = command(
            1,
            store.state(),
            ControlCommandKind::AddLearner { node_id: node(7) },
        );
        let receipt = store
            .apply_committed(ControlAppliedIndex(1), cmd.clone())
            .unwrap();
        assert_eq!(store.applied_index(), ControlAppliedIndex(1));
        drop(store);

        let mut reopened = SqliteControlStore::open(&db, cluster()).unwrap();
        assert_eq!(reopened.applied_index(), ControlAppliedIndex(1));
        assert_eq!(reopened.state().members[&node(7)].role, MemberRole::Learner);
        assert_eq!(
            reopened
                .apply_committed(ControlAppliedIndex(1), cmd)
                .unwrap(),
            receipt
        );
        assert_eq!(reopened.state().control_epoch, ControlEpoch(1));
    }

    #[test]
    fn failure_before_commit_reopens_old_state() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        let cmd = command(
            1,
            store.state(),
            ControlCommandKind::SetPolicyHash {
                policy_hash: [9; 32],
            },
        );
        store.set_failpoint_for_test(ControlStoreFailPoint::AfterStateWriteBeforeCommit);
        assert_eq!(
            store.apply_committed(ControlAppliedIndex(1), cmd),
            Err(ControlStoreError::InjectedFailure(
                ControlStoreFailPoint::AfterStateWriteBeforeCommit
            ))
        );
        drop(store);

        let reopened = SqliteControlStore::open(&db, cluster()).unwrap();
        assert_eq!(reopened.applied_index(), ControlAppliedIndex(0));
        assert_eq!(reopened.state().control_epoch, ControlEpoch(0));
        assert_eq!(reopened.state().policy_hash, [0; 32]);
    }

    #[test]
    fn lost_reply_after_commit_reopens_new_state_and_retries_exactly() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        let cmd = command(
            1,
            store.state(),
            ControlCommandKind::SetPolicyHash {
                policy_hash: [9; 32],
            },
        );
        store.set_failpoint_for_test(ControlStoreFailPoint::AfterCommitBeforeReply);
        assert_eq!(
            store.apply_committed(ControlAppliedIndex(1), cmd.clone()),
            Err(ControlStoreError::ReplyLostAfterCommit)
        );
        drop(store);

        let mut reopened = SqliteControlStore::open(&db, cluster()).unwrap();
        assert_eq!(reopened.applied_index(), ControlAppliedIndex(1));
        assert_eq!(reopened.state().control_epoch, ControlEpoch(1));
        assert_eq!(reopened.state().policy_hash, [9; 32]);

        let receipt = reopened
            .apply_committed(ControlAppliedIndex(1), cmd)
            .unwrap();
        assert_eq!(receipt.control_epoch, ControlEpoch(1));
        assert_eq!(reopened.state().control_epoch, ControlEpoch(1));
    }

    #[test]
    fn applied_index_gap_is_typed_and_does_not_mutate() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        let cmd = command(
            1,
            store.state(),
            ControlCommandKind::SetPolicyHash {
                policy_hash: [5; 32],
            },
        );

        assert_eq!(
            store.apply_committed(ControlAppliedIndex(2), cmd),
            Err(ControlStoreError::AppliedIndexGap {
                expected: ControlAppliedIndex(1),
                received: ControlAppliedIndex(2)
            })
        );
        assert_eq!(store.applied_index(), ControlAppliedIndex(0));
        assert_eq!(store.state().control_epoch, ControlEpoch(0));
    }

    #[test]
    fn snapshot_install_is_durable_and_preserves_learner_state() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut source = ControlState::new(cluster());
        source
            .apply(command(
                1,
                &source,
                ControlCommandKind::AddLearner { node_id: node(7) },
            ))
            .unwrap();
        let snapshot = source.checkpoint(ControlAppliedIndex(8));

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        store.install_snapshot(snapshot.clone()).unwrap();
        drop(store);

        let reopened = SqliteControlStore::open(&db, cluster()).unwrap();
        assert_eq!(reopened.applied_index(), ControlAppliedIndex(8));
        assert_eq!(
            reopened.state().state_root(),
            snapshot.checkpoint.state_root
        );
        assert_eq!(reopened.state().members[&node(7)].role, MemberRole::Learner);
    }

    #[test]
    fn snapshot_applied_index_cannot_roll_back() {
        let dir = TempDir::new().unwrap();
        let db = dir.path().join("control.sqlite");

        let mut source = ControlState::new(cluster());
        source
            .apply(command(
                1,
                &source,
                ControlCommandKind::SetPolicyHash {
                    policy_hash: [3; 32],
                },
            ))
            .unwrap();

        let mut store = SqliteControlStore::open(&db, cluster()).unwrap();
        store
            .install_snapshot(source.checkpoint(ControlAppliedIndex(5)))
            .unwrap();

        assert_eq!(
            store.install_snapshot(source.checkpoint(ControlAppliedIndex(4))),
            Err(ControlStoreError::AppliedIndexRollback {
                current: ControlAppliedIndex(5),
                incoming: ControlAppliedIndex(4)
            })
        );
    }
}
