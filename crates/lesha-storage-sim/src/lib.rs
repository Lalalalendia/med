pub use lesha_storage_core::{
    StorageFailPoint as FailPoint, ALL_STORAGE_FAILPOINTS as ALL_FAILPOINTS,
};

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum InjectedFailure {
    ProcessCrash,
    IoError,
    DiskFull,
    LostReply,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FaultPlan {
    pub point: FailPoint,
    pub failure: InjectedFailure,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunManifest {
    pub scenario: &'static str,
    pub fault: Option<FaultPlan>,
    pub seed: u64,
}
