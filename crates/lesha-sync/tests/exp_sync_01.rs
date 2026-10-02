use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_storage_core::{
    ChunkDescriptor, ChunkRef, ChunkRole, CommitConsistency, ImportPort, LocalStorageImportAdapter,
    ObjectCommitPort, ObjectVersionManifest, ValidatedImportedVersion, ValidatedManifest,
    ValidatedObjectCommit,
};
use lesha_storage_memory::{MemoryChunkStore, MemoryObjectStore};
use lesha_sync::{
    CheckpointRef, ControlContext, DeltaAccept, DeltaChainValidator, DeltaEnvelopeHeader,
    DeltaValidationError, NamespaceSummary, ReceiverPosition, SyncSession, SyncState,
};
use lesha_types::{
    AuthorityEpoch, CheckpointId, ChunkId, ClusterId, ControlFrontierHash, DeltaHash, ManifestHash,
    NamespaceId, ObjectId, OperationId, ProducerSequence, VersionId,
};
use sha2::{Digest, Sha256};

#[derive(Clone)]
struct DeltaFixture {
    header: DeltaEnvelopeHeader,
    bytes: Vec<u8>,
    descriptor: ChunkDescriptor,
    version: ValidatedImportedVersion,
}

fn id16(tag: u8) -> [u8; 16] {
    [tag; 16]
}

fn hash32(tag: u8) -> [u8; 32] {
    [tag; 32]
}

fn ns() -> NamespaceId {
    NamespaceId(id16(1))
}

fn control() -> ControlContext {
    ControlContext {
        epoch: 7,
        frontier_hash: ControlFrontierHash(hash32(7)),
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

fn version(
    tag: u8,
    object: ObjectId,
    parent: Option<VersionId>,
    expected_heads: BTreeSet<VersionId>,
    descriptor: ChunkDescriptor,
) -> ValidatedImportedVersion {
    let version_id = VersionId(id16(tag));
    let operation_id = OperationId(id16(tag.wrapping_add(40)));

    let mut canonical = vec![0x82, 0x01, 0x50];
    canonical.extend_from_slice(&version_id.0);
    let canonical = CanonicalAuthorityBytes::validate(canonical).unwrap();

    ValidatedImportedVersion::new_prevalidated(ValidatedObjectCommit {
        manifest: ValidatedManifest::new_prevalidated(
            ObjectVersionManifest {
                cluster_id: ClusterId(id16(2)),
                object_id: object,
                version_id,
                operation_id,
                parents: parent.into_iter().collect(),
                authority_epoch: AuthorityEpoch(1),
                control_frontier: control().frontier_hash,
                chunks: vec![ChunkRef {
                    ordinal: 0,
                    role: ChunkRole::Payload,
                    descriptor,
                }],
            },
            canonical,
            ManifestHash(hash32(tag)),
        ),
        request_hash: hash32(tag.wrapping_add(80)),
        expected_heads,
        consistency: CommitConsistency::StrictSingleHead,
    })
}

fn fixtures() -> [DeltaFixture; 3] {
    let object = ObjectId(id16(9));

    let bytes1 = b"sync-v1".to_vec();
    let d1 = descriptor(&bytes1);
    let v1 = VersionId(id16(11));

    let bytes2 = b"sync-v2".to_vec();
    let d2 = descriptor(&bytes2);
    let v2 = VersionId(id16(12));

    let bytes3 = b"sync-v3".to_vec();
    let d3 = descriptor(&bytes3);

    [
        DeltaFixture {
            header: DeltaEnvelopeHeader {
                sequence: ProducerSequence(1),
                previous_delta_hash: None,
                envelope_hash: DeltaHash(hash32(1)),
            },
            bytes: bytes1,
            descriptor: d1.clone(),
            version: version(11, object, None, BTreeSet::new(), d1),
        },
        DeltaFixture {
            header: DeltaEnvelopeHeader {
                sequence: ProducerSequence(2),
                previous_delta_hash: Some(DeltaHash(hash32(1))),
                envelope_hash: DeltaHash(hash32(2)),
            },
            bytes: bytes2,
            descriptor: d2.clone(),
            version: version(12, object, Some(v1), BTreeSet::from([v1]), d2),
        },
        DeltaFixture {
            header: DeltaEnvelopeHeader {
                sequence: ProducerSequence(3),
                previous_delta_hash: Some(DeltaHash(hash32(2))),
                envelope_hash: DeltaHash(hash32(3)),
            },
            bytes: bytes3,
            descriptor: d3.clone(),
            version: version(13, object, Some(v2), BTreeSet::from([v2]), d3),
        },
    ]
}

fn sender_summary() -> NamespaceSummary {
    NamespaceSummary {
        namespace_id: ns(),
        checkpoint: Some(CheckpointRef {
            checkpoint_id: CheckpointId(hash32(21)),
            producer_sequence_head: ProducerSequence(1),
            producer_delta_hash: Some(DeltaHash(hash32(1))),
        }),
        delta_floor: Some(ProducerSequence(2)),
        delta_head: Some(ProducerSequence(3)),
        bucket_root_set_hash: hash32(31),
        control: control(),
    }
}

fn receiver_position(last_applied: Option<u64>) -> ReceiverPosition {
    ReceiverPosition {
        namespace_id: ns(),
        last_applied: last_applied.map(ProducerSequence),
        control: control(),
    }
}

fn import_fixture(
    chunks: &mut MemoryChunkStore,
    objects: &mut MemoryObjectStore,
    fixture: &DeltaFixture,
) {
    let mut import = LocalStorageImportAdapter::new(chunks, objects);
    import
        .stage_verified_chunk(&fixture.bytes, &fixture.descriptor)
        .unwrap();
    import.import_version(fixture.version.clone()).unwrap();
}

fn build_sender(fixtures: &[DeltaFixture; 3]) -> (MemoryChunkStore, MemoryObjectStore) {
    let mut chunks = MemoryChunkStore::default();
    let mut objects = MemoryObjectStore::default();
    for fixture in fixtures {
        import_fixture(&mut chunks, &mut objects, fixture);
    }
    (chunks, objects)
}

fn apply_delta(
    validator: &mut DeltaChainValidator,
    session: &mut SyncSession,
    chunks: &mut MemoryChunkStore,
    objects: &mut MemoryObjectStore,
    fixture: &DeltaFixture,
) {
    assert_eq!(
        validator.accept(fixture.header),
        Ok(DeltaAccept::Applied {
            new_head: fixture.header.sequence
        })
    );
    import_fixture(chunks, objects, fixture);
    session.delta_applied(fixture.header.sequence).unwrap();
}

#[test]
fn short_absence_incremental_converges_exactly_and_duplicate_is_idempotent() {
    let fixtures = fixtures();
    let (_, sender_objects) = build_sender(&fixtures);

    let mut receiver_chunks = MemoryChunkStore::default();
    let mut receiver_objects = MemoryObjectStore::default();
    import_fixture(&mut receiver_chunks, &mut receiver_objects, &fixtures[0]);

    let mut session = SyncSession::new(ns());
    session.authenticated().unwrap();
    session
        .negotiate(&sender_summary(), &receiver_position(Some(1)))
        .unwrap();

    let mut validator =
        DeltaChainValidator::new(Some(ProducerSequence(1)), Some(DeltaHash(hash32(1))), 8).unwrap();

    apply_delta(
        &mut validator,
        &mut session,
        &mut receiver_chunks,
        &mut receiver_objects,
        &fixtures[1],
    );

    assert_eq!(
        validator.accept(fixtures[1].header),
        Ok(DeltaAccept::Duplicate {
            sequence: ProducerSequence(2)
        })
    );

    apply_delta(
        &mut validator,
        &mut session,
        &mut receiver_chunks,
        &mut receiver_objects,
        &fixtures[2],
    );
    session.verification_complete().unwrap();

    assert_eq!(
        session.state(),
        SyncState::CaughtUp {
            at: Some(ProducerSequence(3))
        }
    );
    assert_eq!(
        receiver_objects.heads(ObjectId(id16(9))).unwrap(),
        sender_objects.heads(ObjectId(id16(9))).unwrap()
    );
    assert_eq!(receiver_objects.snapshot().versions.len(), 3);
}

#[test]
fn stale_peer_uses_checkpoint_then_tail_and_converges() {
    let fixtures = fixtures();
    let (_, sender_objects) = build_sender(&fixtures);

    let mut receiver_chunks = MemoryChunkStore::default();
    let mut receiver_objects = MemoryObjectStore::default();

    let mut session = SyncSession::new(ns());
    session.authenticated().unwrap();
    session
        .negotiate(&sender_summary(), &receiver_position(None))
        .unwrap();
    assert!(matches!(
        session.state(),
        SyncState::InitialCheckpoint { .. }
    ));

    import_fixture(&mut receiver_chunks, &mut receiver_objects, &fixtures[0]);
    session
        .checkpoint_applied(CheckpointId(hash32(21)))
        .unwrap();

    let mut validator =
        DeltaChainValidator::new(Some(ProducerSequence(1)), Some(DeltaHash(hash32(1))), 8).unwrap();

    for fixture in &fixtures[1..] {
        apply_delta(
            &mut validator,
            &mut session,
            &mut receiver_chunks,
            &mut receiver_objects,
            fixture,
        );
    }
    session.verification_complete().unwrap();

    assert_eq!(
        receiver_objects.heads(ObjectId(id16(9))).unwrap(),
        sender_objects.heads(ObjectId(id16(9))).unwrap()
    );
    assert_eq!(receiver_objects.snapshot().versions.len(), 3);
}

#[test]
fn shuffled_or_missing_delta_never_advances_canonical_state() {
    let fixtures = fixtures();

    let mut receiver_chunks = MemoryChunkStore::default();
    let mut receiver_objects = MemoryObjectStore::default();
    import_fixture(&mut receiver_chunks, &mut receiver_objects, &fixtures[0]);

    let mut session = SyncSession::new(ns());
    session.authenticated().unwrap();
    session
        .negotiate(&sender_summary(), &receiver_position(Some(1)))
        .unwrap();
    let before_session = session.state();
    let before_heads = receiver_objects.heads(ObjectId(id16(9))).unwrap();

    let mut validator =
        DeltaChainValidator::new(Some(ProducerSequence(1)), Some(DeltaHash(hash32(1))), 8).unwrap();

    assert_eq!(
        validator.accept(fixtures[2].header),
        Err(DeltaValidationError::GapDetected {
            expected: ProducerSequence(2),
            received: ProducerSequence(3)
        })
    );
    assert_eq!(validator.last_sequence(), Some(ProducerSequence(1)));
    assert_eq!(session.state(), before_session);
    assert_eq!(
        receiver_objects.heads(ObjectId(id16(9))).unwrap(),
        before_heads
    );

    apply_delta(
        &mut validator,
        &mut session,
        &mut receiver_chunks,
        &mut receiver_objects,
        &fixtures[1],
    );
    apply_delta(
        &mut validator,
        &mut session,
        &mut receiver_chunks,
        &mut receiver_objects,
        &fixtures[2],
    );
    session.verification_complete().unwrap();

    assert_eq!(
        session.state(),
        SyncState::CaughtUp {
            at: Some(ProducerSequence(3))
        }
    );
}
