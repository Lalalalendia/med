use lesha_storage_sim::ALL_FAILPOINTS;

#[test]
fn failpoint_registry_is_unique_and_complete_for_m0() {
    let mut sorted = ALL_FAILPOINTS.to_vec();
    sorted.sort();
    sorted.dedup();
    assert_eq!(sorted.len(), 10);
}
