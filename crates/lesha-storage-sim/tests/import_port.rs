use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, ChunkStoreError, CommitConsistency, CommitError,
    ImportError, ImportPort, LocalStorageImportAdapter, ObjectCommitPort, ObjectVersionManifest,
    ValidatedImportedVersion, ValidatedManifest, ValidatedObjectCommit,
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

fn descriptor(bytes: &[u8]) -> ChunkDescriptor {
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    }
}

fn commit_cmd(
    object: ObjectId,
    version: VersionId,
    operation: OperationId,
    chunk: ChunkDescriptor,
) -> ValidatedObjectCommit {
    let mut cbor = vec![0xa2, 0x01, 0x50];
    cbor.extend_from_slice(&version.0);
    cbor.extend_from_slice(&[0x02, 0x50]);
    cbor.extend_from_slice(&object.0);

    ValidatedObjectCommit {
        manifest: ValidatedManifest::new_prevalidated(
            ObjectVersionManifest {
                cluster_id: ClusterId(id16(1)),
                object_id: object,
                version_id: version,
                operation_id: operation,
                parents: vec![],
                authority_epoch: AuthorityEpoch(1),
                control_frontier: ControlFrontierHash(hash32(2)),
                chunks: vec![ChunkRef {
                    ordinal: 0,
                    role: ChunkRole::Payload,
                    descriptor: chunk,
                }],
            },
            CanonicalAuthorityBytes::validate(cbor).unwrap(),
            ManifestHash(hash32(3)),
        ),
        request_hash: hash32(4),
        expected_heads: BTreeSet::new(),
        consistency: CommitConsistency::StrictSingleHead,
    }
}

#[test]
fn import_port_stages_chunk_then_commits_through_object_port() {
    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();

    let bytes = b"verified-ciphertext";
    let chunk = descriptor(bytes);
    let object = ObjectId(id16(10));
    let version = VersionId(id16(11));
    let command = commit_cmd(object, version, OperationId(id16(12)), chunk.clone());

    let first = {
        let mut import = LocalStorageImportAdapter::new(&mut chunks, &mut objects);
        let staged = import.stage_verified_chunk(bytes, &chunk).unwrap();
        assert_eq!(staged.descriptor, chunk);

        let first = import
            .import_version(ValidatedImportedVersion::new_prevalidated(command.clone()))
            .unwrap();
        let retry = import
            .import_version(ValidatedImportedVersion::new_prevalidated(command))
            .unwrap();
        assert_eq!(retry, first);
        first
    };

    assert_eq!(first.commit.version_id, version);
    assert_eq!(
        objects.heads(object).unwrap(),
        BTreeSet::from([version])
    );
}

#[test]
fn import_port_cannot_commit_version_before_required_chunk_is_staged() {
    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();

    let bytes = b"missing-ciphertext";
    let chunk = descriptor(bytes);
    let version = VersionId(id16(21));
    let command = commit_cmd(
        ObjectId(id16(20)),
        version,
        OperationId(id16(22)),
        chunk.clone(),
    );

    let mut import = LocalStorageImportAdapter::new(&mut chunks, &mut objects);
    assert_eq!(
        import.import_version(ValidatedImportedVersion::new_prevalidated(command)),
        Err(ImportError::Commit(CommitError::MissingChunk(
            chunk.chunk_id
        )))
    );
}

#[test]
fn import_port_revalidates_staged_chunk_descriptor() {
    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();

    let bytes = b"verified-ciphertext";
    let mut wrong = descriptor(bytes);
    wrong.ciphertext_len += 1;

    let mut import = LocalStorageImportAdapter::new(&mut chunks, &mut objects);
    assert_eq!(
        import.stage_verified_chunk(bytes, &wrong),
        Err(ImportError::Chunk(ChunkStoreError::DescriptorMismatch))
    );
}
