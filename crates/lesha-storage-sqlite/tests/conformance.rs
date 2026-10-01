use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, ChunkStorePort, CommitConsistency, CommitError,
    ObjectCommitPort, ObjectVersionManifest, ValidatedManifest, ValidatedObjectCommit,
};
use lesha_storage_memory::MemoryChunkStore;
use lesha_storage_sqlite::SqliteObjectStore;
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, ControlFrontierHash, ManifestHash, ObjectId, OperationId,
    VersionId,
};
use sha2::{Digest, Sha256};
use tempfile::TempDir;

fn id16(tag: u8) -> [u8; 16] {
    [tag; 16]
}

fn hash32(tag: u8) -> [u8; 32] {
    [tag; 32]
}

fn set(ids: &[VersionId]) -> BTreeSet<VersionId> {
    ids.iter().copied().collect()
}

fn open_store() -> (TempDir, SqliteObjectStore) {
    let dir = TempDir::new().unwrap();
    let store = SqliteObjectStore::open(dir.path().join("metadata.sqlite")).unwrap();
    (dir, store)
}

fn put_chunk(store: &mut MemoryChunkStore, bytes: &[u8]) -> ChunkDescriptor {
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    let descriptor = ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    };
    store.put_durable(bytes, &descriptor).unwrap();
    descriptor
}

fn commit_cmd(
    object: ObjectId,
    version: VersionId,
    operation: OperationId,
    parents: Vec<VersionId>,
    expected_heads: BTreeSet<VersionId>,
    chunk: ChunkDescriptor,
    consistency: CommitConsistency,
    tag: u8,
) -> ValidatedObjectCommit {
    let mut cbor = Vec::with_capacity(1 + 2 + 17 + 2 + 17);
    cbor.push(0xa2);
    cbor.push(0x01);
    cbor.push(0x50);
    cbor.extend_from_slice(&version.0);
    cbor.push(0x02);
    cbor.push(0x50);
    cbor.extend_from_slice(&object.0);
    let canonical = CanonicalAuthorityBytes::validate(cbor).unwrap();

    let semantic = ObjectVersionManifest {
        cluster_id: ClusterId(id16(1)),
        object_id: object,
        version_id: version,
        operation_id: operation,
        parents,
        authority_epoch: AuthorityEpoch(1),
        control_frontier: ControlFrontierHash(hash32(2)),
        chunks: vec![ChunkRef {
            ordinal: 0,
            role: ChunkRole::Payload,
            descriptor: chunk,
        }],
    };

    ValidatedObjectCommit {
        manifest: ValidatedManifest::new_prevalidated(
            semantic,
            canonical,
            ManifestHash(hash32(tag)),
        ),
        request_hash: hash32(tag.wrapping_add(64)),
        expected_heads,
        consistency,
    }
}

#[test]
fn sqlite_first_commit_and_rebuild_are_exact() {
    let (_dir, mut objects) = open_store();
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"sqlite-v1");
    let object = ObjectId(id16(10));
    let v1 = VersionId(id16(11));

    let receipt = objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(12)),
                vec![],
                BTreeSet::new(),
                chunk,
                CommitConsistency::StrictSingleHead,
                12,
            ),
        )
        .unwrap();

    assert_eq!(receipt.resulting_heads, set(&[v1]));
    assert_eq!(objects.heads(object).unwrap(), set(&[v1]));
    assert_eq!(
        objects.rebuild_heads().unwrap().get(&object).cloned(),
        Some(set(&[v1]))
    );
    assert_eq!(
        objects.version(v1).unwrap().manifest.semantic.version_id,
        v1
    );
}

#[test]
fn sqlite_lost_ack_retry_returns_exact_prior_receipt() {
    let (dir, mut objects) = open_store();
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"sqlite-idempotent");
    let object = ObjectId(id16(20));
    let v1 = VersionId(id16(21));
    let op = OperationId(id16(22));
    let cmd = commit_cmd(
        object,
        v1,
        op,
        vec![],
        BTreeSet::new(),
        chunk,
        CommitConsistency::StrictSingleHead,
        22,
    );

    let first = objects.commit(&chunks, cmd.clone()).unwrap();
    drop(objects);

    let mut reopened = SqliteObjectStore::open(dir.path().join("metadata.sqlite")).unwrap();
    let second = reopened.commit(&chunks, cmd).unwrap();
    assert_eq!(first, second);
    assert_eq!(reopened.operation(op).unwrap(), Some(first));
}

#[test]
fn sqlite_operation_id_conflict_is_rejected() {
    let (_dir, mut objects) = open_store();
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"sqlite-op");
    let object = ObjectId(id16(30));
    let v1 = VersionId(id16(31));
    let op = OperationId(id16(32));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                op,
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                32,
            ),
        )
        .unwrap();

    let mut retry = commit_cmd(
        object,
        VersionId(id16(33)),
        op,
        vec![v1],
        set(&[v1]),
        chunk,
        CommitConsistency::StrictSingleHead,
        33,
    );
    retry.request_hash = hash32(99);
    assert_eq!(
        objects.commit(&chunks, retry),
        Err(CommitError::IdempotencyConflict)
    );
}

#[test]
fn sqlite_mergeable_branches_and_resolution_are_explicit() {
    let (_dir, mut objects) = open_store();
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"sqlite-branches");
    let object = ObjectId(id16(40));
    let v1 = VersionId(id16(41));
    let a = VersionId(id16(42));
    let b = VersionId(id16(43));
    let merged = VersionId(id16(44));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(45)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                45,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                a,
                OperationId(id16(46)),
                vec![v1],
                set(&[v1]),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                46,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                b,
                OperationId(id16(47)),
                vec![v1],
                set(&[a]),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                47,
            ),
        )
        .unwrap();
    assert_eq!(objects.heads(object).unwrap(), set(&[a, b]));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                merged,
                OperationId(id16(48)),
                vec![a, b],
                set(&[a, b]),
                chunk,
                CommitConsistency::MergeResolution,
                48,
            ),
        )
        .unwrap();
    assert_eq!(objects.heads(object).unwrap(), set(&[merged]));
}

#[test]
fn sqlite_missing_chunk_and_head_mismatch_are_typed() {
    let (_dir, mut objects) = open_store();
    let bytes = b"sqlite-missing";
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    let missing = ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    };
    let chunks = MemoryChunkStore::default();
    let object = ObjectId(id16(50));

    assert_eq!(
        objects.commit(
            &chunks,
            commit_cmd(
                object,
                VersionId(id16(51)),
                OperationId(id16(52)),
                vec![],
                BTreeSet::new(),
                missing.clone(),
                CommitConsistency::StrictSingleHead,
                52
            ),
        ),
        Err(CommitError::MissingChunk(missing.chunk_id))
    );

    let mut chunks = chunks;
    let chunk = put_chunk(&mut chunks, b"sqlite-heads");
    let v1 = VersionId(id16(53));
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(54)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                54,
            ),
        )
        .unwrap();

    assert_eq!(
        objects.commit(
            &chunks,
            commit_cmd(
                object,
                VersionId(id16(55)),
                OperationId(id16(56)),
                vec![v1],
                BTreeSet::new(),
                chunk,
                CommitConsistency::StrictSingleHead,
                56
            ),
        ),
        Err(CommitError::HeadSetChanged {
            expected: BTreeSet::new(),
            actual: set(&[v1]),
        })
    );
}

#[test]
fn sqlite_parent_rules_match_memory_oracle() {
    let (_dir, mut objects) = open_store();
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"sqlite-parents");
    let object_a = ObjectId(id16(60));
    let object_b = ObjectId(id16(61));
    let parent = VersionId(id16(62));

    assert_eq!(
        objects.commit(
            &chunks,
            commit_cmd(
                object_a,
                VersionId(id16(63)),
                OperationId(id16(64)),
                vec![parent],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                64
            ),
        ),
        Err(CommitError::ParentMissing(parent))
    );

    objects
        .commit(
            &chunks,
            commit_cmd(
                object_a,
                parent,
                OperationId(id16(65)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                65,
            ),
        )
        .unwrap();

    assert_eq!(
        objects.commit(
            &chunks,
            commit_cmd(
                object_b,
                VersionId(id16(66)),
                OperationId(id16(67)),
                vec![parent],
                BTreeSet::new(),
                chunk,
                CommitConsistency::MergeableBranch,
                67
            ),
        ),
        Err(CommitError::ManifestMismatch)
    );
}
