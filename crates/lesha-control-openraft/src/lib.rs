#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::io::Cursor;

use lesha_control_core::{CommittedControlReceipt, ValidatedControlCommand};
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
    fn exact_rebind_is_idempotent() {
        let mut registry = OpenRaftNodeRegistry::default();
        registry.bind(node(1), 101).unwrap();
        registry.bind(node(1), 101).unwrap();
        assert_eq!(registry.len(), 1);
    }
}
