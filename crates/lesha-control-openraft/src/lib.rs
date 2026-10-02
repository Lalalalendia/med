#![forbid(unsafe_code)]

use std::collections::{BTreeMap, BTreeSet};
use std::io::Cursor;
use std::sync::{Arc, RwLock};

use lesha_control_core::{
    CommittedControlReceipt, ConsensusError, ConsensusFuture, ConsensusLearnerRequest,
    ConsensusMembershipRequest, ControlConsensusPort, MembershipChangeReceipt,
    ValidatedControlCommand, VerifiedControlView,
};
use lesha_types::NodeId;

openraft::declare_raft_types!(
    pub LesHaOpenRaftConfig:
        D = ValidatedControlCommand,
        R = CommittedControlReceipt,
        NodeId = u64,
        Node = openraft::EmptyNode,
        Entry = openraft::Entry<LesHaOpenRaftConfig>,
        SnapshotData = Cursor<Vec<u8>>,
        AsyncRuntime = openraft::TokioRuntime,
);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NodeBindingError {
    LesHaNodeAlreadyBound {
        node_id: NodeId,
        existing_provider_id: u64,
    },
    ProviderIdAlreadyBound {
        provider_id: u64,
        existing_node_id: NodeId,
    },
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct OpenRaftNodeRegistry {
    by_lesha: BTreeMap<NodeId, u64>,
    by_provider: BTreeMap<u64, NodeId>,
}

impl OpenRaftNodeRegistry {
    pub fn bind(&mut self, node_id: NodeId, provider_id: u64) -> Result<(), NodeBindingError> {
        if let Some(existing_provider_id) = self.by_lesha.get(&node_id) {
            if *existing_provider_id == provider_id {
                return Ok(());
            }
            return Err(NodeBindingError::LesHaNodeAlreadyBound {
                node_id,
                existing_provider_id: *existing_provider_id,
            });
        }

        if let Some(existing_node_id) = self.by_provider.get(&provider_id) {
            if *existing_node_id == node_id {
                return Ok(());
            }
            return Err(NodeBindingError::ProviderIdAlreadyBound {
                provider_id,
                existing_node_id: *existing_node_id,
            });
        }

        self.by_lesha.insert(node_id, provider_id);
        self.by_provider.insert(provider_id, node_id);
        Ok(())
    }

    pub fn provider_id(&self, node_id: NodeId) -> Option<u64> {
        self.by_lesha.get(&node_id).copied()
    }

    pub fn lesha_node_id(&self, provider_id: u64) -> Option<NodeId> {
        self.by_provider.get(&provider_id).copied()
    }

    pub fn len(&self) -> usize {
        self.by_lesha.len()
    }

    pub fn is_empty(&self) -> bool {
        self.by_lesha.is_empty()
    }
}

pub trait ControlViewSource: Send + Sync {
    fn current_view<'a>(&'a self) -> ConsensusFuture<'a, VerifiedControlView>;
}

#[derive(Clone)]
pub struct OpenRaftConsensusAdapter<V> {
    raft: openraft::Raft<LesHaOpenRaftConfig>,
    registry: Arc<RwLock<OpenRaftNodeRegistry>>,
    view_source: Arc<V>,
}

impl<V> OpenRaftConsensusAdapter<V>
where
    V: ControlViewSource + 'static,
{
    pub fn new(
        raft: openraft::Raft<LesHaOpenRaftConfig>,
        registry: Arc<RwLock<OpenRaftNodeRegistry>>,
        view_source: Arc<V>,
    ) -> Self {
        Self {
            raft,
            registry,
            view_source,
        }
    }

    fn provider_id(&self, node_id: NodeId) -> Result<u64, ConsensusError> {
        self.registry
            .read()
            .map_err(|_| ConsensusError::Fatal)?
            .provider_id(node_id)
            .ok_or(ConsensusError::MembershipRejected)
    }

    fn lesha_node_id(&self, provider_id: u64) -> Option<NodeId> {
        self.registry
            .read()
            .ok()
            .and_then(|registry| registry.lesha_node_id(provider_id))
    }

    async fn current_authoritative_view(&self) -> Result<VerifiedControlView, ConsensusError> {
        self.raft
            .ensure_linearizable()
            .await
            .map_err(|error| self.map_raft_error(error))?;
        self.view_source.current_view().await
    }

    fn authorize(
        view: &VerifiedControlView,
        expected_control_epoch: lesha_types::ControlEpoch,
        expected_recovery_epoch: lesha_types::RecoveryEpoch,
        authorization_state_root: [u8; 32],
    ) -> Result<(), ConsensusError> {
        if view.control_epoch != expected_control_epoch
            || view.recovery_epoch != expected_recovery_epoch
            || view.state_root != authorization_state_root
        {
            return Err(ConsensusError::StaleAuthorization);
        }
        Ok(())
    }

    fn provider_voters(&self, voters: &BTreeSet<NodeId>) -> Result<BTreeSet<u64>, ConsensusError> {
        voters
            .iter()
            .map(|node_id| self.provider_id(*node_id))
            .collect()
    }

    fn map_raft_error<E>(&self, error: openraft::error::RaftError<u64, E>) -> ConsensusError {
        match error {
            openraft::error::RaftError::Fatal(_) => ConsensusError::Fatal,
            openraft::error::RaftError::APIError(_) => ConsensusError::ProviderUnavailable,
        }
    }

    async fn enrich_provider_error(&self, fallback: ConsensusError) -> ConsensusError {
        match self.raft.current_leader().await {
            Some(provider_id) => ConsensusError::NotLeader {
                leader_hint: self.lesha_node_id(provider_id),
            },
            None => fallback,
        }
    }
}

impl<V> ControlConsensusPort for OpenRaftConsensusAdapter<V>
where
    V: ControlViewSource + 'static,
{
    fn propose<'a>(
        &'a self,
        cmd: ValidatedControlCommand,
    ) -> ConsensusFuture<'a, CommittedControlReceipt> {
        Box::pin(async move {
            match self.raft.client_write(cmd).await {
                Ok(response) => Ok(response.data),
                Err(error) => {
                    let mapped = self.map_raft_error(error);
                    match mapped {
                        ConsensusError::ProviderUnavailable => Err(self
                            .enrich_provider_error(ConsensusError::QuorumUnavailable)
                            .await),
                        other => Err(other),
                    }
                }
            }
        })
    }

    fn linearizable_view<'a>(&'a self) -> ConsensusFuture<'a, VerifiedControlView> {
        Box::pin(async move {
            match self.current_authoritative_view().await {
                Ok(view) => Ok(view),
                Err(ConsensusError::ProviderUnavailable) => Err(self
                    .enrich_provider_error(ConsensusError::QuorumUnavailable)
                    .await),
                Err(other) => Err(other),
            }
        })
    }

    fn add_learner<'a>(
        &'a self,
        request: ConsensusLearnerRequest,
    ) -> ConsensusFuture<'a, MembershipChangeReceipt> {
        Box::pin(async move {
            let view = self.current_authoritative_view().await?;
            Self::authorize(
                &view,
                request.expected_control_epoch,
                request.expected_recovery_epoch,
                request.authorization_state_root,
            )?;

            if view.revoked_nodes.contains(&request.node.node_id) {
                return Err(ConsensusError::MembershipRejected);
            }

            let provider_id = self.provider_id(request.node.node_id)?;
            if let Err(error) = self
                .raft
                .add_learner(provider_id, openraft::EmptyNode::new(), true)
                .await
            {
                let mapped = self.map_raft_error(error);
                return match mapped {
                    ConsensusError::ProviderUnavailable => Err(self
                        .enrich_provider_error(ConsensusError::MembershipRejected)
                        .await),
                    other => Err(other),
                };
            }

            Ok(MembershipChangeReceipt {
                voters: view.voters,
                control_epoch: view.control_epoch,
                recovery_epoch: view.recovery_epoch,
                authorization_state_root: view.state_root,
            })
        })
    }

    fn change_membership<'a>(
        &'a self,
        request: ConsensusMembershipRequest,
    ) -> ConsensusFuture<'a, MembershipChangeReceipt> {
        Box::pin(async move {
            let view = self.current_authoritative_view().await?;
            Self::authorize(
                &view,
                request.expected_control_epoch,
                request.expected_recovery_epoch,
                request.authorization_state_root,
            )?;

            if request.voters.is_empty()
                || request
                    .voters
                    .iter()
                    .any(|node_id| view.revoked_nodes.contains(node_id))
            {
                return Err(ConsensusError::MembershipRejected);
            }

            let provider_voters = self.provider_voters(&request.voters)?;
            if let Err(error) = self.raft.change_membership(provider_voters, true).await {
                let mapped = self.map_raft_error(error);
                return match mapped {
                    ConsensusError::ProviderUnavailable => Err(self
                        .enrich_provider_error(ConsensusError::MembershipRejected)
                        .await),
                    other => Err(other),
                };
            }

            Ok(MembershipChangeReceipt {
                voters: request.voters,
                control_epoch: view.control_epoch,
                recovery_epoch: view.recovery_epoch,
                authorization_state_root: view.state_root,
            })
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn node(tag: u8) -> NodeId {
        NodeId([tag; 32])
    }

    fn assert_raft_type_config<C: openraft::RaftTypeConfig>() {}

    #[test]
    fn openraft_type_config_compiles_behind_adapter_crate() {
        assert_raft_type_config::<LesHaOpenRaftConfig>();
    }

    #[test]
    fn provider_node_id_mapping_is_explicit_and_bijective() {
        let mut registry = OpenRaftNodeRegistry::default();

        registry.bind(node(1), 101).unwrap();
        registry.bind(node(2), 202).unwrap();

        assert_eq!(registry.provider_id(node(1)), Some(101));
        assert_eq!(registry.provider_id(node(2)), Some(202));
        assert_eq!(registry.lesha_node_id(101), Some(node(1)));
        assert_eq!(registry.lesha_node_id(202), Some(node(2)));
        assert_eq!(registry.len(), 2);
    }

    #[test]
    fn provider_mapping_rejects_implicit_rebinding_or_collision() {
        let mut registry = OpenRaftNodeRegistry::default();
        registry.bind(node(1), 101).unwrap();

        assert_eq!(
            registry.bind(node(1), 202),
            Err(NodeBindingError::LesHaNodeAlreadyBound {
                node_id: node(1),
                existing_provider_id: 101
            })
        );
        assert_eq!(
            registry.bind(node(2), 101),
            Err(NodeBindingError::ProviderIdAlreadyBound {
                provider_id: 101,
                existing_node_id: node(1)
            })
        );
    }

    #[test]
    fn authorization_requires_exact_epoch_and_state_root() {
        let view = VerifiedControlView {
            cluster_id: lesha_types::ClusterId([1; 16]),
            applied_index: lesha_types::ControlAppliedIndex(3),
            control_epoch: lesha_types::ControlEpoch(4),
            recovery_epoch: lesha_types::RecoveryEpoch(2),
            state_root: [9; 32],
            voters: BTreeSet::new(),
            learners: BTreeSet::new(),
            revoked_nodes: BTreeSet::new(),
        };

        assert_eq!(
            OpenRaftConsensusAdapter::<NeverView>::authorize(
                &view,
                lesha_types::ControlEpoch(4),
                lesha_types::RecoveryEpoch(2),
                [9; 32],
            ),
            Ok(())
        );
        assert_eq!(
            OpenRaftConsensusAdapter::<NeverView>::authorize(
                &view,
                lesha_types::ControlEpoch(3),
                lesha_types::RecoveryEpoch(2),
                [9; 32],
            ),
            Err(ConsensusError::StaleAuthorization)
        );
    }

    struct NeverView;

    impl ControlViewSource for NeverView {
        fn current_view<'a>(&'a self) -> ConsensusFuture<'a, VerifiedControlView> {
            Box::pin(async { Err(ConsensusError::Fatal) })
        }
    }

    #[test]
    fn exact_rebind_is_idempotent() {
        let mut registry = OpenRaftNodeRegistry::default();
        registry.bind(node(1), 101).unwrap();
        registry.bind(node(1), 101).unwrap();
        assert_eq!(registry.len(), 1);
    }
}
