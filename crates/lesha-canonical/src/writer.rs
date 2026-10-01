use crate::CanonicalAuthorityBytes;

#[derive(Debug, Default)]
pub struct CanonicalWriter {
    bytes: Vec<u8>,
}

impl CanonicalWriter {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn unsigned(&mut self, value: u64) {
        self.write_head(0, value);
    }

    pub fn bytes(&mut self, value: &[u8]) {
        self.write_head(2, value.len() as u64);
        self.bytes.extend_from_slice(value);
    }

    pub fn array(&mut self, len: usize) {
        self.write_head(4, len as u64);
    }

    pub fn boolean(&mut self, value: bool) {
        self.bytes.push(if value { 0xf5 } else { 0xf4 });
    }

    pub fn null(&mut self) {
        self.bytes.push(0xf6);
    }

    pub fn finish(self) -> CanonicalAuthorityBytes {
        CanonicalAuthorityBytes::validate(self.bytes)
            .expect("CanonicalWriter emitted non-canonical CBOR")
    }

    fn write_head(&mut self, major: u8, value: u64) {
        let prefix = major << 5;
        match value {
            0..=23 => self.bytes.push(prefix | value as u8),
            24..=0xff => {
                self.bytes.push(prefix | 24);
                self.bytes.push(value as u8);
            }
            0x100..=0xffff => {
                self.bytes.push(prefix | 25);
                self.bytes.extend_from_slice(&(value as u16).to_be_bytes());
            }
            0x1_0000..=0xffff_ffff => {
                self.bytes.push(prefix | 26);
                self.bytes.extend_from_slice(&(value as u32).to_be_bytes());
            }
            _ => {
                self.bytes.push(prefix | 27);
                self.bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn writer_uses_shortest_unsigned_forms() {
        let mut w = CanonicalWriter::new();
        w.array(4);
        w.unsigned(23);
        w.unsigned(24);
        w.unsigned(256);
        w.unsigned(u64::MAX);
        assert_eq!(
            w.finish().as_slice(),
            &[
                0x84, 0x17, 0x18, 0x18, 0x19, 0x01, 0x00, 0x1b, 0xff, 0xff, 0xff, 0xff, 0xff,
                0xff, 0xff, 0xff,
            ]
        );
    }

    #[test]
    fn writer_emits_canonical_bytes_arrays_and_bools() {
        let mut w = CanonicalWriter::new();
        w.array(4);
        w.bytes(&[1, 2, 3]);
        w.boolean(false);
        w.boolean(true);
        w.null();
        assert!(CanonicalAuthorityBytes::validate(w.finish().into_vec()).is_ok());
    }
}
