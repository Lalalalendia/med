use std::collections::{BTreeMap, BTreeSet};

use lesha_storage_core::{
    hash_commit_event, hash_heads, ChunkAvailability, ChunkDescriptor, ChunkHealth,
    ChunkStoreError, ChunkStorePort, CommitConsistency, CommitError, CommitLedgerEvent,
    DurableChunkReceipt, ObjectCommitPort, ObjectCommitReceipt, ReadError, RebuildError,
    StorageSnapshot, StoredObjectVersion, ValidatedObjectCommit,
};
use lesha_types::{ChunkId, CommitSeq, ObjectId, OperationId, VersionId};
use sha2::{Digest, Sha256};

#[derive(Clone, Debug, Default)]
pub struct MemoryChunkStore {
    chunks: BTreeMap<ChunkId, Vec<u8>>,
}

impl MemoryChunkStore {
    pub fn corrupt_for_test(&mut self, id: ChunkId) -> bool {
        if let Some(bytes) = self.chunks.get_mut(&id) {
            if let Some(first) = bytes.first_mut() {
                *first ^= 0x80;
            } else {
                bytes.push(0x80);
            }
            true
        } else {
            false
        }
    }
}

impl ChunkAvailability for MemoryChunkStore {
    fn chunk_health(&self, id: ChunkId) -> Result<ChunkHealth, ChunkStoreError> {
        let Some(bytes) = self.chunks.get(&id) else {
            return Ok(ChunkHealth::Missing);
        };
        let digest = sha256(bytes);
        if digest == id.0 {
            Ok(ChunkHealth::Healthy)
        } else {
            Ok(ChunkHealth::DigestMismatch)
        }
    }
}

impl ChunkStorePort for MemoryChunkStore {
    fn put_durable(
        &mut self,
        bytes: &[u8],
        expected: &ChunkDescriptor,
    ) -> Result<DurableChunkReceipt, ChunkStoreError> {
        if bytes.len() as u64 != expected.ciphertext_len {
            return Err(ChunkStoreError::DescriptorMismatch);
        }
        if sha256(bytes) != expected.chunk_id.0 {
            return Err(ChunkStoreError::DigestMismatch);
        }
        if let Some(existing) = self.chunks.get(&expected.chunk_id) {
            if existing != bytes {
                return Err(ChunkStoreError::AlreadyExistsConflict);
            }
        } else {
            self.chunks.insert(expected.chunk_id, bytes.to_vec());
        }
        Ok(DurableChunkReceipt {
            descriptor: expected.clone(),
        })
    }

    fn read_verified(&self, id: ChunkId) -> Result<Vec<u8>, ChunkStoreError> {
        match self.chunk_health(id)? {
            ChunkHealth::Healthy => Ok(self.chunks.get(&id).expect("health checked").clone()),
            ChunkHealth::Missing => Err(ChunkStoreError::Io),
            ChunkHealth::DigestMismatch => Err(ChunkStoreError::DigestMismatch),
            ChunkHealth::IoFailure => Err(ChunkStoreError::Io),
            ChunkHealth::DurabilityUnknown => Err(ChunkStoreError::DurabilityUnknown),
        }
    }

    fn list_orphans(&self, reachable: &BTreeSet<ChunkId>) -> Result<Vec<ChunkId>, ChunkStoreError> {
        Ok(self
            .chunks
            .keys()
            .filter(|id| !reachable.contains(id))
            .copied()
            .collect())
    }
}

#[derive(Clone, Debug, Default)]
pub struct MemoryObjectStore {
    versions: BTreeMap<VersionId, StoredObjectVersion>,
    heads: BTreeMap<ObjectId, BTreeSet<VersionId>>,
    operations: BTreeMap<OperationId, ObjectCommitReceipt>,
    ledger: Vec<CommitLedgerEvent>,
}

impl MemoryObjectStore {
    pub fn snapshot(&self) -> StorageSnapshot {
        StorageSnapshot {
            versions: self.versions.clone(),
            heads: self.heads.clone(),
            operations: self.operations.clone(),
            ledger: self.ledger.clone(),
        }
    }
}

impl ObjectCommitPort for MemoryObjectStore {
    fn commit(
        &mut self,
        chunks: &dyn ChunkAvailability,
        cmd: ValidatedObjectCommit,
    ) -> Result<ObjectCommitReceipt, CommitError> {
        let semantic = &cmd.manifest.semantic;

        if let Some(existing) = self.operations.get(&semantic.operation_id) {
            if existing.request_hash == cmd.request_hash {
                return Ok(existing.clone());
            }
            return Err(CommitError::IdempotencyConflict);
        }

        if self.versions.contains_key(&semantic.version_id) {
            return Err(CommitError::VersionAlreadyExists);
        }

        for chunk in &semantic.chunks {
            match chunks.chunk_health(chunk.descriptor.chunk_id) {
                Ok(ChunkHealth::Healthy) => {}
                Ok(ChunkHealth::Missing) => {
                    return Err(CommitError::MissingChunk(chunk.descriptor.chunk_id));
                }
                Ok(ChunkHealth::DigestMismatch) => {
                    return Err(CommitError::CorruptChunk(chunk.descriptor.chunk_id));
                }
                Ok(ChunkHealth::DurabilityUnknown) => return Err(CommitError::DurabilityUnknown),
                Ok(ChunkHealth::IoFailure) | Err(_) => return Err(CommitError::StorageUnavailable),
            }
        }

        let current_heads = self
            .heads
            .get(&semantic.object_id)
            .cloned()
            .unwrap_or_default();
        if current_heads != cmd.expected_heads {
            return Err(CommitError::HeadSetChanged {
                expected: cmd.expected_heads,
                actual: current_heads,
            });
        }

        let parent_set: BTreeSet<VersionId> = semantic.parents.iter().copied().collect();
        if parent_set.len() != semantic.parents.len() {
            return Err(CommitError::ManifestMismatch);
        }
        for parent in &parent_set {
            let Some(stored_parent) = self.versions.get(parent) else {
                return Err(CommitError::ParentMissing(*parent));
            };
            if stored_parent.manifest.semantic.object_id != semantic.object_id {
                return Err(CommitError::ManifestMismatch);
            }
        }

        match cmd.consistency {
            CommitConsistency::StrictSingleHead => {
                if current_heads.len() > 1 || parent_set != current_heads {
                    return Err(CommitError::StrictConflict);
                }
            }
            CommitConsistency::MergeableBranch => {}
            CommitConsistency::MergeResolution => {
                if current_heads.len() < 2 || parent_set != current_heads {
                    return Err(CommitError::StrictConflict);
                }
            }
        }

        let mut resulting_heads = current_heads.clone();
        for parent in &parent_set {
            resulting_heads.remove(parent);
        }
        resulting_heads.insert(semantic.version_id);

        let seq = CommitSeq(self.ledger.last().map(|e| e.seq.0 + 1).unwrap_or(1));
        let prior_heads_hash = hash_heads(&current_heads);
        let resulting_heads_hash = hash_heads(&resulting_heads);
        let previous_event_hash = self.ledger.last().map(|e| e.event_hash);
        let event_hash = hash_commit_event(
            seq,
            semantic.operation_id,
            semantic.object_id,
            semantic.version_id,
            prior_heads_hash,
            resulting_heads_hash,
            previous_event_hash,
        );

        let stored = StoredObjectVersion {
            manifest: cmd.manifest.clone(),
            commit_seq: seq,
        };
        let receipt = ObjectCommitReceipt {
            object_id: semantic.object_id,
            version_id: semantic.version_id,
            operation_id: semantic.operation_id,
            request_hash: cmd.request_hash,
            commit_seq: seq,
            manifest_hash: cmd.manifest.manifest_hash,
            resulting_heads: resulting_heads.clone(),
        };
        let event = CommitLedgerEvent {
            seq,
            operation_id: semantic.operation_id,
            object_id: semantic.object_id,
            version_id: semantic.version_id,
            prior_heads_hash,
            resulting_heads_hash,
            previous_event_hash,
            event_hash,
        };

        self.versions.insert(semantic.version_id, stored);
        self.heads.insert(semantic.object_id, resulting_heads);
        self.ledger.push(event);
        self.operations
            .insert(semantic.operation_id, receipt.clone());

        Ok(receipt)
    }

    fn heads(&self, object: ObjectId) -> Result<BTreeSet<VersionId>, ReadError> {
        Ok(self.heads.get(&object).cloned().unwrap_or_default())
    }

    fn version(&self, version: VersionId) -> Result<StoredObjectVersion, ReadError> {
        self.versions
            .get(&version)
            .cloned()
            .ok_or(ReadError::NotFound)
    }

    fn operation(&self, op: OperationId) -> Result<Option<ObjectCommitReceipt>, ReadError> {
        Ok(self.operations.get(&op).cloned())
    }

    fn rebuild_heads(&self) -> Result<BTreeMap<ObjectId, BTreeSet<VersionId>>, RebuildError> {
        Ok(lesha_storage_core::rebuild_heads_from_versions(
            &self.versions,
        ))
    }
}

fn sha256(bytes: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(bytes);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}
