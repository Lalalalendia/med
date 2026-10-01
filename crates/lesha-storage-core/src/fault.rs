#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum StorageFailPoint {
    ChunkBeforeWrite,
    ChunkAfterWriteBeforeFlush,
    ChunkAfterFlushBeforePublish,
    ChunkAfterPublish,
    MetadataBeforeBegin,
    MetadataAfterManifest,
    MetadataAfterLedger,
    MetadataAfterHeads,
    MetadataBeforeCommit,
    MetadataAfterCommitBeforeReply,
}

pub const ALL_STORAGE_FAILPOINTS: [StorageFailPoint; 10] = [
    StorageFailPoint::ChunkBeforeWrite,
    StorageFailPoint::ChunkAfterWriteBeforeFlush,
    StorageFailPoint::ChunkAfterFlushBeforePublish,
    StorageFailPoint::ChunkAfterPublish,
    StorageFailPoint::MetadataBeforeBegin,
    StorageFailPoint::MetadataAfterManifest,
    StorageFailPoint::MetadataAfterLedger,
    StorageFailPoint::MetadataAfterHeads,
    StorageFailPoint::MetadataBeforeCommit,
    StorageFailPoint::MetadataAfterCommitBeforeReply,
];
