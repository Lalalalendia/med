use sha2::{Digest, Sha256};

use crate::CanonicalAuthorityBytes;

pub fn sha256_domain(domain: &[u8], value: &CanonicalAuthorityBytes) -> [u8; 32] {
    let mut hasher = Sha256::new();
    hasher.update(domain);
    hasher.update((value.as_slice().len() as u64).to_be_bytes());
    hasher.update(value.as_slice());
    digest32(hasher.finalize())
}

fn digest32(bytes: impl AsRef<[u8]>) -> [u8; 32] {
    let bytes = bytes.as_ref();
    let mut out = [0u8; 32];
    out.copy_from_slice(bytes);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::CanonicalWriter;

    #[test]
    fn domain_separation_changes_digest() {
        let mut writer = CanonicalWriter::new();
        writer.array(1);
        writer.unsigned(7);
        let value = writer.finish();

        assert_ne!(
            sha256_domain(b"LesHa/Test/A/M0\0", &value),
            sha256_domain(b"LesHa/Test/B/M0\0", &value)
        );
    }
}
