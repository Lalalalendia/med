use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use lesha_storage_core::{
    ChunkAvailability, ChunkDescriptor, ChunkHealth, ChunkStoreError, ChunkStorePort,
    DurableChunkReceipt, StorageFailPoint,
};
use lesha_types::ChunkId;
use sha2::{Digest, Sha256};

pub struct FileChunkStore {
    root: PathBuf,
    failpoint: Option<StorageFailPoint>,
}

impl FileChunkStore {
    pub fn open(root: impl AsRef<Path>) -> Result<Self, ChunkStoreError> {
        let root = root.as_ref().to_path_buf();
        fs::create_dir_all(root.join("chunks")).map_err(|_| ChunkStoreError::Io)?;
        fs::create_dir_all(root.join("staging")).map_err(|_| ChunkStoreError::Io)?;
        Ok(Self {
            root,
            failpoint: None,
        })
    }

    pub fn set_failpoint_for_test(&mut self, point: StorageFailPoint) {
        self.failpoint = Some(point);
    }

    fn chunks_dir(&self) -> PathBuf {
        self.root.join("chunks")
    }

    fn final_path(&self, id: ChunkId) -> PathBuf {
        self.chunks_dir().join(hex32(id.0))
    }

    fn temp_path(&self, id: ChunkId) -> PathBuf {
        self.root
            .join("staging")
            .join(format!("{}.tmp", hex32(id.0)))
    }

    fn hit(&mut self, point: StorageFailPoint) -> Result<(), ChunkStoreError> {
        if self.failpoint == Some(point) {
            self.failpoint = None;
            return Err(ChunkStoreError::Io);
        }
        Ok(())
    }
}

impl ChunkAvailability for FileChunkStore {
    fn chunk_health(&self, id: ChunkId) -> Result<ChunkHealth, ChunkStoreError> {
        let path = self.final_path(id);
        let mut file = match File::open(path) {
            Ok(file) => file,
            Err(err) if err.kind() == std::io::ErrorKind::NotFound => {
                return Ok(ChunkHealth::Missing);
            }
            Err(_) => return Ok(ChunkHealth::IoFailure),
        };
        let mut bytes = Vec::new();
        file.read_to_end(&mut bytes)
            .map_err(|_| ChunkStoreError::Io)?;
        if sha256(&bytes) == id.0 {
            Ok(ChunkHealth::Healthy)
        } else {
            Ok(ChunkHealth::DigestMismatch)
        }
    }
}

impl ChunkStorePort for FileChunkStore {
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

        let final_path = self.final_path(expected.chunk_id);
        if final_path.exists() {
            let existing = fs::read(&final_path).map_err(|_| ChunkStoreError::Io)?;
            if existing != bytes || sha256(&existing) != expected.chunk_id.0 {
                return Err(ChunkStoreError::AlreadyExistsConflict);
            }
            return Ok(DurableChunkReceipt {
                descriptor: expected.clone(),
            });
        }

        self.hit(StorageFailPoint::ChunkBeforeWrite)?;
        let temp_path = self.temp_path(expected.chunk_id);
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&temp_path)
            .map_err(|_| ChunkStoreError::Io)?;
        file.write_all(bytes).map_err(|_| ChunkStoreError::Io)?;
        self.hit(StorageFailPoint::ChunkAfterWriteBeforeFlush)?;
        file.sync_all().map_err(|_| ChunkStoreError::Io)?;
        drop(file);
        self.hit(StorageFailPoint::ChunkAfterFlushBeforePublish)?;
        fs::rename(&temp_path, &final_path).map_err(|_| ChunkStoreError::Io)?;
        self.hit(StorageFailPoint::ChunkAfterPublish)?;

        #[cfg(unix)]
        {
            File::open(self.chunks_dir())
                .and_then(|dir| dir.sync_all())
                .map_err(|_| ChunkStoreError::Io)?;
        }

        match self.chunk_health(expected.chunk_id)? {
            ChunkHealth::Healthy => Ok(DurableChunkReceipt {
                descriptor: expected.clone(),
            }),
            ChunkHealth::DigestMismatch => Err(ChunkStoreError::DigestMismatch),
            ChunkHealth::Missing | ChunkHealth::IoFailure => Err(ChunkStoreError::Io),
            ChunkHealth::DurabilityUnknown => Err(ChunkStoreError::DurabilityUnknown),
        }
    }

    fn read_verified(&self, id: ChunkId) -> Result<Vec<u8>, ChunkStoreError> {
        match self.chunk_health(id)? {
            ChunkHealth::Healthy => fs::read(self.final_path(id)).map_err(|_| ChunkStoreError::Io),
            ChunkHealth::Missing | ChunkHealth::IoFailure => Err(ChunkStoreError::Io),
            ChunkHealth::DigestMismatch => Err(ChunkStoreError::DigestMismatch),
            ChunkHealth::DurabilityUnknown => Err(ChunkStoreError::DurabilityUnknown),
        }
    }

    fn list_orphans(&self, reachable: &BTreeSet<ChunkId>) -> Result<Vec<ChunkId>, ChunkStoreError> {
        let mut out = Vec::new();
        for entry in fs::read_dir(self.chunks_dir()).map_err(|_| ChunkStoreError::Io)? {
            let entry = entry.map_err(|_| ChunkStoreError::Io)?;
            if !entry
                .file_type()
                .map_err(|_| ChunkStoreError::Io)?
                .is_file()
            {
                continue;
            }
            let name = entry.file_name();
            let Some(name) = name.to_str() else {
                continue;
            };
            let Some(bytes) = parse_hex32(name) else {
                continue;
            };
            let id = ChunkId(bytes);
            if !reachable.contains(&id) {
                out.push(id);
            }
        }
        out.sort();
        Ok(out)
    }
}

fn sha256(bytes: &[u8]) -> [u8; 32] {
    let digest = Sha256::digest(bytes);
    let mut out = [0u8; 32];
    out.copy_from_slice(&digest);
    out
}

fn hex32(bytes: [u8; 32]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(64);
    for byte in bytes {
        out.push(HEX[(byte >> 4) as usize] as char);
        out.push(HEX[(byte & 0x0f) as usize] as char);
    }
    out
}

fn parse_hex32(s: &str) -> Option<[u8; 32]> {
    if s.len() != 64 {
        return None;
    }
    let bytes = s.as_bytes();
    let mut out = [0u8; 32];
    for (i, slot) in out.iter_mut().enumerate() {
        let hi = nibble(bytes[i * 2])?;
        let lo = nibble(bytes[i * 2 + 1])?;
        *slot = (hi << 4) | lo;
    }
    Some(out)
}

fn nibble(b: u8) -> Option<u8> {
    match b {
        b'0'..=b'9' => Some(b - b'0'),
        b'a'..=b'f' => Some(b - b'a' + 10),
        _ => None,
    }
}
