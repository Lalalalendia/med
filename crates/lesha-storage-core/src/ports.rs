use std::collections::{BTreeMap, BTreeSet};

use lesha_types::{ChunkId, ObjectId, OperationId, VersionId};

use crate::{
    ChunkDescriptor, ChunkHealth, ChunkStoreError, CommitError, DurableChunkReceipt,
    ObjectCommitReceipt, ReadError, RebuildError, StoredObjectVersion, ValidatedObjectCommit,
};

pub trait ChunkAvailability {
    fn chunk_health(&self, id: ChunkId) -> Result<ChunkHealth, ChunkStoreError>;
}

pub trait ChunkStorePort: ChunkAvailability {
    fn put_durable(
        &mut self,
        bytes: &[u8],
        expected: &ChunkDescriptor,
    ) -> Result<DurableChunkReceipt, ChunkStoreError>;

    fn read_verified(&self, id: ChunkId) -> Result<Vec<u8>, ChunkStoreError>;

    fn list_orphans(&self, reachable: &BTreeSet<ChunkId>) -> Result<Vec<ChunkId>, ChunkStoreError>;
}

pub trait ObjectCommitPort {
    fn commit(
        &mut self,
        chunks: &dyn ChunkAvailability,
        cmd: ValidatedObjectCommit,
    ) -> Result<ObjectCommitReceipt, CommitError>;

    fn heads(&self, object: ObjectId) -> Result<BTreeSet<VersionId>, ReadError>;

    fn version(&self, version: VersionId) -> Result<StoredObjectVersion, ReadError>;

    fn operation(&self, op: OperationId) -> Result<Option<ObjectCommitReceipt>, ReadError>;

    fn rebuild_heads(&self) -> Result<BTreeMap<ObjectId, BTreeSet<VersionId>>, RebuildError>;
}
