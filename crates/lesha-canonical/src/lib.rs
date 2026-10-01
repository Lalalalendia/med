use core::fmt;

#[derive(Clone, PartialEq, Eq)]
pub struct CanonicalAuthorityBytes(Vec<u8>);

impl CanonicalAuthorityBytes {
    pub fn validate(bytes: Vec<u8>) -> Result<Self, CanonicalError> {
        let mut cursor = 0usize;
        validate_item(&bytes, &mut cursor, 0)?;
        if cursor != bytes.len() {
            return Err(CanonicalError::TrailingBytes);
        }
        Ok(Self(bytes))
    }

    pub fn as_slice(&self) -> &[u8] {
        &self.0
    }

    pub fn into_vec(self) -> Vec<u8> {
        self.0
    }
}

impl fmt::Debug for CanonicalAuthorityBytes {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CanonicalAuthorityBytes")
            .field("len", &self.0.len())
            .finish()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CanonicalError {
    Empty,
    UnexpectedEof,
    TrailingBytes,
    IndefiniteLength,
    NonShortestInteger,
    UnsupportedSimpleValue,
    UnsupportedTag,
    FloatForbidden,
    InvalidUtf8,
    MapKeyOrder,
    DepthLimit,
    LengthOverflow,
}

const MAX_DEPTH: usize = 64;

fn validate_item(bytes: &[u8], cursor: &mut usize, depth: usize) -> Result<(), CanonicalError> {
    if depth > MAX_DEPTH {
        return Err(CanonicalError::DepthLimit);
    }
    if *cursor >= bytes.len() {
        return Err(if bytes.is_empty() {
            CanonicalError::Empty
        } else {
            CanonicalError::UnexpectedEof
        });
    }

    let head = bytes[*cursor];
    *cursor += 1;
    let major = head >> 5;
    let ai = head & 0x1f;

    match major {
        0 | 1 => {
            let _ = read_argument(bytes, cursor, ai)?;
            Ok(())
        }
        2 => {
            let len = read_argument(bytes, cursor, ai)?;
            advance(bytes, cursor, len)?;
            Ok(())
        }
        3 => {
            let len = read_argument(bytes, cursor, ai)?;
            let start = *cursor;
            advance(bytes, cursor, len)?;
            core::str::from_utf8(&bytes[start..*cursor])
                .map_err(|_| CanonicalError::InvalidUtf8)?;
            Ok(())
        }
        4 => {
            let len = read_argument(bytes, cursor, ai)?;
            let count = usize::try_from(len).map_err(|_| CanonicalError::LengthOverflow)?;
            for _ in 0..count {
                validate_item(bytes, cursor, depth + 1)?;
            }
            Ok(())
        }
        5 => {
            let len = read_argument(bytes, cursor, ai)?;
            let count = usize::try_from(len).map_err(|_| CanonicalError::LengthOverflow)?;
            let mut previous_key: Option<Vec<u8>> = None;
            for _ in 0..count {
                let key_start = *cursor;
                validate_item(bytes, cursor, depth + 1)?;
                let key = bytes[key_start..*cursor].to_vec();
                if let Some(prev) = &previous_key {
                    if prev >= &key {
                        return Err(CanonicalError::MapKeyOrder);
                    }
                }
                previous_key = Some(key);
                validate_item(bytes, cursor, depth + 1)?;
            }
            Ok(())
        }
        6 => Err(CanonicalError::UnsupportedTag),
        7 => match ai {
            20 | 21 | 22 => Ok(()),
            25 | 26 | 27 => Err(CanonicalError::FloatForbidden),
            31 => Err(CanonicalError::IndefiniteLength),
            _ => Err(CanonicalError::UnsupportedSimpleValue),
        },
        _ => unreachable!(),
    }
}

fn read_argument(bytes: &[u8], cursor: &mut usize, ai: u8) -> Result<u64, CanonicalError> {
    match ai {
        0..=23 => Ok(ai as u64),
        24 => {
            let v = read_u8(bytes, cursor)? as u64;
            if v < 24 {
                Err(CanonicalError::NonShortestInteger)
            } else {
                Ok(v)
            }
        }
        25 => {
            let v = read_be(bytes, cursor, 2)?;
            if v <= u8::MAX as u64 {
                Err(CanonicalError::NonShortestInteger)
            } else {
                Ok(v)
            }
        }
        26 => {
            let v = read_be(bytes, cursor, 4)?;
            if v <= u16::MAX as u64 {
                Err(CanonicalError::NonShortestInteger)
            } else {
                Ok(v)
            }
        }
        27 => {
            let v = read_be(bytes, cursor, 8)?;
            if v <= u32::MAX as u64 {
                Err(CanonicalError::NonShortestInteger)
            } else {
                Ok(v)
            }
        }
        31 => Err(CanonicalError::IndefiniteLength),
        _ => Err(CanonicalError::UnsupportedSimpleValue),
    }
}

fn read_u8(bytes: &[u8], cursor: &mut usize) -> Result<u8, CanonicalError> {
    if *cursor >= bytes.len() {
        return Err(CanonicalError::UnexpectedEof);
    }
    let out = bytes[*cursor];
    *cursor += 1;
    Ok(out)
}

fn read_be(bytes: &[u8], cursor: &mut usize, width: usize) -> Result<u64, CanonicalError> {
    if bytes.len().saturating_sub(*cursor) < width {
        return Err(CanonicalError::UnexpectedEof);
    }
    let mut out = 0u64;
    for _ in 0..width {
        out = (out << 8) | read_u8(bytes, cursor)? as u64;
    }
    Ok(out)
}

fn advance(bytes: &[u8], cursor: &mut usize, len: u64) -> Result<(), CanonicalError> {
    let len = usize::try_from(len).map_err(|_| CanonicalError::LengthOverflow)?;
    if bytes.len().saturating_sub(*cursor) < len {
        return Err(CanonicalError::UnexpectedEof);
    }
    *cursor += len;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_indefinite() {
        assert_eq!(
            CanonicalAuthorityBytes::validate(vec![0x9f, 0xff]),
            Err(CanonicalError::IndefiniteLength)
        );
    }

    #[test]
    fn rejects_nonshort_integer() {
        assert_eq!(
            CanonicalAuthorityBytes::validate(vec![0x18, 0x01]),
            Err(CanonicalError::NonShortestInteger)
        );
    }

    #[test]
    fn accepts_sorted_numeric_map() {
        let bytes = vec![0xa2, 0x01, 0x01, 0x02, 0x02];
        assert!(CanonicalAuthorityBytes::validate(bytes).is_ok());
    }

    #[test]
    fn rejects_unsorted_map() {
        let bytes = vec![0xa2, 0x02, 0x02, 0x01, 0x01];
        assert_eq!(
            CanonicalAuthorityBytes::validate(bytes),
            Err(CanonicalError::MapKeyOrder)
        );
    }
}
