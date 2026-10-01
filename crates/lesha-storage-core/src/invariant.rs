use std::collections::{BTreeMap, BTreeSet};

use lesha_types::{ChunkId, ObjectId, VersionId};

use crate::{ChunkAvailability, ChunkHealth, InvariantError, StorageSnapshot};

pub fn reachable_chunks(snapshot: &StorageSnapshot) -> BTreeSet<ChunkId> {
    let mut out = BTreeSet::new();
    for version in snapshot.versions.values() {
        for chunk in &version.manifest.semantic.chunks {
            out.insert(chunk.descriptor.chunk_id);
        }
    }
    out
}

pub fn check_snapshot_invariants(
    snapshot: &StorageSnapshot,
    chunks: &dyn ChunkAvailability,
) -> Result<(), InvariantError> {
    for heads in snapshot.heads.values() {
        for version_id in heads {
            if !snapshot.versions.contains_key(version_id) {
                return Err(InvariantError::HeadMissingVersion(*version_id));
            }
        }
    }

    for stored in snapshot.versions.values() {
        for chunk in &stored.manifest.semantic.chunks {
            match chunks.chunk_health(chunk.descriptor.chunk_id) {
                Ok(ChunkHealth::Healthy) => {}
                _ => {
                    return Err(InvariantError::ReachableVersionMissingChunk(
                        chunk.descriptor.chunk_id,
                    ));
                }
            }
        }
    }

    for receipt in snapshot.operations.values() {
        if !snapshot.versions.contains_key(&receipt.version_id) {
            return Err(InvariantError::OperationReceiptMissingVersion(
                receipt.version_id,
            ));
        }
    }

    let mut previous_seq = 0u64;
    let mut previous_hash: Option<[u8; 32]> = None;
    for event in &snapshot.ledger {
        if event.seq.0 != previous_seq + 1 {
            return Err(InvariantError::LedgerSequenceGap);
        }
        if event.previous_event_hash != previous_hash {
            return Err(InvariantError::LedgerHashLinkMismatch);
        }
        previous_seq = event.seq.0;
        previous_hash = Some(event.event_hash);
    }

    let rebuilt = rebuild_heads_from_versions(&snapshot.versions);
    if rebuilt != snapshot.heads {
        return Err(InvariantError::ProjectionMismatch);
    }

    Ok(())
}

pub fn rebuild_heads_from_versions(
    versions: &BTreeMap<VersionId, crate::StoredObjectVersion>,
) -> BTreeMap<ObjectId, BTreeSet<VersionId>> {
    let mut by_object: BTreeMap<ObjectId, BTreeSet<VersionId>> = BTreeMap::new();
    let mut parent_ids: BTreeMap<ObjectId, BTreeSet<VersionId>> = BTreeMap::new();

    for (version_id, stored) in versions {
        let object = stored.manifest.semantic.object_id;
        by_object.entry(object).or_default().insert(*version_id);
        let parents = parent_ids.entry(object).or_default();
        for parent in &stored.manifest.semantic.parents {
            parents.insert(*parent);
        }
    }

    for (object, parents) in parent_ids {
        if let Some(candidates) = by_object.get_mut(&object) {
            for parent in parents {
                candidates.remove(&parent);
            }
        }
    }

    by_object
}
