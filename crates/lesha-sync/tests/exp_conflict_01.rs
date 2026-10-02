use std::collections::{BTreeMap, BTreeSet};

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, CommitConsistency, CommitError, ImportError, ImportPort,
    LocalStorageImportAdapter, ObjectCommitPort, ObjectVersionManifest, ValidatedImportedVersion,
    ValidatedManifest, ValidatedObjectCommit,
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
    fake_wall_clock: i64,
}

impl VersionFixture {
    fn new(tag: u8, object_id: ObjectId, parents: Vec<VersionId>, fake_wall_clock: i64) -> Self {
        let bytes = format!("branch-v{tag}").into_bytes();
        let descriptor = descriptor(&bytes);
        Self {
            object_id,
            version_id: VersionId([tag; 16]),
            operation_id: OperationId([tag.wrapping_add(100); 16]),
            parents,
            bytes,
            descriptor,
            manifest_hash: ManifestHash([tag; 32]),
            request_hash: [tag.wrapping_add(50); 32],
            fake_wall_clock,
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

fn import_branch(
    chunks: &mut MemoryChunkStore,
    objects: &mut MemoryObjectStore,
    fixture: &VersionFixture,
) -> Result<(), ImportError> {
    let expected_heads = objects.heads(fixture.object_id).unwrap();
    let command = fixture.command(expected_heads, CommitConsistency::MergeableBranch);
    let mut import = LocalStorageImportAdapter::new(chunks, objects);
    import.stage_verified_chunk(&fixture.bytes, &fixture.descriptor)?;
    import.import_version(ValidatedImportedVersion::new_prevalidated(command))?;
    Ok(())
}

fn graph(
    objects: &MemoryObjectStore,
    versions: &[VersionId],
) -> BTreeMap<VersionId, Vec<VersionId>> {
    versions
        .iter()
        .copied()
        .map(|version_id| {
            let stored = objects.version(version_id).unwrap();
            let mut parents = stored.manifest.semantic.parents;
            parents.sort();
            (version_id, parents)
        })
        .collect()
}

#[test]
fn exp_conflict_01_concurrent_branches_converge_without_lww() {
    let object = ObjectId([9; 16]);
    let v1 = VersionFixture::new(10, object, vec![], 1_000);
    let v2a = VersionFixture::new(20, object, vec![v1.version_id], 2_000);
    let v3a = VersionFixture::new(21, object, vec![v2a.version_id], 3_000);
    let v2b = VersionFixture::new(30, object, vec![v1.version_id], 99_000);

    // B intentionally looks much newer by wall clock. The storage/sync substrate
    // has no LWW path and therefore cannot use this as a canonical winner.
    assert!(v2b.fake_wall_clock > v3a.fake_wall_clock);

    let mut chunks_a = MemoryChunkStore::default();
    let mut objects_a = MemoryObjectStore::default();
    import_branch(&mut chunks_a, &mut objects_a, &v1).unwrap();

    let mut chunks_b = MemoryChunkStore::default();
    let mut objects_b = MemoryObjectStore::default();
    import_branch(&mut chunks_b, &mut objects_b, &v1).unwrap();

    // Partition: A advances two causal steps, B advances a concurrent branch.
    import_branch(&mut chunks_a, &mut objects_a, &v2a).unwrap();
    import_branch(&mut chunks_a, &mut objects_a, &v3a).unwrap();
    import_branch(&mut chunks_b, &mut objects_b, &v2b).unwrap();

    assert_eq!(
        objects_a.heads(object).unwrap(),
        BTreeSet::from([v3a.version_id])
    );
    assert_eq!(
        objects_b.heads(object).unwrap(),
        BTreeSet::from([v2b.version_id])
    );

    // Reconnect. A receives B branch; B receives A causal chain.
    import_branch(&mut chunks_a, &mut objects_a, &v2b).unwrap();
    import_branch(&mut chunks_b, &mut objects_b, &v2a).unwrap();
    import_branch(&mut chunks_b, &mut objects_b, &v3a).unwrap();

    let expected_heads = BTreeSet::from([v3a.version_id, v2b.version_id]);
    assert_eq!(objects_a.heads(object).unwrap(), expected_heads);
    assert_eq!(objects_b.heads(object).unwrap(), expected_heads);

    let all_versions = [v1.version_id, v2a.version_id, v3a.version_id, v2b.version_id];
    assert_eq!(graph(&objects_a, &all_versions), graph(&objects_b, &all_versions));
    assert_eq!(objects_a.rebuild_heads().unwrap(), objects_b.rebuild_heads().unwrap());

    // Two fresh receivers observe different valid transport orders. Both end
    // with the same causal graph/head-set even though their local ledger order differs.
    let mut chunks_c = MemoryChunkStore::default();
    let mut objects_c = MemoryObjectStore::default();
    for version in [&v1, &v2a, &v3a, &v2b] {
        import_branch(&mut chunks_c, &mut objects_c, version).unwrap();
    }

    let mut chunks_d = MemoryChunkStore::default();
    let mut objects_d = MemoryObjectStore::default();
    for version in [&v1, &v2b, &v2a, &v3a] {
        import_branch(&mut chunks_d, &mut objects_d, version).unwrap();
    }

    assert_eq!(objects_c.heads(object).unwrap(), expected_heads);
    assert_eq!(objects_d.heads(object).unwrap(), expected_heads);
    assert_eq!(graph(&objects_c, &all_versions), graph(&objects_d, &all_versions));
}

#[test]
fn causal_child_cannot_arrive_before_missing_parent_and_advance_heads() {
    let object = ObjectId([9; 16]);
    let v1 = VersionFixture::new(10, object, vec![], 1_000);
    let v2a = VersionFixture::new(20, object, vec![v1.version_id], 2_000);
    let v3a = VersionFixture::new(21, object, vec![v2a.version_id], 3_000);

    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();
    import_branch(&mut chunks, &mut objects, &v1).unwrap();
    let before = objects.heads(object).unwrap();

    assert_eq!(
        import_branch(&mut chunks, &mut objects, &v3a),
        Err(ImportError::Commit(CommitError::ParentMissing(v2a.version_id)))
    );
    assert_eq!(objects.heads(object).unwrap(), before);
    assert!(objects.version(v3a.version_id).is_err());

    import_branch(&mut chunks, &mut objects, &v2a).unwrap();
    import_branch(&mut chunks, &mut objects, &v3a).unwrap();
    assert_eq!(
        objects.heads(object).unwrap(),
        BTreeSet::from([v3a.version_id])
    );
}
