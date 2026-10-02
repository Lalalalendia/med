use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, ChunkStorePort, CommitConsistency, CommitError,
    ObjectCommitPort, ObjectVersionManifest, ReadError, StorageFailPoint, ValidatedManifest,
    ValidatedObjectCommit,
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
    tag: u8,
) -> ValidatedObjectCommit {
    let mut cbor = Vec::new();
    cbor.push(0xa2);
    cbor.push(0x01);
    cbor.push(0x50);
    cbor.extend_from_slice(&version.0);
    cbor.push(0x02);
    cbor.push(0x50);
    cbor.extend_from_slice(&object.0);
    let canonical = CanonicalAuthorityBytes::validate(cbor).unwrap();

    ValidatedObjectCommit {
        manifest: ValidatedManifest::new_prevalidated(
            ObjectVersionManifest {
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
            },
            canonical,
            ManifestHash(hash32(tag)),
        ),
        request_hash: hash32(tag.wrapping_add(64)),
        expected_heads,
        consistency: CommitConsistency::StrictSingleHead,
    }
}

#[test]
fn metadata_failpoints_reopen_to_exact_old_or_new_state() {
    let points = [
        StorageFailPoint::MetadataBeforeBegin,
        StorageFailPoint::MetadataAfterManifest,
        StorageFailPoint::MetadataAfterHeads,
        StorageFailPoint::MetadataAfterLedger,
        StorageFailPoint::MetadataBeforeCommit,
        StorageFailPoint::MetadataAfterCommitBeforeReply,
    ];

    for point in points {
        let dir = TempDir::new().unwrap();
        let db_path = dir.path().join("metadata.sqlite");
        let mut chunks = MemoryChunkStore::default();
        let chunk = put_chunk(&mut chunks, b"metadata-crash");
        let object = ObjectId(id16(10));
        let v1 = VersionId(id16(11));
        let v2 = VersionId(id16(12));
        let op2 = OperationId(id16(14));

        let mut store = SqliteObjectStore::open(&db_path).unwrap();
        store
            .commit(
                &chunks,
                commit_cmd(
                    object,
                    v1,
                    OperationId(id16(13)),
                    vec![],
                    BTreeSet::new(),
                    chunk.clone(),
                    13,
                ),
            )
            .unwrap();

        let cmd2 = commit_cmd(object, v2, op2, vec![v1], set(&[v1]), chunk.clone(), 14);
        store.set_failpoint_for_test(point);
        assert_eq!(
            store.commit(&chunks, cmd2.clone()),
            Err(CommitError::StorageUnavailable),
            "point={point:?}"
        );
        drop(store);

        let mut reopened = SqliteObjectStore::open(&db_path).unwrap();
        if point == StorageFailPoint::MetadataAfterCommitBeforeReply {
            assert_eq!(reopened.heads(object).unwrap(), set(&[v2]));
            let prior = reopened.operation(op2).unwrap().unwrap();
            let retry = reopened.commit(&chunks, cmd2).unwrap();
            assert_eq!(retry, prior);
            assert!(reopened.version(v2).is_ok());

            let ledger_count: i64 = reopened
                .connection()
                .query_row("SELECT COUNT(*) FROM commit_ledger", [], |row| row.get(0))
                .unwrap();
            assert_eq!(ledger_count, 2);
        } else {
            assert_eq!(reopened.heads(object).unwrap(), set(&[v1]));
            assert_eq!(reopened.operation(op2).unwrap(), None);
            assert_eq!(reopened.version(v2), Err(ReadError::NotFound));
        }
    }
}
