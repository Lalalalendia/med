use lesha_types::MonoDuration;

#[derive(Debug, Clone, Eq, PartialEq)]
pub struct CoreConfig {
    pub probe_interval: MonoDuration,
    pub probe_timeout: MonoDuration,
    pub suspicion_timeout: MonoDuration,
    pub max_sessions: u16,
    pub max_pending_probes: u16,
    pub max_effects_per_step: u16,
    pub require_current_control_for_data: bool,
}

impl Default for CoreConfig {
    fn default() -> Self {
        Self {
            probe_interval: MonoDuration(1_000),
            probe_timeout: MonoDuration(300),
            suspicion_timeout: MonoDuration(1_000),
            max_sessions: 8,
            max_pending_probes: 8,
            max_effects_per_step: 32,
            require_current_control_for_data: true,
        }
    }
}
