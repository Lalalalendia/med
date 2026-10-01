use std::collections::{BTreeMap, BTreeSet};

use lesha_canonical::CanonicalAuthorityBytes;
use lesha_types::{
    AuthorityEpoch, ChunkId, ClusterId, CommitSeq, ControlFrontierHash, ManifestHash, ObjectId,
    OperationId, VersionId,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChunkDescriptor {
    pub chunk_id: ChunkId,
    pub ciphertext_len: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum ChunkRole {
    Payload,
    Attachment,
    Preview,
    Other(u16),
}

impl ChunkRole {
    pub fn storage_code(&self) -> u32 {
        match self {
            Self::Payload => 0,
            Self::Attachment => 1,
            Self::Preview => 2,
            Self::Other(value) => 0x1_0000 + u32::from(*value),
        }
    }

    pub fn from_storage_code(code: u32) -> Option<Self> {
        match code {
            0 => Some(Self::Payload),
            1 => Some(Self::Attachment),
            2 => Some(Self::Preview),
            0x1_0000..=0x1_FFFF => Some(Self::Other((code - 0x1_0000) as u16)),
            _ => None,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ChunkRef {
    pub ordinal: u32,
    pub role: ChunkRole,
    pub descriptor: ChunkDescriptor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectVersionManifest {
    pub cluster_id: ClusterId,
    pub object_id: ObjectId,
    pub version_id: VersionId,
    pub operation_id: OperationId,
    pub parents: Vec<VersionId>,
    pub authority_epoch: AuthorityEpoch,
    pub control_frontier: ControlFrontierHash,
    pub chunks: Vec<ChunkRef>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedManifest {
    pub semantic: ObjectVersionManifest,
    pub canonical: CanonicalAuthorityBytes,
    pub manifest_hash: ManifestHash,
}

impl ValidatedManifest {
    pub fn new_prevalidated(
        semantic: ObjectVersionManifest,
        canonical: CanonicalAuthorityBytes,
        manifest_hash: ManifestHash,
    ) -> Self {
        Self {
            semantic,
            canonical,
            manifest_hash,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CommitConsistency {
    StrictSingleHead,
    MergeableBranch,
    MergeResolution,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedObjectCommit {
    pub manifest: ValidatedManifest,
    pub request_hash: [u8; 32],
    pub expected_heads: BTreeSet<VersionId>,
    pub consistency: CommitConsistency,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DurableChunkReceipt {
    pub descriptor: ChunkDescriptor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ChunkHealth {
    Healthy,
    Missing,
    DigestMismatch,
    IoFailure,
    DurabilityUnknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredObjectVersion {
    pub manifest: ValidatedManifest,
    pub commit_seq: CommitSeq,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ObjectCommitReceipt {
    pub object_id: ObjectId,
    pub version_id: VersionId,
    pub operation_id: OperationId,
    pub request_hash: [u8; 32],
    pub commit_seq: CommitSeq,
    pub manifest_hash: ManifestHash,
    pub resulting_heads: BTreeSet<VersionId>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CommitLedgerEvent {
    pub seq: CommitSeq,
    pub operation_id: OperationId,
    pub object_id: ObjectId,
    pub version_id: VersionId,
    pub prior_heads_hash: [u8; 32],
    pub resulting_heads_hash: [u8; 32],
    pub previous_event_hash: Option<[u8; 32]>,
    pub event_hash: [u8; 32],
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RebuiltHeads {
    pub by_object: BTreeMap<ObjectId, BTreeSet<VersionId>>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StorageSnapshot {
    pub versions: BTreeMap<VersionId, StoredObjectVersion>,
    pub heads: BTreeMap<ObjectId, BTreeSet<VersionId>>,
    pub operations: BTreeMap<OperationId, ObjectCommitReceipt>,
    pub ledger: Vec<CommitLedgerEvent>,
}
