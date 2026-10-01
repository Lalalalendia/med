use lesha_storage_core::{
    ChunkAvailability, ChunkDescriptor, ChunkHealth, ChunkStoreError, ChunkStorePort,
    StorageFailPoint,
};
use lesha_storage_files::FileChunkStore;
use lesha_types::ChunkId;
use sha2::{Digest, Sha256};
use tempfile::TempDir;

fn descriptor(bytes: &[u8]) -> ChunkDescriptor {
    let digest = Sha256::digest(bytes);
    let mut id = [0u8; 32];
    id.copy_from_slice(&digest);
    ChunkDescriptor {
        chunk_id: ChunkId(id),
        ciphertext_len: bytes.len() as u64,
    }
}

#[test]
fn chunk_publish_failpoints_are_recoverable() {
    let points = [
        StorageFailPoint::ChunkBeforeWrite,
        StorageFailPoint::ChunkAfterWriteBeforeFlush,
        StorageFailPoint::ChunkAfterFlushBeforePublish,
        StorageFailPoint::ChunkAfterPublish,
    ];

    for point in points {
        let dir = TempDir::new().unwrap();
        let bytes = b"persistent-ciphertext";
        let expected = descriptor(bytes);

        let mut store = FileChunkStore::open(dir.path()).unwrap();
        store.set_failpoint_for_test(point);
        assert_eq!(
            store.put_durable(bytes, &expected),
            Err(ChunkStoreError::Io),
            "point={point:?}"
        );
        drop(store);

        let mut reopened = FileChunkStore::open(dir.path()).unwrap();
        match point {
            StorageFailPoint::ChunkAfterPublish => {
                assert_eq!(
                    reopened.chunk_health(expected.chunk_id).unwrap(),
                    ChunkHealth::Healthy
                );
            }
            _ => {
                assert_eq!(
                    reopened.chunk_health(expected.chunk_id).unwrap(),
                    ChunkHealth::Missing
                );
            }
        }

        reopened.put_durable(bytes, &expected).unwrap();
        assert_eq!(
            reopened.chunk_health(expected.chunk_id).unwrap(),
            ChunkHealth::Healthy
        );
    }
}
