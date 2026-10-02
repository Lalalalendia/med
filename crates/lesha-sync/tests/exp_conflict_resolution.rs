use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, CommitConsistency, CommitError, ImportError, ImportPort,
    ImportReceipt, LocalStorageImportAdapter, ObjectCommitPort, ObjectVersionManifest,
    ValidatedImportedVersion, ValidatedManifest, ValidatedObjectCommit,
};
use lesha_storage_memory::{MemoryChunkStore, MemoryObjectStore};
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, ControlFrontierHash, ManifestHash, ObjectId, OperationId,
    VersionId,
};
use sha2::{Digest, Sha256};

#[derive(Clone)]
struct VersionFixture {
    object_id: ObjectId,
    version_id: VersionId,
    operation_id: OperationId,
    parents: Vec<VersionId>,
    bytes: Vec<u8>,
    descriptor: ChunkDescriptor,
    manifest_hash: ManifestHash,
    request_hash: [u8; 32],
}

impl VersionFixture {
    fn new(tag: u8, object_id: ObjectId, parents: Vec<VersionId>, bytes: &[u8]) -> Self {
        Self {
            object_id,
            version_id: VersionId([tag; 16]),
            operation_id: OperationId([tag.wrapping_add(100); 16]),
            parents,
            bytes: bytes.to_vec(),
            descriptor: descriptor(bytes),
            manifest_hash: ManifestHash([tag; 32]),
            request_hash: [tag.wrapping_add(50); 32],
        }
    }

    fn command(
        &self,
        expected_heads: BTreeSet<VersionId>,
        consistency: CommitConsistency,
    ) -> ValidatedObjectCommit {
        let mut canonical = vec![0x82, 0x01, 0x50];
        canonical.extend_from_slice(&self.version_id.0);
        let canonical = CanonicalAuthorityBytes::validate(canonical).unwrap();

        ValidatedObjectCommit {
            manifest: ValidatedManifest::new_prevalidated(
                ObjectVersionManifest {
                    cluster_id: ClusterId([1; 16]),
                    object_id: self.object_id,
                    version_id: self.version_id,
                    operation_id: self.operation_id,
                    parents: self.parents.clone(),
                    authority_epoch: AuthorityEpoch(1),
                    control_frontier: ControlFrontierHash([7; 32]),
                    chunks: vec![ChunkRef {
                        ordinal: 0,
                        role: ChunkRole::Payload,
                        descriptor: self.descriptor.clone(),
                    }],
                },
                canonical,
                self.manifest_hash,
            ),
            request_hash: self.request_hash,
            expected_heads,
            consistency,
        }
    }
}

fn descriptor(bytes: &[u8]) -> ChunkDescriptor {
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    }
}

fn import_with(
    chunks: &mut MemoryChunkStore,
    objects: &mut MemoryObjectStore,
    fixture: &VersionFixture,
    expected_heads: BTreeSet<VersionId>,
    consistency: CommitConsistency,
) -> Result<ImportReceipt, ImportError> {
    let command = fixture.command(expected_heads, consistency);
    let mut import = LocalStorageImportAdapter::new(chunks, objects);
    import.stage_verified_chunk(&fixture.bytes, &fixture.descriptor)?;
    import.import_version(ValidatedImportedVersion::new_prevalidated(command))
}

fn import_branch(
    chunks: &mut MemoryChunkStore,
    objects: &mut MemoryObjectStore,
    fixture: &VersionFixture,
) -> Result<ImportReceipt, ImportError> {
    let expected_heads = objects.heads(fixture.object_id).unwrap();
    import_with(
        chunks,
        objects,
        fixture,
        expected_heads,
        CommitConsistency::MergeableBranch,
    )
}

fn divergent_fixture(
) -> (
    ObjectId,
    VersionFixture,
    VersionFixture,
    VersionFixture,
    VersionFixture,
    MemoryChunkStore,
    MemoryObjectStore,
) {
    let object = ObjectId([9; 16]);
    let v1 = VersionFixture::new(10, object, vec![], b"v1");
    let v2a = VersionFixture::new(20, object, vec![v1.version_id], b"v2a");
    let v3a = VersionFixture::new(21, object, vec![v2a.version_id], b"v3a");
    let v2b = VersionFixture::new(30, object, vec![v1.version_id], b"v2b");

    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();
    for version in [&v1, &v2a, &v3a, &v2b] {
        import_branch(&mut chunks, &mut objects, version).unwrap();
    }

    assert_eq!(
        objects.heads(object).unwrap(),
        BTreeSet::from([v3a.version_id, v2b.version_id])
    );

    (object, v1, v2a, v3a, v2b, chunks, objects)
}

#[test]
fn exact_manual_resolution_creates_child_of_all_reviewed_heads_and_is_idempotent() {
    let (object, _v1, _v2a, v3a, v2b, mut chunks, mut objects) = divergent_fixture();
    let reviewed_heads = objects.heads(object).unwrap();

    let mut parents = vec![v3a.version_id, v2b.version_id];
    parents.sort();
    let v4 = VersionFixture::new(40, object, parents.clone(), b"resolved-v4");
    let command = v4.command(reviewed_heads.clone(), CommitConsistency::MergeResolution);

    let first = {
        let mut import = LocalStorageImportAdapter::new(&mut chunks, &mut objects);
        import
            .stage_verified_chunk(&v4.bytes, &v4.descriptor)
            .unwrap();
        import
            .import_version(ValidatedImportedVersion::new_prevalidated(command.clone()))
            .unwrap()
    };
    let ledger_len_after_first = objects.snapshot().ledger.len();

    assert_eq!(
        objects.heads(object).unwrap(),
        BTreeSet::from([v4.version_id])
    );
    let stored = objects.version(v4.version_id).unwrap();
    let mut stored_parents = stored.manifest.semantic.parents;
    stored_parents.sort();
    assert_eq!(stored_parents, parents);

    // Lost ACK / exact retry: same operation produces the prior receipt and no
    // second ledger event, even though the current head-set is now {V4}.
    let retry = {
        let mut import = LocalStorageImportAdapter::new(&mut chunks, &mut objects);
        import
            .stage_verified_chunk(&v4.bytes, &v4.descriptor)
            .unwrap();
        import
            .import_version(ValidatedImportedVersion::new_prevalidated(command))
            .unwrap()
    };

    assert_eq!(retry, first);
    assert_eq!(objects.snapshot().ledger.len(), ledger_len_after_first);
}

#[test]
fn manual_resolution_fails_if_a_new_head_arrives_after_review() {
    let (object, v1, _v2a, v3a, v2b, mut chunks, mut objects) = divergent_fixture();
    let reviewed_heads = objects.heads(object).unwrap();
    assert_eq!(
        reviewed_heads,
        BTreeSet::from([v3a.version_id, v2b.version_id])
    );

    // A third concurrent branch arrives while the user/domain service is reviewing.
    let v2c = VersionFixture::new(31, object, vec![v1.version_id], b"v2c");
    import_branch(&mut chunks, &mut objects, &v2c).unwrap();
    let actual_heads = objects.heads(object).unwrap();
    assert_eq!(
        actual_heads,
        BTreeSet::from([v3a.version_id, v2b.version_id, v2c.version_id])
    );

    let mut reviewed_parents: Vec<_> = reviewed_heads.iter().copied().collect();
    reviewed_parents.sort();
    let stale_resolution = VersionFixture::new(40, object, reviewed_parents, b"stale-resolution");

    assert_eq!(
        import_with(
            &mut chunks,
            &mut objects,
            &stale_resolution,
            reviewed_heads.clone(),
            CommitConsistency::MergeResolution,
        ),
        Err(ImportError::Commit(CommitError::HeadSetChanged {
            expected: reviewed_heads,
            actual: actual_heads.clone(),
        }))
    );
    assert_eq!(objects.heads(object).unwrap(), actual_heads);
    assert!(objects.version(stale_resolution.version_id).is_err());
}

#[test]
fn tombstone_is_an_explicit_concurrent_version_not_peer_absence() {
    let object = ObjectId([9; 16]);
    let v1 = VersionFixture::new(10, object, vec![], b"v1");
    let update = VersionFixture::new(20, object, vec![v1.version_id], b"ordinary-update");
    let tombstone = VersionFixture::new(
        30,
        object,
        vec![v1.version_id],
        b"LESHA_TEST_TOMBSTONE:explicit",
    );

    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();
    import_branch(&mut chunks, &mut objects, &v1).unwrap();
    import_branch(&mut chunks, &mut objects, &update).unwrap();
    import_branch(&mut chunks, &mut objects, &tombstone).unwrap();

    assert_eq!(
        objects.heads(object).unwrap(),
        BTreeSet::from([update.version_id, tombstone.version_id])
    );
    assert_eq!(
        objects
            .version(tombstone.version_id)
            .unwrap()
            .manifest
            .semantic
            .parents,
        vec![v1.version_id]
    );

    // In a peer that never received a tombstone version, mere absence of that
    // branch does not synthesize a deletion.
    let mut chunks_without_delete = MemoryChunkStore::default();
    let mut objects_without_delete = MemoryObjectStore::default();
    import_branch(&mut chunks_without_delete, &mut objects_without_delete, &v1).unwrap();
    import_branch(
        &mut chunks_without_delete,
        &mut objects_without_delete,
        &update,
    )
    .unwrap();
    assert_eq!(
        objects_without_delete.heads(object).unwrap(),
        BTreeSet::from([update.version_id])
    );
    assert!(objects_without_delete.version(tombstone.version_id).is_err());
}
