use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    check_snapshot_invariants, reachable_chunks, rebuild_heads_from_versions, ChunkDescriptor,
    ChunkRef, ChunkRole, ChunkStorePort, CommitConsistency, CommitError, ObjectCommitPort,
    ObjectVersionManifest, ValidatedManifest, ValidatedObjectCommit,
};
use lesha_storage_memory::{MemoryChunkStore, MemoryObjectStore};
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, ControlFrontierHash, ManifestHash, ObjectId, OperationId,
    VersionId,
};
use sha2::{Digest, Sha256};

fn id16(tag: u8) -> [u8; 16] {
    [tag; 16]
}

fn hash32(tag: u8) -> [u8; 32] {
    [tag; 32]
}

fn set(ids: &[VersionId]) -> BTreeSet<VersionId> {
    ids.iter().copied().collect()
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

#[allow(clippy::too_many_arguments)]
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
    // Canonical test fixture: {1: h'<version-id>', 2: h'<object-id>'}
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
fn first_commit_and_rebuild_are_exact() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ciphertext-v1");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(10));
    let v1 = VersionId(id16(11));

    let receipt = objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(21)),
                vec![],
                BTreeSet::new(),
                chunk,
                CommitConsistency::StrictSingleHead,
                31,
            ),
        )
        .unwrap();

    assert_eq!(receipt.resulting_heads, set(&[v1]));
    assert_eq!(
        objects
            .rebuild_heads()
            .unwrap()
            .get(&object)
            .cloned()
            .unwrap(),
        set(&[v1])
    );
    check_snapshot_invariants(&objects.snapshot(), &chunks).unwrap();
}

#[test]
fn lost_ack_retry_is_idempotent() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ciphertext-v1");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(40));
    let v1 = VersionId(id16(41));
    let op = OperationId(id16(42));
    let cmd = commit_cmd(
        object,
        v1,
        op,
        vec![],
        BTreeSet::new(),
        chunk,
        CommitConsistency::StrictSingleHead,
        43,
    );

    let first = objects.commit(&chunks, cmd.clone()).unwrap();
    let second = objects.commit(&chunks, cmd).unwrap();
    assert_eq!(first, second);
    assert_eq!(objects.snapshot().ledger.len(), 1);
}

#[test]
fn operation_id_with_different_request_is_rejected() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ciphertext-v1");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(50));
    let v1 = VersionId(id16(51));
    let op = OperationId(id16(52));
    let cmd = commit_cmd(
        object,
        v1,
        op,
        vec![],
        BTreeSet::new(),
        chunk.clone(),
        CommitConsistency::StrictSingleHead,
        53,
    );
    objects.commit(&chunks, cmd).unwrap();

    let mut retry = commit_cmd(
        object,
        VersionId(id16(54)),
        op,
        vec![v1],
        set(&[v1]),
        chunk,
        CommitConsistency::StrictSingleHead,
        55,
    );
    retry.request_hash = hash32(99);
    assert_eq!(
        objects.commit(&chunks, retry),
        Err(CommitError::IdempotencyConflict)
    );
}

#[test]
fn concurrent_mergeable_branches_remain_explicit() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ciphertext");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(60));
    let v1 = VersionId(id16(61));
    let a = VersionId(id16(62));
    let b = VersionId(id16(63));
    let merged = VersionId(id16(64));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(71)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                71,
            ),
        )
        .unwrap();

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                a,
                OperationId(id16(72)),
                vec![v1],
                set(&[v1]),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                72,
            ),
        )
        .unwrap();

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                b,
                OperationId(id16(73)),
                vec![v1],
                set(&[a]),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                73,
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
                OperationId(id16(74)),
                vec![a, b],
                set(&[a, b]),
                chunk,
                CommitConsistency::MergeResolution,
                74,
            ),
        )
        .unwrap();
    assert_eq!(objects.heads(object).unwrap(), set(&[merged]));
    check_snapshot_invariants(&objects.snapshot(), &chunks).unwrap();
}

#[test]
fn corrupt_chunk_is_not_healthy() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ciphertext");
    assert!(chunks.corrupt_for_test(chunk.chunk_id));
    assert!(chunks.read_verified(chunk.chunk_id).is_err());
}

#[test]
fn strict_second_writer_without_current_head_parent_is_rejected() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"strict");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(80));
    let v1 = VersionId(id16(81));
    let v2 = VersionId(id16(82));
    let v3 = VersionId(id16(83));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(84)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                84,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v2,
                OperationId(id16(85)),
                vec![v1],
                set(&[v1]),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                85,
            ),
        )
        .unwrap();

    let result = objects.commit(
        &chunks,
        commit_cmd(
            object,
            v3,
            OperationId(id16(86)),
            vec![v1],
            set(&[v2]),
            chunk,
            CommitConsistency::StrictSingleHead,
            86,
        ),
    );
    assert_eq!(result, Err(CommitError::StrictConflict));
}

#[test]
fn missing_chunk_is_rejected_before_commit() {
    let bytes = b"missing";
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    let chunk = ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    };

    let chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(90));
    let version = VersionId(id16(91));

    let result = objects.commit(
        &chunks,
        commit_cmd(
            object,
            version,
            OperationId(id16(92)),
            vec![],
            BTreeSet::new(),
            chunk.clone(),
            CommitConsistency::StrictSingleHead,
            92,
        ),
    );
    assert_eq!(result, Err(CommitError::MissingChunk(chunk.chunk_id)));
    assert!(objects.heads(object).unwrap().is_empty());
}

#[test]
fn exact_head_set_mismatch_is_typed() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"heads");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(100));
    let v1 = VersionId(id16(101));
    let v2 = VersionId(id16(102));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(103)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                103,
            ),
        )
        .unwrap();

    let result = objects.commit(
        &chunks,
        commit_cmd(
            object,
            v2,
            OperationId(id16(104)),
            vec![v1],
            BTreeSet::new(),
            chunk,
            CommitConsistency::StrictSingleHead,
            104,
        ),
    );
    assert_eq!(
        result,
        Err(CommitError::HeadSetChanged {
            expected: BTreeSet::new(),
            actual: set(&[v1]),
        })
    );
}

#[test]
fn missing_parent_is_rejected() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"parent");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(110));
    let missing = VersionId(id16(111));
    let child = VersionId(id16(112));

    let result = objects.commit(
        &chunks,
        commit_cmd(
            object,
            child,
            OperationId(id16(113)),
            vec![missing],
            BTreeSet::new(),
            chunk,
            CommitConsistency::MergeableBranch,
            113,
        ),
    );
    assert_eq!(result, Err(CommitError::ParentMissing(missing)));
}

#[test]
fn cross_object_parent_is_rejected() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"cross-object");
    let mut objects = MemoryObjectStore::default();
    let object_a = ObjectId(id16(120));
    let object_b = ObjectId(id16(121));
    let parent = VersionId(id16(122));
    let child = VersionId(id16(123));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object_a,
                parent,
                OperationId(id16(124)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                124,
            ),
        )
        .unwrap();

    let result = objects.commit(
        &chunks,
        commit_cmd(
            object_b,
            child,
            OperationId(id16(125)),
            vec![parent],
            BTreeSet::new(),
            chunk,
            CommitConsistency::MergeableBranch,
            125,
        ),
    );
    assert_eq!(result, Err(CommitError::ManifestMismatch));
}

#[test]
fn orphan_chunk_never_creates_semantic_state() {
    let mut chunks = MemoryChunkStore::default();
    let used = put_chunk(&mut chunks, b"used");
    let orphan = put_chunk(&mut chunks, b"orphan");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(130));
    let version = VersionId(id16(131));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                version,
                OperationId(id16(132)),
                vec![],
                BTreeSet::new(),
                used,
                CommitConsistency::StrictSingleHead,
                132,
            ),
        )
        .unwrap();

    let snapshot = objects.snapshot();
    let reachable = reachable_chunks(&snapshot);
    let orphans = chunks.list_orphans(&reachable).unwrap();
    assert_eq!(orphans, vec![orphan.chunk_id]);
    assert_eq!(objects.heads(object).unwrap(), set(&[version]));
}

#[test]
fn ledger_chain_is_exact_for_multiple_commits() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"ledger");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(140));
    let v1 = VersionId(id16(141));
    let v2 = VersionId(id16(142));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(143)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                143,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v2,
                OperationId(id16(144)),
                vec![v1],
                set(&[v1]),
                chunk,
                CommitConsistency::StrictSingleHead,
                144,
            ),
        )
        .unwrap();

    let snapshot = objects.snapshot();
    assert_eq!(snapshot.ledger.len(), 2);
    assert_eq!(snapshot.ledger[0].seq.0, 1);
    assert_eq!(snapshot.ledger[1].seq.0, 2);
    assert_eq!(
        snapshot.ledger[1].previous_event_hash,
        Some(snapshot.ledger[0].event_hash)
    );
    check_snapshot_invariants(&snapshot, &chunks).unwrap();
}

#[test]
fn derived_head_projection_can_be_rebuilt_exactly() {
    let mut chunks = MemoryChunkStore::default();
    let chunk = put_chunk(&mut chunks, b"projection");
    let mut objects = MemoryObjectStore::default();
    let object = ObjectId(id16(150));
    let v1 = VersionId(id16(151));
    let a = VersionId(id16(152));
    let b = VersionId(id16(153));

    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                v1,
                OperationId(id16(154)),
                vec![],
                BTreeSet::new(),
                chunk.clone(),
                CommitConsistency::StrictSingleHead,
                154,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                a,
                OperationId(id16(155)),
                vec![v1],
                set(&[v1]),
                chunk.clone(),
                CommitConsistency::MergeableBranch,
                155,
            ),
        )
        .unwrap();
    objects
        .commit(
            &chunks,
            commit_cmd(
                object,
                b,
                OperationId(id16(156)),
                vec![v1],
                set(&[a]),
                chunk,
                CommitConsistency::MergeableBranch,
                156,
            ),
        )
        .unwrap();

    let mut snapshot = objects.snapshot();
    let expected = snapshot.heads.clone();
    snapshot.heads.clear();
    let rebuilt = rebuild_heads_from_versions(&snapshot.versions);
    assert_eq!(rebuilt, expected);
}
