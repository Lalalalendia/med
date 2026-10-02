use crate::{
    ChunkDescriptor, ChunkStoreError, ChunkStorePort, CommitError, ObjectCommitPort,
    ObjectCommitReceipt, ValidatedObjectCommit,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StagedChunkRef {
    pub descriptor: ChunkDescriptor,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ValidatedImportedVersion {
    commit: ValidatedObjectCommit,
}

impl ValidatedImportedVersion {
    pub fn new_prevalidated(commit: ValidatedObjectCommit) -> Self {
        Self { commit }
    }

    pub fn commit(&self) -> &ValidatedObjectCommit {
        &self.commit
    }

    pub fn into_commit(self) -> ValidatedObjectCommit {
        self.commit
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ImportReceipt {
    pub commit: ObjectCommitReceipt,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ImportError {
    Chunk(ChunkStoreError),
    Commit(CommitError),
}

pub trait ImportPort {
    fn stage_verified_chunk(
        &mut self,
        bytes: &[u8],
        expected: &ChunkDescriptor,
    ) -> Result<StagedChunkRef, ImportError>;

    fn import_version(
        &mut self,
        version: ValidatedImportedVersion,
    ) -> Result<ImportReceipt, ImportError>;
}

pub struct LocalStorageImportAdapter<'a, C, O> {
    chunks: &'a mut C,
    objects: &'a mut O,
}

impl<'a, C, O> LocalStorageImportAdapter<'a, C, O> {
    pub fn new(chunks: &'a mut C, objects: &'a mut O) -> Self {
        Self { chunks, objects }
    }
}

impl<C, O> ImportPort for LocalStorageImportAdapter<'_, C, O>
where
    C: ChunkStorePort,
    O: ObjectCommitPort,
{
    fn stage_verified_chunk(
        &mut self,
        bytes: &[u8],
        expected: &ChunkDescriptor,
    ) -> Result<StagedChunkRef, ImportError> {
        let receipt = self
            .chunks
            .put_durable(bytes, expected)
            .map_err(ImportError::Chunk)?;

        Ok(StagedChunkRef {
            descriptor: receipt.descriptor,
        })
    }

    fn import_version(
        &mut self,
        version: ValidatedImportedVersion,
    ) -> Result<ImportReceipt, ImportError> {
        let commit = self
            .objects
            .commit(&*self.chunks, version.into_commit())
            .map_err(ImportError::Commit)?;

        Ok(ImportReceipt { commit })
    }
}
