use lesha_types::MonotonicTime;

#[derive(Debug, Clone, Copy, Eq, PartialEq)]
pub struct VirtualClock {
    now: MonotonicTime,
}

impl VirtualClock {
    pub fn new() -> Self {
        Self { now: MonotonicTime(0) }
    }

    pub fn now(&self) -> MonotonicTime {
        self.now
    }

    pub fn advance_to(&mut self, at: MonotonicTime) {
        assert!(at >= self.now, "virtual time cannot move backwards");
        self.now = at;
    }
}

impl Default for VirtualClock {
    fn default() -> Self {
        Self::new()
    }
}
