use crate::{ClusterId, NodeGeneration, NodeId};

#[derive(Debug, Clone, Copy, Eq, PartialEq, Ord, PartialOrd, Hash)]
pub struct NodeRef {
    pub cluster_id: ClusterId,
    pub node_id: NodeId,
    pub generation: NodeGeneration,
}
