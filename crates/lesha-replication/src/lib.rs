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

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct HealthEvidenceSequence(pub u64);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ReplicaHealthObservationKind {
    VerifiedHealthy,
    ReverificationRequired,
    DigestMismatch,
    Missing,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReplicaHealthObservation {
    pub node: NodeRef,
    pub storage_generation: u64,
    pub sequence: HealthEvidenceSequence,
    pub kind: ReplicaHealthObservationKind,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HealthObservationApply {
    Applied { health: ReceiptHealth },
    Duplicate,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HealthTrackerError {
    NodeMismatch,
    StorageGenerationMismatch {
        expected: u64,
        received: u64,
    },
    SequenceRegression {
        last: HealthEvidenceSequence,
        received: HealthEvidenceSequence,
    },
    SequenceEquivocation {
        sequence: HealthEvidenceSequence,
    },
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ReplicaHealthTracker {
    node: NodeRef,
    storage_generation: u64,
    last_observation: Option<ReplicaHealthObservation>,
    health: ReceiptHealth,
}

impl ReplicaHealthTracker {
    pub fn new(node: NodeRef, storage_generation: u64) -> Self {
        Self {
            node,
            storage_generation,
            last_observation: None,
            health: ReceiptHealth::Unknown,
        }
    }

    pub fn node(&self) -> NodeRef {
        self.node
    }

    pub fn storage_generation(&self) -> u64 {
        self.storage_generation
    }

    pub fn health(&self) -> ReceiptHealth {
        self.health
    }

    pub fn last_sequence(&self) -> Option<HealthEvidenceSequence> {
        self.last_observation
            .map(|observation| observation.sequence)
    }

    pub fn apply(
        &mut self,
        observation: ReplicaHealthObservation,
    ) -> Result<HealthObservationApply, HealthTrackerError> {
        if observation.node != self.node {
            return Err(HealthTrackerError::NodeMismatch);
        }
        if observation.storage_generation != self.storage_generation {
            return Err(HealthTrackerError::StorageGenerationMismatch {
                expected: self.storage_generation,
                received: observation.storage_generation,
            });
        }

        if let Some(last) = self.last_observation {
            if observation.sequence < last.sequence {
                return Err(HealthTrackerError::SequenceRegression {
                    last: last.sequence,
                    received: observation.sequence,
                });
            }
            if observation.sequence == last.sequence {
                return if observation == last {
                    Ok(HealthObservationApply::Duplicate)
                } else {
                    Err(HealthTrackerError::SequenceEquivocation {
                        sequence: observation.sequence,
                    })
                };
            }
        }

        self.health = match observation.kind {
            ReplicaHealthObservationKind::VerifiedHealthy => ReceiptHealth::CurrentVerified,
            ReplicaHealthObservationKind::ReverificationRequired => match self.health {
                ReceiptHealth::Corrupt => ReceiptHealth::Corrupt,
                ReceiptHealth::Missing => ReceiptHealth::Missing,
                ReceiptHealth::CurrentVerified | ReceiptHealth::Stale | ReceiptHealth::Unknown => {
                    ReceiptHealth::Stale
                }
            },
            ReplicaHealthObservationKind::DigestMismatch => ReceiptHealth::Corrupt,
            ReplicaHealthObservationKind::Missing => ReceiptHealth::Missing,
        };
        self.last_observation = Some(observation);

        Ok(HealthObservationApply::Applied {
            health: self.health,
        })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RepairCandidateState {
    Available,
    TemporarilyUnavailable,
    CapacityBlocked,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RepairCandidate {
    pub node: NodeRef,
    pub eligibility: DurabilityEligibility,
    pub topology: ReplicaTopology,
    pub is_anchor: bool,
    pub state: RepairCandidateState,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RepairPlanState {
    Complete,
    Partial,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PlannedRepairTarget {
    pub node: NodeRef,
    pub deficit_units_closed: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RepairPlan {
    pub state: RepairPlanState,
    pub initial: ProtectionStatus,
    pub targets: Vec<PlannedRepairTarget>,
    pub projected: ProtectionStatus,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RepairPlanError {
    Protection(ProtectionEvaluationError),
    DuplicateCandidate(NodeId),
}

pub fn plan_repairs(
    target: &ProtectedSubject,
    policy: ReplicaPlacementPolicy,
    evidence: &[ReplicaEvidence],
    candidates: &[RepairCandidate],
    max_targets: usize,
) -> Result<RepairPlan, RepairPlanError> {
    let initial =
        evaluate_protection(target, policy, evidence).map_err(RepairPlanError::Protection)?;

    let mut seen_candidates = BTreeSet::new();
    for candidate in candidates {
        if !seen_candidates.insert(candidate.node.node_id) {
            return Err(RepairPlanError::DuplicateCandidate(candidate.node.node_id));
        }
    }

    let mut working_evidence = evidence.to_vec();
    let mut projected = initial.clone();
    let mut selected = BTreeSet::new();
    let mut targets = Vec::new();

    while !projected.deficits.is_empty() && targets.len() < max_targets {
        let current_gap = deficit_units(&projected);
        let mut best: Option<(
            usize,
            usize,
            bool,
            NodeId,
            RepairCandidate,
            ProtectionStatus,
        )> = None;

        for candidate in candidates {
            if selected.contains(&candidate.node.node_id)
                || candidate.node.cluster_id != target.cluster_id
                || candidate.state != RepairCandidateState::Available
                || candidate.eligibility != DurabilityEligibility::CountsForDurability
                || projected.credited_nodes.contains(&candidate.node.node_id)
            {
                continue;
            }

            let candidate_evidence = projected_evidence_for_candidate(target, *candidate);
            let candidate_set = replace_or_append_evidence(&working_evidence, candidate_evidence);
            let candidate_status = evaluate_protection(target, policy, &candidate_set)
                .map_err(RepairPlanError::Protection)?;
            let new_gap = deficit_units(&candidate_status);
            let gain = current_gap.saturating_sub(new_gap);
            if gain == 0 {
                continue;
            }

            let known_domains = known_domain_count(candidate.topology);
            let rank = (
                gain,
                known_domains,
                candidate.is_anchor,
                candidate.node.node_id,
                *candidate,
                candidate_status,
            );

            let replace = match &best {
                None => true,
                Some(existing) => {
                    rank.0 > existing.0
                        || (rank.0 == existing.0 && rank.1 > existing.1)
                        || (rank.0 == existing.0 && rank.1 == existing.1 && rank.2 && !existing.2)
                        || (rank.0 == existing.0
                            && rank.1 == existing.1
                            && rank.2 == existing.2
                            && rank.3 < existing.3)
                }
            };

            if replace {
                best = Some(rank);
            }
        }

        let Some((gain, _, _, node_id, candidate, candidate_status)) = best else {
            break;
        };

        selected.insert(node_id);
        working_evidence = replace_or_append_evidence(
            &working_evidence,
            projected_evidence_for_candidate(target, candidate),
        );
        projected = candidate_status;
        targets.push(PlannedRepairTarget {
            node: candidate.node,
            deficit_units_closed: gain,
        });
    }

    Ok(RepairPlan {
        state: if projected.deficits.is_empty() {
            RepairPlanState::Complete
        } else {
            RepairPlanState::Partial
        },
        initial,
        targets,
        projected,
    })
}

fn deficit_units(status: &ProtectionStatus) -> usize {
    status
        .deficits
        .iter()
        .map(|deficit| match *deficit {
            PolicyDeficit::FullReplicas { required, observed }
            | PolicyDeficit::DistinctHosts { required, observed }
            | PolicyDeficit::DistinctStorageDevices { required, observed }
            | PolicyDeficit::DistinctSites { required, observed }
            | PolicyDeficit::DistinctPowerDomains { required, observed }
            | PolicyDeficit::AnchorReplicas { required, observed } => {
                required.saturating_sub(observed)
            }
        })
        .sum()
}

fn known_domain_count(topology: ReplicaTopology) -> usize {
    [
        topology.host,
        topology.storage_device,
        topology.site,
        topology.power,
    ]
    .into_iter()
    .flatten()
    .count()
}

fn projected_evidence_for_candidate(
    target: &ProtectedSubject,
    candidate: RepairCandidate,
) -> ReplicaEvidence {
    let mut receipt_id = [0u8; 16];
    receipt_id.copy_from_slice(&candidate.node.node_id.0[..16]);

    ReplicaEvidence {
        node: candidate.node,
        receipts: vec![VerifiedReplicaReceipt::new_prevalidated(
            ReceiptId(receipt_id),
            target.cluster_id,
            candidate.node,
            target.subject,
            target.subject_hash,
            0,
        )],
        receipt_health: ReceiptHealth::CurrentVerified,
        eligibility: DurabilityEligibility::CountsForDurability,
        topology: candidate.topology,
        is_anchor: candidate.is_anchor,
    }
}

fn replace_or_append_evidence(
    evidence: &[ReplicaEvidence],
    replacement: ReplicaEvidence,
) -> Vec<ReplicaEvidence> {
    let mut out = evidence.to_vec();
    if let Some(existing) = out
        .iter_mut()
        .find(|item| item.node.node_id == replacement.node.node_id)
    {
        *existing = replacement;
    } else {
        out.push(replacement);
    }
    out
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct RepairBudget {
    pub max_targets: usize,
    pub max_jobs: usize,
    pub max_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RepairWorkCandidate {
    pub candidate: RepairCandidate,
    pub expected_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ScheduledRepairWork {
    pub node: NodeRef,
    pub expected_bytes: u64,
    pub deficit_units_closed: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DeferredRepairReason {
    TargetBudgetExhausted,
    JobBudgetExhausted,
    ByteBudgetExceeded,
    NotCurrentlySchedulable,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct DeferredRepairWork {
    pub node: NodeRef,
    pub expected_bytes: u64,
    pub reason: DeferredRepairReason,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundedRepairPlan {
    pub state: RepairPlanState,
    pub initial: ProtectionStatus,
    pub scheduled: Vec<ScheduledRepairWork>,
    pub deferred: Vec<DeferredRepairWork>,
    pub projected: ProtectionStatus,
    pub used_jobs: usize,
    pub used_bytes: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BoundedRepairPlanError {
    Protection(ProtectionEvaluationError),
    DuplicateCandidate(NodeId),
}

pub fn plan_bounded_repairs(
    target: &ProtectedSubject,
    policy: ReplicaPlacementPolicy,
    evidence: &[ReplicaEvidence],
    candidates: &[RepairWorkCandidate],
    budget: RepairBudget,
) -> Result<BoundedRepairPlan, BoundedRepairPlanError> {
    let initial = evaluate_protection(target, policy, evidence)
        .map_err(BoundedRepairPlanError::Protection)?;

    let mut seen_candidates = BTreeSet::new();
    for work in candidates {
        if !seen_candidates.insert(work.candidate.node.node_id) {
            return Err(BoundedRepairPlanError::DuplicateCandidate(
                work.candidate.node.node_id,
            ));
        }
    }

    let mut working_evidence = evidence.to_vec();
    let mut projected = initial.clone();
    let mut selected = BTreeSet::new();
    let mut scheduled = Vec::new();
    let mut used_jobs = 0usize;
    let mut used_bytes = 0u64;

    while !projected.deficits.is_empty()
        && scheduled.len() < budget.max_targets
        && used_jobs < budget.max_jobs
    {
        let remaining_bytes = budget.max_bytes.saturating_sub(used_bytes);
        let current_gap = deficit_units(&projected);
        let mut best: Option<(
            usize,
            usize,
            bool,
            NodeId,
            RepairWorkCandidate,
            ProtectionStatus,
        )> = None;

        for work in candidates {
            let candidate = work.candidate;
            if selected.contains(&candidate.node.node_id)
                || candidate.node.cluster_id != target.cluster_id
                || candidate.state != RepairCandidateState::Available
                || candidate.eligibility != DurabilityEligibility::CountsForDurability
                || projected.credited_nodes.contains(&candidate.node.node_id)
                || work.expected_bytes > remaining_bytes
            {
                continue;
            }

            let candidate_evidence = projected_evidence_for_candidate(target, candidate);
            let candidate_set = replace_or_append_evidence(&working_evidence, candidate_evidence);
            let candidate_status = evaluate_protection(target, policy, &candidate_set)
                .map_err(BoundedRepairPlanError::Protection)?;
            let gain = current_gap.saturating_sub(deficit_units(&candidate_status));
            if gain == 0 {
                continue;
            }

            let rank = (
                gain,
                known_domain_count(candidate.topology),
                candidate.is_anchor,
                candidate.node.node_id,
                *work,
                candidate_status,
            );
            let replace = match &best {
                None => true,
                Some(existing) => {
                    rank.0 > existing.0
                        || (rank.0 == existing.0 && rank.1 > existing.1)
                        || (rank.0 == existing.0 && rank.1 == existing.1 && rank.2 && !existing.2)
                        || (rank.0 == existing.0
                            && rank.1 == existing.1
                            && rank.2 == existing.2
                            && rank.3 < existing.3)
                }
            };
            if replace {
                best = Some(rank);
            }
        }

        let Some((gain, _, _, node_id, work, candidate_status)) = best else {
            break;
        };

        selected.insert(node_id);
        used_jobs += 1;
        used_bytes += work.expected_bytes;
        working_evidence = replace_or_append_evidence(
            &working_evidence,
            projected_evidence_for_candidate(target, work.candidate),
        );
        projected = candidate_status;
        scheduled.push(ScheduledRepairWork {
            node: work.candidate.node,
            expected_bytes: work.expected_bytes,
            deficit_units_closed: gain,
        });
    }

    let remaining_bytes = budget.max_bytes.saturating_sub(used_bytes);
    let current_gap = deficit_units(&projected);
    let mut deferred = Vec::new();

    if !projected.deficits.is_empty() {
        for work in candidates {
            let candidate = work.candidate;
            if selected.contains(&candidate.node.node_id)
                || projected.credited_nodes.contains(&candidate.node.node_id)
                || candidate.node.cluster_id != target.cluster_id
            {
                continue;
            }

            let candidate_evidence = projected_evidence_for_candidate(target, candidate);
            let candidate_set = replace_or_append_evidence(&working_evidence, candidate_evidence);
            let candidate_status = evaluate_protection(target, policy, &candidate_set)
                .map_err(BoundedRepairPlanError::Protection)?;
            let gain = current_gap.saturating_sub(deficit_units(&candidate_status));
            if gain == 0 {
                continue;
            }

            let reason = if candidate.state != RepairCandidateState::Available
                || candidate.eligibility != DurabilityEligibility::CountsForDurability
            {
                DeferredRepairReason::NotCurrentlySchedulable
            } else if scheduled.len() >= budget.max_targets {
                DeferredRepairReason::TargetBudgetExhausted
            } else if used_jobs >= budget.max_jobs {
                DeferredRepairReason::JobBudgetExhausted
            } else if work.expected_bytes > remaining_bytes {
                DeferredRepairReason::ByteBudgetExceeded
            } else {
                continue;
            };

            deferred.push(DeferredRepairWork {
                node: candidate.node,
                expected_bytes: work.expected_bytes,
                reason,
            });
        }
    }
    deferred.sort_by_key(|work| work.node.node_id);

    Ok(BoundedRepairPlan {
        state: if projected.deficits.is_empty() {
            RepairPlanState::Complete
        } else {
            RepairPlanState::Partial
        },
        initial,
        scheduled,
        deferred,
        projected,
        used_jobs,
        used_bytes,
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
    fn candidate(
        tag: u8,
        host: Option<u8>,
        anchor: bool,
        state: RepairCandidateState,
    ) -> RepairCandidate {
        RepairCandidate {
            node: node(tag),
            eligibility: DurabilityEligibility::CountsForDurability,
            topology: ReplicaTopology {
                host: host.map(domain),
                storage_device: Some(domain(tag.wrapping_add(20))),
                site: None,
                power: None,
            },
            is_anchor: anchor,
            state,
        }
    }

    #[test]
    fn repair_planner_prefers_target_that_closes_more_policy_deficits() {
        let current = [
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
        ];
        let plan = plan_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                min_distinct_hosts: 3,
                ..Default::default()
            },
            &current,
            &[
                candidate(3, Some(2), false, RepairCandidateState::Available),
                candidate(4, Some(4), false, RepairCandidateState::Available),
            ],
            1,
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Complete);
        assert_eq!(plan.targets.len(), 1);
        assert_eq!(plan.targets[0].node.node_id, NodeId([4; 32]));
        assert_eq!(plan.targets[0].deficit_units_closed, 2);
    }

    #[test]
    fn repair_planner_uses_anchor_when_anchor_is_the_only_deficit() {
        let current = [
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
        ];
        let plan = plan_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                min_anchor_replicas: 1,
                ..Default::default()
            },
            &current,
            &[
                candidate(3, Some(3), false, RepairCandidateState::Available),
                candidate(4, Some(4), true, RepairCandidateState::Available),
            ],
            1,
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Complete);
        assert_eq!(plan.targets[0].node.node_id, NodeId([4; 32]));
    }

    #[test]
    fn repair_planner_does_not_invent_diversity_from_unknown_domain() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let mut known_site = candidate(3, Some(3), false, RepairCandidateState::Available);
        known_site.topology.site = Some(domain(3));

        let plan = plan_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                min_distinct_sites: 1,
                ..Default::default()
            },
            &current,
            &[
                candidate(2, None, false, RepairCandidateState::Available),
                known_site,
            ],
            1,
        )
        .unwrap();

        assert_eq!(plan.targets[0].node.node_id, NodeId([3; 32]));
        assert_eq!(plan.projected.distinct_sites, 1);
    }

    #[test]
    fn repair_planner_returns_partial_when_available_targets_cannot_close_deficit() {
        let current = [
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
        ];
        let plan = plan_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                min_distinct_hosts: 2,
                ..Default::default()
            },
            &current,
            &[
                candidate(3, Some(9), false, RepairCandidateState::Available),
                candidate(4, None, false, RepairCandidateState::Available),
            ],
            2,
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Partial);
        assert!(plan.targets.is_empty());
        assert_eq!(
            plan.projected.deficits,
            vec![PolicyDeficit::DistinctHosts {
                required: 2,
                observed: 1
            }]
        );
    }

    #[test]
    fn repair_planner_is_deterministic_and_filters_unavailable_targets() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let candidates = [
            candidate(
                2,
                Some(2),
                false,
                RepairCandidateState::TemporarilyUnavailable,
            ),
            candidate(4, Some(4), false, RepairCandidateState::Available),
            candidate(3, Some(3), false, RepairCandidateState::Available),
        ];
        let policy = ReplicaPlacementPolicy {
            full_replica_count: 2,
            ..Default::default()
        };

        let first = plan_repairs(&target(), policy, &current, &candidates, 1).unwrap();
        let second = plan_repairs(&target(), policy, &current, &candidates, 1).unwrap();

        assert_eq!(first, second);
        assert_eq!(first.targets[0].node.node_id, NodeId([3; 32]));
    }

    #[test]
    fn repair_planner_can_repair_stale_existing_node_without_double_evidence() {
        let stale = evidence(
            2,
            Some(2),
            false,
            ReceiptHealth::Stale,
            DurabilityEligibility::CountsForDurability,
        );
        let current = [
            evidence(
                1,
                Some(1),
                true,
                ReceiptHealth::CurrentVerified,
                DurabilityEligibility::CountsForDurability,
            ),
            stale,
        ];

        let plan = plan_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                ..Default::default()
            },
            &current,
            &[candidate(
                2,
                Some(2),
                false,
                RepairCandidateState::Available,
            )],
            1,
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Complete);
        assert_eq!(plan.targets[0].node.node_id, NodeId([2; 32]));
        assert_eq!(plan.projected.verified_replicas, 2);
    }
    fn health_observation(
        node: NodeRef,
        storage_generation: u64,
        sequence: u64,
        kind: ReplicaHealthObservationKind,
    ) -> ReplicaHealthObservation {
        ReplicaHealthObservation {
            node,
            storage_generation,
            sequence: HealthEvidenceSequence(sequence),
            kind,
        }
    }

    #[test]
    fn reverification_required_removes_durability_credit_without_wall_clock_logic() {
        let n = node(1);
        let mut tracker = ReplicaHealthTracker::new(n, 1);
        tracker
            .apply(health_observation(
                n,
                1,
                1,
                ReplicaHealthObservationKind::VerifiedHealthy,
            ))
            .unwrap();

        let mut replica = evidence(
            1,
            Some(1),
            true,
            tracker.health(),
            DurabilityEligibility::CountsForDurability,
        );
        let current = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 1,
                ..Default::default()
            },
            &[replica.clone()],
        )
        .unwrap();
        assert_eq!(current.state, ProtectionState::Replicated);

        tracker
            .apply(health_observation(
                n,
                1,
                2,
                ReplicaHealthObservationKind::ReverificationRequired,
            ))
            .unwrap();
        replica.receipt_health = tracker.health();

        let stale = evaluate_protection(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 1,
                ..Default::default()
            },
            &[replica],
        )
        .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::Stale);
        assert_eq!(stale.verified_replicas, 0);
        assert_eq!(stale.state, ProtectionState::DegradedPolicyUnsatisfied);
    }

    #[test]
    fn health_observations_are_idempotent_and_monotonic() {
        let n = node(1);
        let mut tracker = ReplicaHealthTracker::new(n, 7);
        let healthy = health_observation(n, 7, 10, ReplicaHealthObservationKind::VerifiedHealthy);

        assert_eq!(
            tracker.apply(healthy),
            Ok(HealthObservationApply::Applied {
                health: ReceiptHealth::CurrentVerified
            })
        );
        assert_eq!(
            tracker.apply(healthy),
            Ok(HealthObservationApply::Duplicate)
        );
        assert_eq!(
            tracker.apply(health_observation(
                n,
                7,
                10,
                ReplicaHealthObservationKind::Missing,
            )),
            Err(HealthTrackerError::SequenceEquivocation {
                sequence: HealthEvidenceSequence(10)
            })
        );
        assert_eq!(
            tracker.apply(health_observation(
                n,
                7,
                9,
                ReplicaHealthObservationKind::VerifiedHealthy,
            )),
            Err(HealthTrackerError::SequenceRegression {
                last: HealthEvidenceSequence(10),
                received: HealthEvidenceSequence(9)
            })
        );
        assert_eq!(tracker.health(), ReceiptHealth::CurrentVerified);
    }

    #[test]
    fn health_observation_is_bound_to_node_and_storage_generation() {
        let n = node(1);
        let mut tracker = ReplicaHealthTracker::new(n, 4);

        assert_eq!(
            tracker.apply(health_observation(
                node(2),
                4,
                1,
                ReplicaHealthObservationKind::VerifiedHealthy,
            )),
            Err(HealthTrackerError::NodeMismatch)
        );
        assert_eq!(
            tracker.apply(health_observation(
                n,
                3,
                1,
                ReplicaHealthObservationKind::VerifiedHealthy,
            )),
            Err(HealthTrackerError::StorageGenerationMismatch {
                expected: 4,
                received: 3
            })
        );
        assert_eq!(tracker.health(), ReceiptHealth::Unknown);
    }

    #[test]
    fn corruption_or_missing_state_persists_until_explicit_healthy_reverification() {
        let n = node(1);
        let mut tracker = ReplicaHealthTracker::new(n, 1);

        tracker
            .apply(health_observation(
                n,
                1,
                1,
                ReplicaHealthObservationKind::DigestMismatch,
            ))
            .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::Corrupt);

        tracker
            .apply(health_observation(
                n,
                1,
                2,
                ReplicaHealthObservationKind::ReverificationRequired,
            ))
            .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::Corrupt);

        tracker
            .apply(health_observation(
                n,
                1,
                3,
                ReplicaHealthObservationKind::VerifiedHealthy,
            ))
            .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::CurrentVerified);

        tracker
            .apply(health_observation(
                n,
                1,
                4,
                ReplicaHealthObservationKind::Missing,
            ))
            .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::Missing);

        tracker
            .apply(health_observation(
                n,
                1,
                5,
                ReplicaHealthObservationKind::VerifiedHealthy,
            ))
            .unwrap();
        assert_eq!(tracker.health(), ReceiptHealth::CurrentVerified);
    }
    fn work_candidate(
        tag: u8,
        host: Option<u8>,
        anchor: bool,
        state: RepairCandidateState,
        expected_bytes: u64,
    ) -> RepairWorkCandidate {
        RepairWorkCandidate {
            candidate: candidate(tag, host, anchor, state),
            expected_bytes,
        }
    }

    #[test]
    fn bounded_repair_skips_oversized_target_and_schedules_fitting_work() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let plan = plan_bounded_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                min_distinct_hosts: 3,
                ..Default::default()
            },
            &current,
            &[
                work_candidate(2, Some(2), false, RepairCandidateState::Available, 100),
                work_candidate(3, Some(3), false, RepairCandidateState::Available, 10),
            ],
            RepairBudget {
                max_targets: 2,
                max_jobs: 2,
                max_bytes: 10,
            },
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Partial);
        assert_eq!(plan.scheduled.len(), 1);
        assert_eq!(plan.scheduled[0].node.node_id, NodeId([3; 32]));
        assert_eq!(plan.used_jobs, 1);
        assert_eq!(plan.used_bytes, 10);
        assert_eq!(
            plan.deferred,
            vec![DeferredRepairWork {
                node: node(2),
                expected_bytes: 100,
                reason: DeferredRepairReason::ByteBudgetExceeded,
            }]
        );
        assert_eq!(plan.projected.verified_replicas, 2);
    }

    #[test]
    fn bounded_repair_job_budget_preserves_remaining_deficit() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let plan = plan_bounded_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                ..Default::default()
            },
            &current,
            &[
                work_candidate(2, Some(2), false, RepairCandidateState::Available, 1),
                work_candidate(3, Some(3), false, RepairCandidateState::Available, 1),
            ],
            RepairBudget {
                max_targets: 2,
                max_jobs: 1,
                max_bytes: 100,
            },
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Partial);
        assert_eq!(plan.scheduled.len(), 1);
        assert_eq!(plan.scheduled[0].node.node_id, NodeId([2; 32]));
        assert_eq!(
            plan.deferred,
            vec![DeferredRepairWork {
                node: node(3),
                expected_bytes: 1,
                reason: DeferredRepairReason::JobBudgetExhausted,
            }]
        );
        assert_eq!(
            plan.projected.deficits,
            vec![PolicyDeficit::FullReplicas {
                required: 3,
                observed: 2,
            }]
        );
    }

    #[test]
    fn bounded_repair_target_budget_is_distinct_from_job_budget() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let plan = plan_bounded_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 3,
                ..Default::default()
            },
            &current,
            &[
                work_candidate(2, Some(2), false, RepairCandidateState::Available, 1),
                work_candidate(3, Some(3), false, RepairCandidateState::Available, 1),
            ],
            RepairBudget {
                max_targets: 1,
                max_jobs: 2,
                max_bytes: 100,
            },
        )
        .unwrap();

        assert_eq!(plan.scheduled.len(), 1);
        assert_eq!(
            plan.deferred,
            vec![DeferredRepairWork {
                node: node(3),
                expected_bytes: 1,
                reason: DeferredRepairReason::TargetBudgetExhausted,
            }]
        );
    }

    #[test]
    fn bounded_repair_marks_unavailable_useful_target_as_deferred() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let plan = plan_bounded_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                ..Default::default()
            },
            &current,
            &[work_candidate(
                2,
                Some(2),
                false,
                RepairCandidateState::TemporarilyUnavailable,
                10,
            )],
            RepairBudget {
                max_targets: 1,
                max_jobs: 1,
                max_bytes: 100,
            },
        )
        .unwrap();

        assert!(plan.scheduled.is_empty());
        assert_eq!(
            plan.deferred,
            vec![DeferredRepairWork {
                node: node(2),
                expected_bytes: 10,
                reason: DeferredRepairReason::NotCurrentlySchedulable,
            }]
        );
        assert_eq!(plan.state, RepairPlanState::Partial);
    }

    #[test]
    fn bounded_repair_is_deterministic_across_candidate_input_order() {
        let current = [evidence(
            1,
            Some(1),
            true,
            ReceiptHealth::CurrentVerified,
            DurabilityEligibility::CountsForDurability,
        )];
        let left = [
            work_candidate(3, Some(3), false, RepairCandidateState::Available, 1),
            work_candidate(2, Some(2), false, RepairCandidateState::Available, 1),
        ];
        let right = [left[1], left[0]];
        let policy = ReplicaPlacementPolicy {
            full_replica_count: 3,
            ..Default::default()
        };
        let budget = RepairBudget {
            max_targets: 1,
            max_jobs: 1,
            max_bytes: 10,
        };

        let first = plan_bounded_repairs(&target(), policy, &current, &left, budget).unwrap();
        let second = plan_bounded_repairs(&target(), policy, &current, &right, budget).unwrap();

        assert_eq!(first, second);
        assert_eq!(first.scheduled[0].node.node_id, NodeId([2; 32]));
    }

    #[test]
    fn bounded_repair_does_no_work_when_policy_is_already_satisfied() {
        let current = [
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
        ];
        let plan = plan_bounded_repairs(
            &target(),
            ReplicaPlacementPolicy {
                full_replica_count: 2,
                ..Default::default()
            },
            &current,
            &[work_candidate(
                3,
                Some(3),
                false,
                RepairCandidateState::Available,
                5,
            )],
            RepairBudget {
                max_targets: 4,
                max_jobs: 4,
                max_bytes: 100,
            },
        )
        .unwrap();

        assert_eq!(plan.state, RepairPlanState::Complete);
        assert!(plan.scheduled.is_empty());
        assert!(plan.deferred.is_empty());
        assert_eq!(plan.used_jobs, 0);
        assert_eq!(plan.used_bytes, 0);
    }
}
