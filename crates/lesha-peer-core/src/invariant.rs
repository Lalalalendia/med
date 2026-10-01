use crate::effect::{CoreEffect, CoreEffectKind};
use crate::event::CoreEvent;
use crate::state::{LifecycleState, PeerManagerStateM0};

#[derive(Debug, Clone, Eq, PartialEq)]
pub enum InvariantViolation {
    NetworkEffectBeforeActivation,
    MembershipChangedByNonControlEvent,
}

pub fn check_no_network_before_activation(
    before: &PeerManagerStateM0,
    effects: &[CoreEffect],
) -> Result<(), InvariantViolation> {
    if before.lifecycle == LifecycleState::NetworkActive {
        return Ok(());
    }
    let network_effect = effects.iter().any(|effect| {
        matches!(
            &effect.kind,
            CoreEffectKind::SendMeshMessage { .. } | CoreEffectKind::CloseSession { .. }
        )
    });
    if network_effect {
        Err(InvariantViolation::NetworkEffectBeforeActivation)
    } else {
        Ok(())
    }
}

pub fn check_membership_immutable_for_non_control(
    before: &PeerManagerStateM0,
    event: &CoreEvent,
    after: &PeerManagerStateM0,
) -> Result<(), InvariantViolation> {
    use crate::event::CoreEventKind;
    if matches!(&event.kind, CoreEventKind::ControlViewReplaced { .. }) {
        return Ok(());
    }
    if before.control == after.control {
        Ok(())
    } else {
        Err(InvariantViolation::MembershipChangedByNonControlEvent)
    }
}
