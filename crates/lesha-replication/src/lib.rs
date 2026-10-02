#![forbid(unsafe_code)]

use std::collections::BTreeSet;

use lesha_types::{ChunkId, ClusterId, NodeId, NodeRef, VersionId};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct ReceiptId(pub [u8; 16]);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct FailureDomainId(pub [u8; 16]);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub enum ReplicaSubject {
    Chunk(ChunkId),
    VersionBundle(VersionId),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProtectedSubject {
    pub cluster_id: ClusterId,
    pub subject: ReplicaSubject,
    pub subject_hash: [u8; 32],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct VerifiedReplicaReceipt {
    pub receipt_id: ReceiptId,
    pub cluster_id: ClusterId,
    pub destination: NodeRef,
    pub subject: ReplicaSubject,
    pub subject_hash: [u8; 32],
    pub storage_generation: u64,
}

impl VerifiedReplicaReceipt {
    pub fn new_prevalidated(
        receipt_id: ReceiptId,
        cluster_id: ClusterId,
        destination: NodeRef,
        subject: ReplicaSubject,
        subject_hash: [u8; 32],
        storage_generation: u64,
    ) -> Self {
        Self {
            receipt_id,
            cluster_id,
            destination,
            subject,
            subject_hash,
            storage_generation,
        }
    }

    fn matches(&self, target: &ProtectedSubject, node: NodeRef) -> bool {
        self.cluster_id == target.cluster_id
            && self.destination == node
            && self.subject == target.subject
            && self.subject_hash == target.subject_hash
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReceiptHealth {
    CurrentVerified,
    Stale,
    Unknown,
    Corrupt,
    Missing,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DurabilityEligibility {
    CountsForDurability,
    StoreOnly,
    Ineligible,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ReplicaTopology {
    pub host: Option<FailureDomainId>,
    pub storage_device: Option<FailureDomainId>,
    pub site: Option<FailureDomainId>,
    pub power: Option<FailureDomainId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReplicaEvidence {
    pub node: NodeRef,
    pub receipts: Vec<VerifiedReplicaReceipt>,
    pub receipt_health: ReceiptHealth,
    pub eligibility: DurabilityEligibility,
    pub topology: ReplicaTopology,
    pub is_anchor: bool,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ReplicaPlacementPolicy {
    pub full_replica_count: usize,
    pub min_distinct_hosts: usize,
    pub min_distinct_storage_devices: usize,
    pub min_distinct_sites: usize,
    pub min_distinct_power_domains: usize,
    pub min_anchor_replicas: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProtectionState {
    Replicated,
    DegradedPolicyUnsatisfied,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDeficit {
    FullReplicas { required: usize, observed: usize },
    DistinctHosts { required: usize, observed: usize },
    DistinctStorageDevices { required: usize, observed: usize },
    DistinctSites { required: usize, observed: usize },
    DistinctPowerDomains { required: usize, observed: usize },
    AnchorReplicas { required: usize, observed: usize },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProtectionStatus {
    pub state: ProtectionState,
    pub credited_nodes: BTreeSet<NodeId>,
    pub verified_replicas: usize,
    pub distinct_hosts: usize,
    pub distinct_storage_devices: usize,
    pub distinct_sites: usize,
    pub distinct_power_domains: usize,
    pub anchor_replicas: usize,
    pub deficits: Vec<PolicyDeficit>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProtectionEvaluationError {
    DuplicateNodeEvidence(NodeId),
}

pub fn evaluate_protection(
    target: &ProtectedSubject,
    policy: ReplicaPlacementPolicy,
    evidence: &[ReplicaEvidence],
) -> Result<ProtectionStatus, ProtectionEvaluationError> {
    let mut seen_nodes = BTreeSet::new();
    let mut credited_nodes = BTreeSet::new();
    let mut hosts = BTreeSet::new();
    let mut storage_devices = BTreeSet::new();
    let mut sites = BTreeSet::new();
    let mut power_domains = BTreeSet::new();
    let mut anchor_replicas = 0usize;

    for replica in evidence {
        if !seen_nodes.insert(replica.node.node_id) {
            return Err(ProtectionEvaluationError::DuplicateNodeEvidence(
                replica.node.node_id,
            ));
        }

        if replica.receipt_health != ReceiptHealth::CurrentVerified
            || replica.eligibility != DurabilityEligibility::CountsForDurability
        {
            continue;
        }

        let has_matching_receipt = replica
            .receipts
            .iter()
            .any(|receipt| receipt.matches(target, replica.node));

        if !has_matching_receipt {
            continue;
        }

        credited_nodes.insert(replica.node.node_id);

        if let Some(domain) = replica.topology.host {
            hosts.insert(domain);
        }
        if let Some(domain) = replica.topology.storage_device {
            storage_devices.insert(domain);
        }
        if let Some(domain) = replica.topology.site {
            sites.insert(domain);
        }
        if let Some(domain) = replica.topology.power {
            power_domains.insert(domain);
        }
        if replica.is_anchor {
            anchor_replicas += 1;
        }
    }

    let verified_replicas = credited_nodes.len();
    let distinct_hosts = hosts.len();
    let distinct_storage_devices = storage_devices.len();
    let distinct_sites = sites.len();
    let distinct_power_domains = power_domains.len();

    let mut deficits = Vec::new();
    if verified_replicas < policy.full_replica_count {
        deficits.push(PolicyDeficit::FullReplicas {
            required: policy.full_replica_count,
            observed: verified_replicas,
        });
    }
    if distinct_hosts < policy.min_distinct_hosts {
        deficits.push(PolicyDeficit::DistinctHosts {
            required: policy.min_distinct_hosts,
            observed: distinct_hosts,
        });
    }
    if distinct_storage_devices < policy.min_distinct_storage_devices {
        deficits.push(PolicyDeficit::DistinctStorageDevices {
            required: policy.min_distinct_storage_devices,
            observed: distinct_storage_devices,
        });
    }
    if distinct_sites < policy.min_distinct_sites {
        deficits.push(PolicyDeficit::DistinctSites {
            required: policy.min_distinct_sites,
            observed: distinct_sites,
        });
    }
    if distinct_power_domains < policy.min_distinct_power_domains {
        deficits.push(PolicyDeficit::DistinctPowerDomains {
            required: policy.min_distinct_power_domains,
            observed: distinct_power_domains,
        });
    }
    if anchor_replicas < policy.min_anchor_replicas {
        deficits.push(PolicyDeficit::AnchorReplicas {
            required: policy.min_anchor_replicas,
            observed: anchor_replicas,
        });
    }

    Ok(ProtectionStatus {
        state: if deficits.is_empty() {
            ProtectionState::Replicated
        } else {
            ProtectionState::DegradedPolicyUnsatisfied
        },
        credited_nodes,
        verified_replicas,
        distinct_hosts,
        distinct_storage_devices,
        distinct_sites,
        distinct_power_domains,
        anchor_replicas,
        deficits,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use lesha_types::NodeGeneration;

    fn node(tag: u8) -> NodeRef {
        NodeRef {
            cluster_id: ClusterId([1; 16]),
            node_id: NodeId([tag; 32]),
            generation: NodeGeneration(1),
        }
    }

    fn domain(tag: u8) -> FailureDomainId {
        FailureDomainId([tag; 16])
    }

    fn target() -> ProtectedSubject {
        ProtectedSubject {
            cluster_id: ClusterId([1; 16]),
            subject: ReplicaSubject::Chunk(ChunkId([7; 32])),
            subject_hash: [8; 32],
        }
    }

    fn receipt(tag: u8, destination: NodeRef) -> VerifiedReplicaReceipt {
        VerifiedReplicaReceipt::new_prevalidated(
            ReceiptId([tag; 16]),
            ClusterId([1; 16]),
            destination,
            ReplicaSubject::Chunk(ChunkId([7; 32])),
            [8; 32],
            1,
        )
    }

    fn evidence(
        tag: u8,
        host: Option<u8>,
        anchor: bool,
        health: ReceiptHealth,
        eligibility: DurabilityEligibility,
    ) -> ReplicaEvidence {
        let n = node(tag);
        ReplicaEvidence {
            node: n,
            receipts: vec![receipt(tag, n)],
            receipt_health: health,
            eligibility,
            topology: ReplicaTopology {
                host: host.map(domain),
                storage_device: Some(domain(tag.wrapping_add(20))),
                site: None,
                power: None,
            },
            is_anchor: anchor,
        }
    }

    fn policy() -> ReplicaPlacementPolicy {
        ReplicaPlacementPolicy {
            full_replica_count: 3,
            min_distinct_hosts: 3,
            min_distinct_storage_devices: 3,
            min_distinct_sites: 0,
            min_distinct_power_domains: 0,
            min_anchor_replicas: 1,
        }
    }

    #[test]
    fn three_verified_independent_replicas_satisfy_policy() {
        let status = evaluate_protection(
            &target(),
            policy(),
            &[
                evidence(
                    1,
                    Some(1),
                    true,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    2,
                    Some(2),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    3,
                    Some(3),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
            ],
        )
        .unwrap();

        assert_eq!(status.state, ProtectionState::Replicated);
        assert!(status.deficits.is_empty());
        assert_eq!(status.verified_replicas, 3);
        assert_eq!(status.distinct_hosts, 3);
        assert_eq!(status.anchor_replicas, 1);
    }

    #[test]
    fn duplicate_receipts_on_one_destination_do_not_double_count() {
        let n = node(1);
        let mut one = evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        );
        one.receipts.push(receipt(99, n));

        let status = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                ..Default::default()
            },
            &[one],
        )
        .unwrap();

        assert_eq!(status.verified_replicas, 1);
        assert_eq!(
            status.deficits,
            vec![PolicyDeficit::FullReplicas {
                required: 2,
                observed: 1
            }]
        );
    }

    #[test]
    fn same_host_and_unknown_host_do_not_fake_diversity() {
        let status = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                min_distinct_hosts: 3,
                ..Default::default()
            },
            &[
                evidence(
                    1,
                    Some(9),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    2,
                    Some(9),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    3,
                    None,
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
            ],
        )
        .unwrap();

        assert_eq!(status.verified_replicas, 3);
        assert_eq!(status.distinct_hosts, 1);
        assert_eq!(
            status.deficits,
            vec![PolicyDeficit::DistinctHosts {
                required: 3,
                observed: 1
            }]
        );
    }

    #[test]
    fn stale_store_only_or_wrong_subject_receipts_do_not_count() {
        let mut wrong_subject = evidence(
            3,
            Some(3),
            false,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        );
        wrong_subject.receipts[0].subject_hash = [99; 32];

        let status = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                ..Default::default()
            },
            &[
                evidence(
                    1,
                    Some(1),
                    false,
                    ReceiptHealth::Stale,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    2,
                    Some(2),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::StoreOnly,
                ),
                wrong_subject,
            ],
        )
        .unwrap();

        assert_eq!(status.verified_replicas, 0);
        assert_eq!(
            status.deficits,
            vec![PolicyDeficit::FullReplicas {
                required: 3,
                observed: 0
            }]
        );
    }

    #[test]
    fn anchor_requirement_is_independent_from_replica_count() {
        let status = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                min_anchor_replicas: 1,
                ..Default::default()
            },
            &[
                evidence(
                    1,
                    Some(1),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
                evidence(
                    2,
                    Some(2),
                    false,
                    ReceiptHealth::CurrentVerified,
                    DurabilityEligibility::CountsForDurability,
                ),
            ],
        )
        .unwrap();

        assert_eq!(status.verified_replicas, 2);
        assert_eq!(
            status.deficits,
            vec![PolicyDeficit::AnchorReplicas {
                required: 1,
                observed: 0
            }]
        );
    }

    #[test]
    fn duplicate_node_evidence_is_rejected_instead_of_order_dependent() {
        let e = evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        );
        assert_eq!(
            evaluate_protection(&target(), policy(), &[e.clone(), e]),
            Err(ProtectionEvaluationError::DuplicateNodeEvidence(NodeId(
                [1; 32]
            )))
        );
    }
}
