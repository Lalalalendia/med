use std::collections::BTreeSet;

use lesha_types::{CommitSeq, ObjectId, OperationId, VersionId};
use sha2::{Digest, Sha256};

pub fn hash_heads(heads: &BTreeSet<VersionId>) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"LesHa/HeadSet/M0\0");
    h.update((heads.len() as u64).to_be_bytes());
    for id in heads {
        h.update(id.0);
    }
    digest32(h.finalize())
}

pub fn hash_commit_event(
    seq: CommitSeq,
    operation_id: OperationId,
    object_id: ObjectId,
    version_id: VersionId,
    prior_heads_hash: [u8; 32],
    resulting_heads_hash: [u8; 32],
    previous_event_hash: Option<[u8; 32]>,
) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"LesHa/CommitLedgerEvent/M0\0");
    h.update(seq.0.to_be_bytes());
    h.update(operation_id.0);
    h.update(object_id.0);
    h.update(version_id.0);
    h.update(prior_heads_hash);
    h.update(resulting_heads_hash);
    h.update(previous_event_hash.unwrap_or([0u8; 32]));
    digest32(h.finalize())
}

fn digest32(bytes: impl AsRef<[u8]>) -> [u8; 32] {
    let bytes = bytes.as_ref();
    let mut out = [0u8; 32];
    out.copy_from_slice(bytes);
    out
}
