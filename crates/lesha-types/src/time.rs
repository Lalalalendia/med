#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct MonotonicTime(pub u64);

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct MonoDuration(pub u64);

impl MonotonicTime {
    pub fn checked_add(self, duration: MonoDuration) -> Option<Self> {
        self.0.checked_add(duration.0).map(Self)
    }
}
