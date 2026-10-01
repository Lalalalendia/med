use std::collections::BTreeSet;

use lesha_types::{ChunkId, VersionId};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ChunkStoreError {
    DescriptorMismatch,
    DigestMismatch,
    AlreadyExistsConflict,
    Io,
    DurabilityUnknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CommitError {
    MissingChunk(ChunkId),
    CorruptChunk(ChunkId),
    IdempotencyConflict,
    HeadSetChanged {
        expected: BTreeSet<VersionId>,
        actual: BTreeSet<VersionId>,
    },
    ParentMissing(VersionId),
    StrictConflict,
    ManifestMismatch,
    VersionAlreadyExists,
    StorageUnavailable,
    DurabilityUnknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReadError {
    NotFound,
    StorageUnavailable,
    Corrupt,
    DurabilityUnknown,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RebuildError {
    MissingVersion(VersionId),
    LedgerInconsistent,
    StorageUnavailable,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InvariantError {
    HeadMissingVersion(VersionId),
    ReachableVersionMissingChunk(ChunkId),
    OperationReceiptMissingVersion(VersionId),
    LedgerSequenceGap,
    LedgerHashLinkMismatch,
    ProjectionMismatch,
}
