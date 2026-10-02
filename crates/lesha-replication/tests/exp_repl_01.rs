use std::collections::BTreeSet;

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_replication::{
    evaluate_protection, plan_repairs, DurabilityEligibility, FailureDomainId,
    HealthEvidenceSequence, ProtectedSubject, ProtectionState, ReceiptHealth, ReceiptId,
    RepairCandidate, RepairCandidateState, RepairPlanState, ReplicaEvidence,
    ReplicaHealthObservation, ReplicaHealthObservationKind, ReplicaHealthTracker,
    ReplicaPlacementPolicy, ReplicaSubject, ReplicaTopology, VerifiedReplicaReceipt,
};
use lesha_storage_core::{
    ChunkAvailability, ChunkDescriptor, ChunkHealth, ChunkRef, ChunkRole, ChunkStorePort,
    CommitConsistency, ObjectCommitPort, ObjectVersionManifest, ValidatedManifest,
    ValidatedObjectCommit,
};
use lesha_storage_memory::{MemoryChunkStore, MemoryObjectStore};
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, ControlFrontierHash, ManifestHash, NodeGeneration, NodeId,
    NodeRef, ObjectId, OperationId, VersionId,
};
use sha2::{Digest, Sha256};

fn id16(tag: u8) -> [u8; 16] {
    [tag; 16]
}

fn hash32(tag: u8) -> [u8; 32] {
    [tag; 32]
}

fn node(tag: u8) -> NodeRef {
    NodeRef {
        cluster_id: ClusterId(id16(1)),
        node_id: NodeId([tag; 32]),
        generation: NodeGeneration(1),
    }
}

fn domain(tag: u8) -> FailureDomainId {
    FailureDomainId(id16(tag))
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

fn commit(
    tag: u8,
    object: ObjectId,
    parent: Option<VersionId>,
    expected_heads: BTreeSet<VersionId>,
    chunk: ChunkDescriptor,
) -> ValidatedObjectCommit {
    let version_id = VersionId(id16(tag));
    let operation_id = OperationId(id16(tag.wrapping_add(40)));
    let mut canonical = vec![0x82, 0x01, 0x50];
    canonical.extend_from_slice(&version_id.0);
    let canonical = CanonicalAuthorityBytes::validate(canonical).unwrap();

    ValidatedObjectCommit {
        manifest: ValidatedManifest::new_prevalidated(
            ObjectVersionManifest {
                cluster_id: ClusterId(id16(1)),
                object_id: object,
                version_id,
                operation_id,
                parents: parent.into_iter().collect(),
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
        request_hash: hash32(tag.wrapping_add(80)),
        expected_heads,
        consistency: CommitConsistency::StrictSingleHead,
    }
}

fn receipt(
    tag: u8,
    destination: NodeRef,
    target: ProtectedSubject,
    storage_generation: u64,
) -> VerifiedReplicaReceipt {
    VerifiedReplicaReceipt::new_prevalidated(
        ReceiptId(id16(tag)),
        target.cluster_id,
        destination,
        target.subject,
        target.subject_hash,
        storage_generation,
    )
}

fn evidence(
    tag: u8,
    host: u8,
    target: ProtectedSubject,
    health: ReceiptHealth,
    storage_generation: u64,
) -> ReplicaEvidence {
    let destination = node(tag);
    ReplicaEvidence {
        node: destination,
        receipts: vec![receipt(tag, destination, target, storage_generation)],
        receipt_health: health,
        eligibility: DurabilityEligibility::CountsForDurability,
        topology: ReplicaTopology {
            host: Some(domain(host)),
            storage_device: Some(domain(tag.wrapping_add(20))),
            site: None,
            power: None,
        },
        is_anchor: tag == 3 || tag == 4,
    }
}

fn candidate(tag: u8, host: u8) -> RepairCandidate {
    RepairCandidate {
        node: node(tag),
        eligibility: DurabilityEligibility::CountsForDurability,
        topology: ReplicaTopology {
            host: Some(domain(host)),
            storage_device: Some(domain(tag.wrapping_add(20))),
            site: None,
            power: None,
        },
        is_anchor: tag == 3 || tag == 4,
        state: RepairCandidateState::Available,
    }
}

fn set_health(evidence: &mut [ReplicaEvidence], node_id: NodeId, health: ReceiptHealth) {
    evidence
        .iter_mut()
        .find(|item| item.node.node_id == node_id)
        .unwrap()
        .receipt_health = health;
}

#[test]
fn exp_repl_01_three_node_loss_corruption_and_repair() {
    let object = ObjectId(id16(9));
    let v1 = VersionId(id16(11));
    let v2 = VersionId(id16(12));
    let bytes_v1 = b"semantic-v1";
    let bytes_v2 = b"semantic-v2";
    let d1 = descriptor(bytes_v1);
    let d2 = descriptor(bytes_v2);

    let mut semantic_chunks = MemoryChunkStore::default();
    let mut semantic_objects = MemoryObjectStore::default();
    semantic_chunks.put_durable(bytes_v1, &d1).unwrap();
    semantic_objects
        .commit(
            &semantic_chunks,
            commit(11, object, None, BTreeSet::new(), d1.clone()),
        )
        .unwrap();
    semantic_chunks.put_durable(bytes_v2, &d2).unwrap();
    semantic_objects
        .commit(
            &semantic_chunks,
            commit(12, object, Some(v1), BTreeSet::from([v1]), d2.clone()),
        )
        .unwrap();
    assert_eq!(
        semantic_objects.heads(object).unwrap(),
        BTreeSet::from([v2])
    );
    let semantic_before_repair = semantic_objects.snapshot();

    let target = ProtectedSubject {
        cluster_id: ClusterId(id16(1)),
        subject: ReplicaSubject::Chunk(d2.chunk_id),
        subject_hash: d2.chunk_id.0,
    };
    let policy = ReplicaPlacementPolicy {
        full_replica_count: 3,
        min_distinct_hosts: 3,
        min_distinct_storage_devices: 3,
        min_distinct_sites: 0,
        min_distinct_power_domains: 0,
        min_anchor_replicas: 1,
    };

    let mut store_a = MemoryChunkStore::default();
    let mut store_b = MemoryChunkStore::default();
    let mut store_c = MemoryChunkStore::default();
    let mut store_d = MemoryChunkStore::default();
    for store in [&mut store_a, &mut store_b, &mut store_c] {
        store.put_durable(bytes_v2, &d2).unwrap();
    }

    let mut replicas = vec![
        evidence(1, 1, target, ReceiptHealth::CurrentVerified, 1),
        evidence(2, 2, target, ReceiptHealth::CurrentVerified, 1),
        evidence(3, 3, target, ReceiptHealth::CurrentVerified, 1),
    ];

    let initial = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(initial.state, ProtectionState::Replicated);
    assert_eq!(initial.verified_replicas, 3);
    assert_eq!(initial.distinct_hosts, 3);

    set_health(&mut replicas, node(1).node_id, ReceiptHealth::Missing);
    let after_a_loss = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(
        after_a_loss.state,
        ProtectionState::DegradedPolicyUnsatisfied
    );
    assert_eq!(after_a_loss.verified_replicas, 2);

    let plan_d = plan_repairs(&target, policy, &replicas, &[candidate(4, 4)], 1).unwrap();
    assert_eq!(plan_d.state, RepairPlanState::Complete);
    assert_eq!(plan_d.targets[0].node.node_id, node(4).node_id);

    let healthy_bytes = store_c.read_verified(d2.chunk_id).unwrap();
    store_d.put_durable(&healthy_bytes, &d2).unwrap();
    assert_eq!(
        store_d.chunk_health(d2.chunk_id).unwrap(),
        ChunkHealth::Healthy
    );

    let before_receipt = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(before_receipt.verified_replicas, 2);
    assert_eq!(
        before_receipt.state,
        ProtectionState::DegradedPolicyUnsatisfied
    );

    store_d.put_durable(&healthy_bytes, &d2).unwrap();
    replicas.push(evidence(4, 4, target, ReceiptHealth::CurrentVerified, 1));
    let after_d_receipt = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(after_d_receipt.state, ProtectionState::Replicated);
    assert_eq!(after_d_receipt.verified_replicas, 3);

    assert!(store_b.corrupt_for_test(d2.chunk_id));
    assert_eq!(
        store_b.chunk_health(d2.chunk_id).unwrap(),
        ChunkHealth::DigestMismatch
    );
    assert!(store_b.read_verified(d2.chunk_id).is_err());

    let mut b_health = ReplicaHealthTracker::new(node(2), 1);
    b_health
        .apply(ReplicaHealthObservation {
            node: node(2),
            storage_generation: 1,
            sequence: HealthEvidenceSequence(1),
            kind: ReplicaHealthObservationKind::VerifiedHealthy,
        })
        .unwrap();
    b_health
        .apply(ReplicaHealthObservation {
            node: node(2),
            storage_generation: 1,
            sequence: HealthEvidenceSequence(2),
            kind: ReplicaHealthObservationKind::DigestMismatch,
        })
        .unwrap();
    set_health(&mut replicas, node(2).node_id, b_health.health());

    let after_b_corruption = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(after_b_corruption.verified_replicas, 2);
    assert_eq!(
        after_b_corruption.state,
        ProtectionState::DegradedPolicyUnsatisfied
    );

    let plan_b = plan_repairs(&target, policy, &replicas, &[candidate(2, 2)], 1).unwrap();
    assert_eq!(plan_b.state, RepairPlanState::Complete);
    assert_eq!(plan_b.targets[0].node.node_id, node(2).node_id);

    let repair_source = store_c.read_verified(d2.chunk_id).unwrap();
    let mut repaired_b = MemoryChunkStore::default();
    repaired_b.put_durable(&repair_source, &d2).unwrap();
    assert_eq!(
        repaired_b.chunk_health(d2.chunk_id).unwrap(),
        ChunkHealth::Healthy
    );

    let b_entry = replicas
        .iter_mut()
        .find(|item| item.node.node_id == node(2).node_id)
        .unwrap();
    b_entry.receipts = vec![receipt(22, node(2), target, 2)];
    b_entry.receipt_health = ReceiptHealth::CurrentVerified;

    let after_b_repair = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(after_b_repair.state, ProtectionState::Replicated);
    assert_eq!(after_b_repair.verified_replicas, 3);

    let d_entry = replicas
        .iter_mut()
        .find(|item| item.node.node_id == node(4).node_id)
        .unwrap();
    d_entry.receipts.push(receipt(44, node(4), target, 1));
    let duplicate_receipt_status = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(duplicate_receipt_status.verified_replicas, 3);

    let mut correlated = replicas.clone();
    correlated
        .iter_mut()
        .find(|item| item.node.node_id == node(4).node_id)
        .unwrap()
        .topology
        .host = Some(domain(3));
    let correlated_status = evaluate_protection(&target, policy, &correlated).unwrap();
    assert_eq!(correlated_status.verified_replicas, 3);
    assert_eq!(correlated_status.distinct_hosts, 2);
    assert_eq!(
        correlated_status.state,
        ProtectionState::DegradedPolicyUnsatisfied
    );

    let a_entry = replicas
        .iter_mut()
        .find(|item| item.node.node_id == node(1).node_id)
        .unwrap();
    a_entry.receipt_health = ReceiptHealth::CurrentVerified;
    a_entry.receipts = vec![VerifiedReplicaReceipt::new_prevalidated(
        ReceiptId(id16(91)),
        target.cluster_id,
        node(1),
        ReplicaSubject::VersionBundle(v1),
        hash32(91),
        1,
    )];
    let stale_return = evaluate_protection(&target, policy, &replicas).unwrap();
    assert_eq!(stale_return.verified_replicas, 3);

    assert_eq!(semantic_objects.snapshot(), semantic_before_repair);
    assert_eq!(semantic_objects.heads(object).unwrap(), BTreeSet::from([v2]));
}
