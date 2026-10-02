use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct FactKey(pub String);

impl From<&str> for FactKey {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Observation {
    pub value: String,
    pub source: String,
    pub authority_weight: u32,
}

impl Observation {
    pub fn new(value: impl Into<String>, source: impl Into<String>, authority_weight: u32) -> Self {
        Self {
            value: value.into(),
            source: source.into(),
            authority_weight,
        }
    }
}

#[derive(Clone, Debug, Default)]
pub struct FactStore {
    facts: BTreeMap<FactKey, Observation>,
}

impl FactStore {
    pub fn insert(&mut self, key: impl Into<FactKey>, observation: Observation) {
        self.facts.insert(key.into(), observation);
    }

    pub fn get(&self, key: &FactKey) -> Option<&Observation> {
        self.facts.get(key)
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ConstraintState {
    Confirmed,
    Bounded,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Repairability {
    None,
    RelationOnly,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ConstraintSpec {
    pub id: String,
    pub authority_ref: String,
    pub state: ConstraintState,
    pub scope: String,
    pub keys: Vec<FactKey>,
    pub repairability: Repairability,
}

impl ConstraintSpec {
    pub fn all_equal(
        id: impl Into<String>,
        authority_ref: impl Into<String>,
        state: ConstraintState,
        scope: impl Into<String>,
        keys: impl IntoIterator<Item = impl Into<FactKey>>,
        repairability: Repairability,
    ) -> Self {
        Self {
            id: id.into(),
            authority_ref: authority_ref.into(),
            state,
            scope: scope.into(),
            keys: keys.into_iter().map(Into::into).collect(),
            repairability,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WitnessFact {
    pub key: FactKey,
    pub observation: Observation,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ConstraintResult {
    Satisfied,
    NotEvaluable { missing: Vec<FactKey> },
    Violated { witness: Vec<WitnessFact> },
}

pub fn evaluate_all_equal(store: &FactStore, constraint: &ConstraintSpec) -> ConstraintResult {
    let mut missing = Vec::new();
    let mut witness = Vec::new();

    for key in &constraint.keys {
        match store.get(key) {
            Some(observation) => witness.push(WitnessFact {
                key: key.clone(),
                observation: observation.clone(),
            }),
            None => missing.push(key.clone()),
        }
    }

    if !missing.is_empty() {
        return ConstraintResult::NotEvaluable { missing };
    }

    let distinct_values = witness
        .iter()
        .map(|fact| fact.observation.value.as_str())
        .collect::<BTreeSet<_>>();

    if distinct_values.len() <= 1 {
        ConstraintResult::Satisfied
    } else {
        ConstraintResult::Violated { witness }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RepairEdit {
    pub key: FactKey,
    pub from: String,
    pub to: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RepairCandidate {
    pub value: String,
    pub support_weight: u32,
    pub supporting_sources: Vec<String>,
    pub edits: Vec<RepairEdit>,
    pub auto_applicable: bool,
}

pub fn rank_relation_repairs(
    store: &FactStore,
    constraint: &ConstraintSpec,
) -> Vec<RepairCandidate> {
    if constraint.repairability != Repairability::RelationOnly {
        return Vec::new();
    }

    let ConstraintResult::Violated { witness } = evaluate_all_equal(store, constraint) else {
        return Vec::new();
    };

    // Do not count the same projection/source multiple times for one candidate value.
    let mut support_by_value: BTreeMap<String, BTreeMap<String, u32>> = BTreeMap::new();
    for fact in &witness {
        support_by_value
            .entry(fact.observation.value.clone())
            .or_default()
            .entry(fact.observation.source.clone())
            .and_modify(|weight| {
                *weight = (*weight).max(fact.observation.authority_weight);
            })
            .or_insert(fact.observation.authority_weight);
    }

    let mut candidates = Vec::new();
    for (value, sources) in support_by_value {
        let support_weight = sources.values().copied().sum();
        let supporting_sources = sources.keys().cloned().collect::<Vec<_>>();
        let edits = witness
            .iter()
            .filter(|fact| fact.observation.value != value)
            .map(|fact| RepairEdit {
                key: fact.key.clone(),
                from: fact.observation.value.clone(),
                to: value.clone(),
            })
            .collect::<Vec<_>>();

        candidates.push(RepairCandidate {
            value,
            support_weight,
            supporting_sources,
            edits,
            auto_applicable: false,
        });
    }

    candidates.sort_by(|a, b| {
        b.support_weight
            .cmp(&a.support_weight)
            .then_with(|| a.edits.len().cmp(&b.edits.len()))
            .then_with(|| a.value.cmp(&b.value))
    });

    if let Some((first, rest)) = candidates.split_first_mut() {
        let second_weight = rest.first().map(|candidate| candidate.support_weight).unwrap_or(0);
        if first.support_weight > second_weight {
            first.auto_applicable = true;
        }
    }

    candidates
}

pub fn pub_seed_constraints() -> Vec<ConstraintSpec> {
    vec![
        ConstraintSpec::all_equal(
            "PUB-CSTR-001",
            "WFS mature join: TABLE textId -> Story/SYID -> TCD",
            ConstraintState::Confirmed,
            "mature TABLE only",
            [
                "table/contents/text_id",
                "story/quill/syid",
                "tcd/quill/story_id",
            ],
            Repairability::RelationOnly,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-002",
            "WFS mature join: TABLE cellsSeqNum -> CELLS",
            ConstraintState::Confirmed,
            "mature TABLE only",
            ["table/contents/cells_seq", "cells/contents/seq"],
            Repairability::RelationOnly,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-003",
            "WFS mature join: 0x65.field07 -> MCLD.recordId",
            ConstraintState::Confirmed,
            "Story/TextFrame with stored MCLD",
            ["story/contents/mcld_ref", "mcld/contents/record_id"],
            Repairability::RelationOnly,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-004",
            "bounded geometry join: shape width -> Escher ClientAnchor width",
            ConstraintState::Bounded,
            "applicability-proven shape class only",
            ["shape/semantic/width_emu", "escher/client_anchor/width_emu"],
            Repairability::None,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-005",
            "bounded geometry join: shape height -> Escher ClientAnchor height",
            ConstraintState::Bounded,
            "applicability-proven shape class only",
            ["shape/semantic/height_emu", "escher/client_anchor/height_emu"],
            Repairability::None,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-006",
            "resource join: picture reference -> BStore slot",
            ConstraintState::Bounded,
            "picture classes with proven BStore binding",
            ["picture/semantic/resource_slot", "bstore/entry/slot"],
            Repairability::RelationOnly,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-007",
            "TABLE border owner join: carrier 0x6802 -> TABLE owner",
            ConstraintState::Bounded,
            "TABLE border carrier topology",
            ["border/escher/owner_table", "table/semantic/owner_id"],
            Repairability::RelationOnly,
        ),
        ConstraintSpec::all_equal(
            "PUB-CSTR-008",
            "page identity join: hyperlink target PageID -> Page identity",
            ConstraintState::Bounded,
            "internal page hyperlink identity scope",
            ["hyperlink/semantic/target_page_id", "page/contents/page_id"],
            Repairability::RelationOnly,
        ),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn obs(value: &str, source: &str, weight: u32) -> Observation {
        Observation::new(value, source, weight)
    }

    #[test]
    fn healthy_table_identity_is_satisfied() {
        let constraint = &pub_seed_constraints()[0];
        let mut store = FactStore::default();
        store.insert("table/contents/text_id", obs("1001", "Contents", 100));
        store.insert("story/quill/syid", obs("1001", "Quill", 100));
        store.insert("tcd/quill/story_id", obs("1001", "Quill/TCD", 100));

        assert_eq!(
            evaluate_all_equal(&store, constraint),
            ConstraintResult::Satisfied
        );
        assert!(rank_relation_repairs(&store, constraint).is_empty());
    }

    #[test]
    fn missing_projection_is_not_called_corruption() {
        let constraint = &pub_seed_constraints()[0];
        let mut store = FactStore::default();
        store.insert("table/contents/text_id", obs("1001", "Contents", 100));
        store.insert("story/quill/syid", obs("1001", "Quill", 100));

        let ConstraintResult::NotEvaluable { missing } =
            evaluate_all_equal(&store, constraint)
        else {
            panic!("expected NotEvaluable");
        };

        assert_eq!(missing, vec![FactKey::from("tcd/quill/story_id")]);
    }

    #[test]
    fn single_corrupt_relation_is_localized_and_ranked() {
        let constraint = &pub_seed_constraints()[0];
        let mut store = FactStore::default();
        store.insert("table/contents/text_id", obs("1001", "Contents", 100));
        store.insert("story/quill/syid", obs("1001", "Quill", 100));
        store.insert("tcd/quill/story_id", obs("9009", "Quill/TCD", 100));

        let ConstraintResult::Violated { witness } =
            evaluate_all_equal(&store, constraint)
        else {
            panic!("expected violation");
        };
        assert_eq!(witness.len(), 3);

        let candidates = rank_relation_repairs(&store, constraint);
        assert_eq!(candidates[0].value, "1001");
        assert_eq!(candidates[0].support_weight, 200);
        assert!(candidates[0].auto_applicable);
        assert_eq!(candidates[0].edits.len(), 1);
        assert_eq!(
            candidates[0].edits[0].key,
            FactKey::from("tcd/quill/story_id")
        );
    }

    #[test]
    fn ambiguous_relation_never_auto_repairs() {
        let constraint = ConstraintSpec::all_equal(
            "AMBIG",
            "test",
            ConstraintState::Confirmed,
            "test",
            ["left", "right"],
            Repairability::RelationOnly,
        );
        let mut store = FactStore::default();
        store.insert("left", obs("A", "Contents", 100));
        store.insert("right", obs("B", "Quill", 100));

        let candidates = rank_relation_repairs(&store, &constraint);
        assert_eq!(candidates.len(), 2);
        assert!(candidates.iter().all(|candidate| !candidate.auto_applicable));
    }

    #[test]
    fn duplicated_same_source_does_not_fake_independent_support() {
        let constraint = ConstraintSpec::all_equal(
            "SOURCE-DEDUPE",
            "test",
            ConstraintState::Confirmed,
            "test",
            ["a", "b", "c"],
            Repairability::RelationOnly,
        );
        let mut store = FactStore::default();
        store.insert("a", obs("A", "Quill", 100));
        store.insert("b", obs("A", "Quill", 100));
        store.insert("c", obs("B", "Contents", 100));

        let candidates = rank_relation_repairs(&store, &constraint);
        assert_eq!(candidates[0].support_weight, 100);
        assert_eq!(candidates[1].support_weight, 100);
        assert!(candidates.iter().all(|candidate| !candidate.auto_applicable));
    }

    #[test]
    fn authority_weight_can_break_a_tie_without_raw_majority_vote() {
        let constraint = ConstraintSpec::all_equal(
            "AUTHORITY",
            "test",
            ConstraintState::Confirmed,
            "test",
            ["a", "b", "c"],
            Repairability::RelationOnly,
        );
        let mut store = FactStore::default();
        store.insert("a", obs("A", "Contents", 200));
        store.insert("b", obs("B", "Quill", 50));
        store.insert("c", obs("B", "Escher", 50));

        let candidates = rank_relation_repairs(&store, &constraint);
        assert_eq!(candidates[0].value, "A");
        assert_eq!(candidates[0].support_weight, 200);
        assert!(candidates[0].auto_applicable);
    }

    #[test]
    fn non_repairable_constraint_only_reports_violation() {
        let constraint = &pub_seed_constraints()[3];
        let mut store = FactStore::default();
        store.insert("shape/semantic/width_emu", obs("100", "Contents", 100));
        store.insert(
            "escher/client_anchor/width_emu",
            obs("101", "Escher", 100),
        );

        assert!(matches!(
            evaluate_all_equal(&store, constraint),
            ConstraintResult::Violated { .. }
        ));
        assert!(rank_relation_repairs(&store, constraint).is_empty());
    }

    #[test]
    fn seed_contains_eight_bounded_or_confirmed_constraints() {
        let constraints = pub_seed_constraints();
        assert_eq!(constraints.len(), 8);
        assert!(constraints.iter().all(|constraint| matches!(
            constraint.state,
            ConstraintState::Confirmed | ConstraintState::Bounded
        )));
    }
}
