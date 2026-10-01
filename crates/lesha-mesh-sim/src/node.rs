use lesha_peer_core::{step, CoreConfig, CoreEvent, PeerManagerStateM0, StepOutput};

#[derive(Debug)]
pub struct SimNode {
    pub state: PeerManagerStateM0,
    pub config: CoreConfig,
    pub trace_seq: u64,
}

impl SimNode {
    pub fn apply(&mut self, event: CoreEvent) -> StepOutput {
        self.trace_seq = self.trace_seq.saturating_add(1);
        step(&self.config, &mut self.state, event)
    }
}
