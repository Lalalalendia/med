use lesha_types::NodeRef;

use crate::state::ProbeId;

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub enum TimerKey {
    ProbeInterval(NodeRef),
    ProbeDeadline(ProbeId),
    SuspicionDeadline(NodeRef),
    Maintenance,
    Exploration,
}

#[derive(Debug, Clone, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct TimerId {
    pub key: TimerKey,
    pub generation: u64,
}
