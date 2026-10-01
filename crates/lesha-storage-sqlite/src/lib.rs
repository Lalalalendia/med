use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    hash_commit_event, hash_heads, rebuild_heads_from_versions, ChunkAvailability, ChunkDescriptor,
    ChunkHealth, ChunkRef, ChunkRole, CommitConsistency, CommitError, ObjectCommitPort,
    ObjectCommitReceipt, ObjectVersionManifest, ReadError, RebuildError, StorageFailPoint,
    StoredObjectVersion, ValidatedManifest, ValidatedObjectCommit,
};
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, CommitSeq, ControlFrontierHash, ManifestHash, ObjectId,
    OperationId, VersionId,
};
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};

pub struct SqliteObjectStore {
    conn: Connection,
    failpoint: Option<StorageFailPoint>,
}

impl SqliteObjectStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, rusqlite::Error> {
        let conn = Connection::open(path)?;
        conn.pragma_update(None, "journal_mode", "WAL")?;
        conn.pragma_update(None, "synchronous", "FULL")?;
        conn.pragma_update(None, "foreign_keys", "ON")?;
        conn.execute_batch(SCHEMA_M0)?;
        Ok(Self {
            conn,
            failpoint: None,
        })
    }

    pub fn connection(&self) -> &Connection {
        &self.conn
    }

    pub fn set_failpoint_for_test(&mut self, point: StorageFailPoint) {
        self.failpoint = Some(point);
    }
}

impl ObjectCommitPort for SqliteObjectStore {
    fn commit(
        &mut self,
        chunks: &dyn ChunkAvailability,
        cmd: ValidatedObjectCommit,
    ) -> Result<ObjectCommitReceipt, CommitError> {
        let semantic = cmd.manifest.semantic.clone();
        let mut failpoint = self.failpoint.take();

        if let Some(existing) = load_operation(&self.conn, semantic.operation_id)
            .map_err(|_| CommitError::StorageUnavailable)?
        {
            if existing.request_hash == cmd.request_hash {
                return Ok(existing);
            }
            return Err(CommitError::IdempotencyConflict);
        }

        for chunk in &semantic.chunks {
            match chunks.chunk_health(chunk.descriptor.chunk_id) {
                Ok(ChunkHealth::Healthy) => {}
                Ok(ChunkHealth::Missing) => {
                    return Err(CommitError::MissingChunk(chunk.descriptor.chunk_id));
                }
                Ok(ChunkHealth::DigestMismatch) => {
                    return Err(CommitError::CorruptChunk(chunk.descriptor.chunk_id));
                }
                Ok(ChunkHealth::DurabilityUnknown) => return Err(CommitError::DurabilityUnknown),
                Ok(ChunkHealth::IoFailure) | Err(_) => return Err(CommitError::StorageUnavailable),
            }
        }

        hit_failpoint(&mut failpoint, StorageFailPoint::MetadataBeforeBegin)?;

        let tx = self
            .conn
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|_| CommitError::StorageUnavailable)?;

        if let Some(existing) = load_operation(&tx, semantic.operation_id)
            .map_err(|_| CommitError::StorageUnavailable)?
        {
            if existing.request_hash == cmd.request_hash {
                return Ok(existing);
            }
            return Err(CommitError::IdempotencyConflict);
        }

        let version_exists = tx
            .query_row(
                "SELECT 1 FROM object_versions WHERE version_id = ?1",
                params![&semantic.version_id.0[..]],
                |_| Ok(()),
            )
            .optional()
            .map_err(|_| CommitError::StorageUnavailable)?
            .is_some();
        if version_exists {
            return Err(CommitError::VersionAlreadyExists);
        }

        let current_heads =
            load_heads(&tx, semantic.object_id).map_err(|_| CommitError::StorageUnavailable)?;
        if current_heads != cmd.expected_heads {
            return Err(CommitError::HeadSetChanged {
                expected: cmd.expected_heads,
                actual: current_heads,
            });
        }

        let parent_set: BTreeSet<VersionId> = semantic.parents.iter().copied().collect();
        if parent_set.len() != semantic.parents.len() {
            return Err(CommitError::ManifestMismatch);
        }
        for parent in &parent_set {
            let parent_object: Option<Vec<u8>> = tx
                .query_row(
                    "SELECT object_id FROM object_versions WHERE version_id = ?1",
                    params![&parent.0[..]],
                    |row| row.get(0),
                )
                .optional()
                .map_err(|_| CommitError::StorageUnavailable)?;
            let Some(parent_object) = parent_object else {
                return Err(CommitError::ParentMissing(*parent));
            };
            if fixed16(parent_object).map_err(|_| CommitError::StorageUnavailable)?
                != semantic.object_id.0
            {
                return Err(CommitError::ManifestMismatch);
            }
        }

        match cmd.consistency {
            CommitConsistency::StrictSingleHead => {
                if current_heads.len() > 1 || parent_set != current_heads {
                    return Err(CommitError::StrictConflict);
                }
            }
            CommitConsistency::MergeableBranch => {}
            CommitConsistency::MergeResolution => {
                if current_heads.len() < 2 || parent_set != current_heads {
                    return Err(CommitError::StrictConflict);
                }
            }
        }

        let mut resulting_heads = current_heads.clone();
        for parent in &parent_set {
            resulting_heads.remove(parent);
        }
        resulting_heads.insert(semantic.version_id);

        let next_seq_i64: i64 = tx
            .query_row(
                "SELECT COALESCE(MAX(commit_seq), 0) + 1 FROM commit_ledger",
                [],
                |row| row.get(0),
            )
            .map_err(|_| CommitError::StorageUnavailable)?;
        let seq =
            CommitSeq(u64::try_from(next_seq_i64).map_err(|_| CommitError::StorageUnavailable)?);

        let previous_event_hash: Option<Vec<u8>> = tx
            .query_row(
                "SELECT event_hash FROM commit_ledger ORDER BY commit_seq DESC LIMIT 1",
                [],
                |row| row.get(0),
            )
            .optional()
            .map_err(|_| CommitError::StorageUnavailable)?;
        let previous_event_hash = previous_event_hash
            .map(fixed32)
            .transpose()
            .map_err(|_| CommitError::StorageUnavailable)?;

        let prior_heads_hash = hash_heads(&current_heads);
        let resulting_heads_hash = hash_heads(&resulting_heads);
        let event_hash = hash_commit_event(
            seq,
            semantic.operation_id,
            semantic.object_id,
            semantic.version_id,
            prior_heads_hash,
            resulting_heads_hash,
            previous_event_hash,
        );

        let authority_epoch = i64::try_from(semantic.authority_epoch.0)
            .map_err(|_| CommitError::StorageUnavailable)?;
        let commit_seq = i64::try_from(seq.0).map_err(|_| CommitError::StorageUnavailable)?;

        tx.execute(
            "INSERT INTO object_versions(
                version_id, cluster_id, object_id, operation_id, manifest_hash, manifest_bytes,
                authority_epoch, control_frontier, commit_seq
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)",
            params![
                &semantic.version_id.0[..],
                &semantic.cluster_id.0[..],
                &semantic.object_id.0[..],
                &semantic.operation_id.0[..],
                &cmd.manifest.manifest_hash.0[..],
                cmd.manifest.canonical.as_slice(),
                authority_epoch,
                &semantic.control_frontier.0[..],
                commit_seq,
            ],
        )
        .map_err(|_| CommitError::StorageUnavailable)?;

        for parent in &parent_set {
            tx.execute(
                "INSERT INTO version_parents(version_id, parent_version_id) VALUES (?1, ?2)",
                params![&semantic.version_id.0[..], &parent.0[..]],
            )
            .map_err(|_| CommitError::StorageUnavailable)?;
        }

        for chunk in &semantic.chunks {
            tx.execute(
                "INSERT INTO version_chunks(
                    version_id, ordinal, role, chunk_id, ciphertext_len
                 ) VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    &semantic.version_id.0[..],
                    i64::from(chunk.ordinal),
                    i64::from(chunk.role.storage_code()),
                    &chunk.descriptor.chunk_id.0[..],
                    i64::try_from(chunk.descriptor.ciphertext_len)
                        .map_err(|_| CommitError::StorageUnavailable)?,
                ],
            )
            .map_err(|_| CommitError::StorageUnavailable)?;
        }

        hit_failpoint(&mut failpoint, StorageFailPoint::MetadataAfterManifest)?;

        tx.execute(
            "DELETE FROM object_heads WHERE object_id = ?1",
            params![&semantic.object_id.0[..]],
        )
        .map_err(|_| CommitError::StorageUnavailable)?;
        for head in &resulting_heads {
            tx.execute(
                "INSERT INTO object_heads(object_id, version_id) VALUES (?1, ?2)",
                params![&semantic.object_id.0[..], &head.0[..]],
            )
            .map_err(|_| CommitError::StorageUnavailable)?;
        }

        hit_failpoint(&mut failpoint, StorageFailPoint::MetadataAfterHeads)?;

        tx.execute(
            "INSERT INTO commit_ledger(
                commit_seq, operation_id, object_id, version_id, prior_heads_hash,
                resulting_heads_hash, previous_event_hash, event_hash
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)",
            params![
                commit_seq,
                &semantic.operation_id.0[..],
                &semantic.object_id.0[..],
                &semantic.version_id.0[..],
                &prior_heads_hash[..],
                &resulting_heads_hash[..],
                previous_event_hash.as_ref().map(|v| &v[..]),
                &event_hash[..],
            ],
        )
        .map_err(|_| CommitError::StorageUnavailable)?;

        hit_failpoint(&mut failpoint, StorageFailPoint::MetadataAfterLedger)?;

        tx.execute(
            "INSERT INTO committed_operations(
                operation_id, request_hash, object_id, version_id, commit_seq,
                manifest_hash, resulting_heads_hash
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            params![
                &semantic.operation_id.0[..],
                &cmd.request_hash[..],
                &semantic.object_id.0[..],
                &semantic.version_id.0[..],
                commit_seq,
                &cmd.manifest.manifest_hash.0[..],
                &resulting_heads_hash[..],
            ],
        )
        .map_err(|_| CommitError::StorageUnavailable)?;

        for head in &resulting_heads {
            tx.execute(
                "INSERT INTO operation_result_heads(operation_id, version_id) VALUES (?1, ?2)",
                params![&semantic.operation_id.0[..], &head.0[..]],
            )
            .map_err(|_| CommitError::StorageUnavailable)?;
        }

        hit_failpoint(&mut failpoint, StorageFailPoint::MetadataBeforeCommit)?;
        tx.commit().map_err(|_| CommitError::StorageUnavailable)?;
        hit_failpoint(
            &mut failpoint,
            StorageFailPoint::MetadataAfterCommitBeforeReply,
        )?;

        Ok(ObjectCommitReceipt {
            object_id: semantic.object_id,
            version_id: semantic.version_id,
            operation_id: semantic.operation_id,
            request_hash: cmd.request_hash,
            commit_seq: seq,
            manifest_hash: cmd.manifest.manifest_hash,
            resulting_heads,
        })
    }

    fn heads(&self, object: ObjectId) -> Result<BTreeSet<VersionId>, ReadError> {
        load_heads(&self.conn, object)
    }

    fn version(&self, version: VersionId) -> Result<StoredObjectVersion, ReadError> {
        load_version(&self.conn, version)
    }

    fn operation(&self, op: OperationId) -> Result<Option<ObjectCommitReceipt>, ReadError> {
        load_operation(&self.conn, op)
    }

    fn rebuild_heads(&self) -> Result<BTreeMap<ObjectId, BTreeSet<VersionId>>, RebuildError> {
        let mut stmt = self
            .conn
            .prepare("SELECT version_id FROM object_versions ORDER BY version_id")
            .map_err(|_| RebuildError::StorageUnavailable)?;
        let ids = stmt
            .query_map([], |row| row.get::<_, Vec<u8>>(0))
            .map_err(|_| RebuildError::StorageUnavailable)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| RebuildError::StorageUnavailable)?;
        drop(stmt);

        let mut versions = BTreeMap::new();
        for raw in ids {
            let version = VersionId(fixed16(raw).map_err(|_| RebuildError::StorageUnavailable)?);
            let stored =
                load_version(&self.conn, version).map_err(|_| RebuildError::StorageUnavailable)?;
            versions.insert(version, stored);
        }
        Ok(rebuild_heads_from_versions(&versions))
    }
}

fn hit_failpoint(
    configured: &mut Option<StorageFailPoint>,
    point: StorageFailPoint,
) -> Result<(), CommitError> {
    if *configured == Some(point) {
        *configured = None;
        return Err(CommitError::StorageUnavailable);
    }
    Ok(())
}

fn load_heads(conn: &Connection, object: ObjectId) -> Result<BTreeSet<VersionId>, ReadError> {
    let mut stmt = conn
        .prepare("SELECT version_id FROM object_heads WHERE object_id = ?1 ORDER BY version_id")
        .map_err(|_| ReadError::StorageUnavailable)?;
    let rows = stmt
        .query_map(params![&object.0[..]], |row| row.get::<_, Vec<u8>>(0))
        .map_err(|_| ReadError::StorageUnavailable)?;
    let mut out = BTreeSet::new();
    for row in rows {
        out.insert(VersionId(fixed16(
            row.map_err(|_| ReadError::StorageUnavailable)?,
        )?));
    }
    Ok(out)
}

fn load_operation(
    conn: &Connection,
    op: OperationId,
) -> Result<Option<ObjectCommitReceipt>, ReadError> {
    let row: Option<(Vec<u8>, Vec<u8>, Vec<u8>, i64, Vec<u8>, Vec<u8>)> = conn
        .query_row(
            "SELECT request_hash, object_id, version_id, commit_seq, manifest_hash,
                    resulting_heads_hash
             FROM committed_operations WHERE operation_id = ?1",
            params![&op.0[..]],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                ))
            },
        )
        .optional()
        .map_err(|_| ReadError::StorageUnavailable)?;

    let Some((request_hash, object_id, version_id, commit_seq, manifest_hash, stored_heads_hash)) =
        row
    else {
        return Ok(None);
    };

    let mut stmt = conn
        .prepare(
            "SELECT version_id FROM operation_result_heads
             WHERE operation_id = ?1 ORDER BY version_id",
        )
        .map_err(|_| ReadError::StorageUnavailable)?;
    let rows = stmt
        .query_map(params![&op.0[..]], |row| row.get::<_, Vec<u8>>(0))
        .map_err(|_| ReadError::StorageUnavailable)?;
    let mut resulting_heads = BTreeSet::new();
    for row in rows {
        resulting_heads.insert(VersionId(fixed16(
            row.map_err(|_| ReadError::StorageUnavailable)?,
        )?));
    }

    if hash_heads(&resulting_heads) != fixed32(stored_heads_hash)? {
        return Err(ReadError::Corrupt);
    }

    Ok(Some(ObjectCommitReceipt {
        object_id: ObjectId(fixed16(object_id)?),
        version_id: VersionId(fixed16(version_id)?),
        operation_id: op,
        request_hash: fixed32(request_hash)?,
        commit_seq: CommitSeq(u64_from_i64(commit_seq)?),
        manifest_hash: ManifestHash(fixed32(manifest_hash)?),
        resulting_heads,
    }))
}

fn load_version(conn: &Connection, version: VersionId) -> Result<StoredObjectVersion, ReadError> {
    let row: Option<(
        Vec<u8>,
        Vec<u8>,
        Vec<u8>,
        Vec<u8>,
        Vec<u8>,
        i64,
        Vec<u8>,
        i64,
    )> = conn
        .query_row(
            "SELECT cluster_id, object_id, operation_id, manifest_hash, manifest_bytes,
                    authority_epoch, control_frontier, commit_seq
             FROM object_versions WHERE version_id = ?1",
            params![&version.0[..]],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                    row.get(5)?,
                    row.get(6)?,
                    row.get(7)?,
                ))
            },
        )
        .optional()
        .map_err(|_| ReadError::StorageUnavailable)?;

    let Some((
        cluster_id,
        object_id,
        operation_id,
        manifest_hash,
        manifest_bytes,
        authority_epoch,
        control_frontier,
        commit_seq,
    )) = row
    else {
        return Err(ReadError::NotFound);
    };

    let mut parent_stmt = conn
        .prepare(
            "SELECT parent_version_id FROM version_parents
             WHERE version_id = ?1 ORDER BY parent_version_id",
        )
        .map_err(|_| ReadError::StorageUnavailable)?;
    let parent_rows = parent_stmt
        .query_map(params![&version.0[..]], |row| row.get::<_, Vec<u8>>(0))
        .map_err(|_| ReadError::StorageUnavailable)?;
    let mut parents = Vec::new();
    for row in parent_rows {
        parents.push(VersionId(fixed16(
            row.map_err(|_| ReadError::StorageUnavailable)?,
        )?));
    }

    let mut chunk_stmt = conn
        .prepare(
            "SELECT ordinal, role, chunk_id, ciphertext_len FROM version_chunks
             WHERE version_id = ?1 ORDER BY ordinal",
        )
        .map_err(|_| ReadError::StorageUnavailable)?;
    let chunk_rows = chunk_stmt
        .query_map(params![&version.0[..]], |row| {
            Ok((
                row.get::<_, i64>(0)?,
                row.get::<_, i64>(1)?,
                row.get::<_, Vec<u8>>(2)?,
                row.get::<_, i64>(3)?,
            ))
        })
        .map_err(|_| ReadError::StorageUnavailable)?;
    let mut chunks = Vec::new();
    for row in chunk_rows {
        let (ordinal, role, chunk_id, ciphertext_len) =
            row.map_err(|_| ReadError::StorageUnavailable)?;
        let role_u32 = u32::try_from(role).map_err(|_| ReadError::Corrupt)?;
        chunks.push(ChunkRef {
            ordinal: u32::try_from(ordinal).map_err(|_| ReadError::Corrupt)?,
            role: ChunkRole::from_storage_code(role_u32).ok_or(ReadError::Corrupt)?,
            descriptor: ChunkDescriptor {
                chunk_id: ChunkId(fixed32(chunk_id)?),
                ciphertext_len: u64_from_i64(ciphertext_len)?,
            },
        });
    }

    let canonical =
        CanonicalAuthorityBytes::validate(manifest_bytes).map_err(|_| ReadError::Corrupt)?;
    let semantic = ObjectVersionManifest {
        cluster_id: ClusterId(fixed16(cluster_id)?),
        object_id: ObjectId(fixed16(object_id)?),
        version_id: version,
        operation_id: OperationId(fixed16(operation_id)?),
        parents,
        authority_epoch: AuthorityEpoch(u64_from_i64(authority_epoch)?),
        control_frontier: ControlFrontierHash(fixed32(control_frontier)?),
        chunks,
    };

    Ok(StoredObjectVersion {
        manifest: ValidatedManifest::new_prevalidated(
            semantic,
            canonical,
            ManifestHash(fixed32(manifest_hash)?),
        ),
        commit_seq: CommitSeq(u64_from_i64(commit_seq)?),
    })
}

fn fixed16(bytes: Vec<u8>) -> Result<[u8; 16], ReadError> {
    bytes.try_into().map_err(|_| ReadError::Corrupt)
}

fn fixed32(bytes: Vec<u8>) -> Result<[u8; 32], ReadError> {
    bytes.try_into().map_err(|_| ReadError::Corrupt)
}

fn u64_from_i64(value: i64) -> Result<u64, ReadError> {
    u64::try_from(value).map_err(|_| ReadError::Corrupt)
}

pub const SCHEMA_M0: &str = r#"
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', 1);

CREATE TABLE IF NOT EXISTS object_versions (
    version_id BLOB PRIMARY KEY,
    cluster_id BLOB NOT NULL,
    object_id BLOB NOT NULL,
    operation_id BLOB NOT NULL,
    manifest_hash BLOB NOT NULL UNIQUE,
    manifest_bytes BLOB NOT NULL,
    authority_epoch INTEGER NOT NULL,
    control_frontier BLOB NOT NULL,
    commit_seq INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS version_parents (
    version_id BLOB NOT NULL,
    parent_version_id BLOB NOT NULL,
    PRIMARY KEY(version_id, parent_version_id),
    FOREIGN KEY(version_id) REFERENCES object_versions(version_id)
);

CREATE TABLE IF NOT EXISTS version_chunks (
    version_id BLOB NOT NULL,
    ordinal INTEGER NOT NULL,
    role INTEGER NOT NULL,
    chunk_id BLOB NOT NULL,
    ciphertext_len INTEGER NOT NULL,
    PRIMARY KEY(version_id, ordinal),
    FOREIGN KEY(version_id) REFERENCES object_versions(version_id)
);

CREATE TABLE IF NOT EXISTS object_heads (
    object_id BLOB NOT NULL,
    version_id BLOB NOT NULL,
    PRIMARY KEY(object_id, version_id),
    FOREIGN KEY(version_id) REFERENCES object_versions(version_id)
);

CREATE TABLE IF NOT EXISTS committed_operations (
    operation_id BLOB PRIMARY KEY,
    request_hash BLOB NOT NULL,
    object_id BLOB NOT NULL,
    version_id BLOB NOT NULL,
    commit_seq INTEGER NOT NULL UNIQUE,
    manifest_hash BLOB NOT NULL,
    resulting_heads_hash BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS operation_result_heads (
    operation_id BLOB NOT NULL,
    version_id BLOB NOT NULL,
    PRIMARY KEY(operation_id, version_id),
    FOREIGN KEY(operation_id) REFERENCES committed_operations(operation_id),
    FOREIGN KEY(version_id) REFERENCES object_versions(version_id)
);

CREATE TABLE IF NOT EXISTS commit_ledger (
    commit_seq INTEGER PRIMARY KEY,
    operation_id BLOB NOT NULL UNIQUE,
    object_id BLOB NOT NULL,
    version_id BLOB NOT NULL,
    prior_heads_hash BLOB NOT NULL,
    resulting_heads_hash BLOB NOT NULL,
    previous_event_hash BLOB,
    event_hash BLOB NOT NULL UNIQUE
);
"#;
