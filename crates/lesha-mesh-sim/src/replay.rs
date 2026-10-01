use crate::EventTrace;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct ReplayMismatch {
    pub record_index: usize,
    pub expected: Option<String>,
    pub actual: Option<String>,
}

pub fn verify_exact_replay(
    expected: &EventTrace,
    actual: &EventTrace,
) -> Result<(), ReplayMismatch> {
    let max = expected.records.len().max(actual.records.len());
    for index in 0..max {
        let left = expected.records.get(index);
        let right = actual.records.get(index);
        if left != right {
            return Err(ReplayMismatch {
                record_index: index,
                expected: left.map(|record| format!("{record:?}")),
                actual: right.map(|record| format!("{record:?}")),
            });
        }
    }
    Ok(())
}
