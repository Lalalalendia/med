use pub_constraint_lab::{
    evaluate_all_equal, pub_seed_constraints, rank_relation_repairs, ConstraintResult,
    ConstraintSpec, FactKey, FactStore, Observation, RepairCandidate,
};
use sha2::{Digest, Sha256};
use std::fmt::Write;

#[derive(Clone, Copy)]
struct FactRow {
    key: &'static str,
    value: &'static str,
    source: &'static str,
    authority_weight: u32,
}

const FIXTURE_REPOSITORY: &str = "apache/poi";
const FIXTURE_COMMIT: &str = "732120980140d5ed64b482c470e0b625cdb1ab15";
const FIXTURE_PATH: &str = "test-data/publisher/Sample.pub";
const FIXTURE_GIT_BLOB_SHA: &str = "b870168319048c9e8631c2338eb937e6f8f62b5b";
const FIXTURE_SHA256: &str =
    "6fefdef46b87c767150878dc384549cb2d2ec2ac54de25f8ddb3a5628301107e";
const FIXTURE_SIZE: u64 = 72_192;
const TABLE_SEQ: u32 = 299;
const CELLS_SEQ: u32 = 301;
const RAW_TCD_DESCRIPTOR_ORDINAL: u32 = 3;
const RESOLVED_STORY_SYID: &str = "6";
const TCD_BOUNDARIES_UTF16: [u32; 6] = [15, 25, 39, 54, 66, 80];

const HEALTHY_ROWS: [FactRow; 3] = [
    FactRow {
        key: "table/contents/text_id",
        value: RESOLVED_STORY_SYID,
        source: "Contents",
        authority_weight: 100,
    },
    FactRow {
        key: "story/quill/syid",
        value: RESOLVED_STORY_SYID,
        source: "Quill",
        authority_weight: 100,
    },
    FactRow {
        key: "tcd/quill/story_id",
        value: RESOLVED_STORY_SYID,
        source: "Quill/TCD-resolved",
        authority_weight: 100,
    },
];

fn json_string(value: &str) -> String {
    let mut out = String::with_capacity(value.len() + 2);
    out.push('"');
    for ch in value.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c.is_control() => {
                write!(&mut out, "\\u{:04x}", c as u32).expect("write to String");
            }
            c => out.push(c),
        }
    }
    out.push('"');
    out
}

fn store_from(rows: &[FactRow]) -> FactStore {
    let mut store = FactStore::default();
    for row in rows {
        store.insert(
            row.key,
            Observation::new(row.value, row.source, row.authority_weight),
        );
    }
    store
}

fn fact_graph_sha256(rows: &[FactRow]) -> String {
    let mut canonical = rows
        .iter()
        .map(|row| {
            format!(
                "{}={}\\t{}\\t{}",
                row.key, row.value, row.source, row.authority_weight
            )
        })
        .collect::<Vec<_>>();
    canonical.sort();

    let mut hasher = Sha256::new();
    for line in canonical {
        hasher.update(line.as_bytes());
        hasher.update(b"\n");
    }
    format!("{:x}", hasher.finalize())
}

fn state_name(result: &ConstraintResult) -> &'static str {
    match result {
        ConstraintResult::Satisfied => "Satisfied",
        ConstraintResult::NotEvaluable { .. } => "NotEvaluable",
        ConstraintResult::Violated { .. } => "Violated",
    }
}

fn facts_json(rows: &[FactRow]) -> String {
    let mut items = rows
        .iter()
        .map(|row| {
            format!(
                "{{\"key\":{},\"value\":{},\"source\":{},\"authority_weight\":{}}}",
                json_string(row.key),
                json_string(row.value),
                json_string(row.source),
                row.authority_weight
            )
        })
        .collect::<Vec<_>>();
    items.sort();
    format!("[{}]", items.join(","))
}

fn candidates_json(candidates: &[RepairCandidate]) -> String {
    let mut out = Vec::new();
    for candidate in candidates {
        let sources = candidate
            .supporting_sources
            .iter()
            .map(|source| json_string(source))
            .collect::<Vec<_>>()
            .join(",");
        let edits = candidate
            .edits
            .iter()
            .map(|edit| {
                format!(
                    "{{\"key\":{},\"from\":{},\"to\":{}}}",
                    json_string(&edit.key.0),
                    json_string(&edit.from),
                    json_string(&edit.to)
                )
            })
            .collect::<Vec<_>>()
            .join(",");
        out.push(format!(
            "{{\"value\":{},\"support_weight\":{},\"supporting_sources\":[{}],\"edits\":[{}],\"auto_applicable\":{}}}",
            json_string(&candidate.value),
            candidate.support_weight,
            sources,
            edits,
            if candidate.auto_applicable {
                "true"
            } else {
                "false"
            }
        ));
    }
    format!("[{}]", out.join(","))
}

fn apply_candidate(store: &mut FactStore, candidate: &RepairCandidate) {
    for edit in &candidate.edits {
        let before = store
            .get(&edit.key)
            .unwrap_or_else(|| panic!("missing repair fact {}", edit.key.0))
            .clone();
        assert_eq!(before.value, edit.from);
        store.insert(
            edit.key.clone(),
            Observation::new(
                edit.to.clone(),
                format!("repair:{}", before.source),
                before.authority_weight,
            ),
        );
    }
}

fn constraint() -> ConstraintSpec {
    pub_seed_constraints()
        .into_iter()
        .next()
        .expect("PUB-CSTR-001 seed")
}

fn healthy_case(spec: &ConstraintSpec) -> String {
    let store = store_from(&HEALTHY_ROWS);
    let result = evaluate_all_equal(&store, spec);
    assert!(matches!(result, ConstraintResult::Satisfied));
    assert!(rank_relation_repairs(&store, spec).is_empty());

    format!(
        "{{\"name\":\"healthy-control\",\"corruption_delta\":[],\"surviving_facts\":{},\"constraint_id\":{},\"evaluation\":{},\"ranked_candidates\":[],\"post_repair_validation\":\"Satisfied\"}}",
        facts_json(&HEALTHY_ROWS),
        json_string(&spec.id),
        json_string(state_name(&result))
    )
}

fn single_corruption_case(spec: &ConstraintSpec) -> String {
    let rows = [
        HEALTHY_ROWS[0],
        HEALTHY_ROWS[1],
        FactRow {
            value: "9009",
            ..HEALTHY_ROWS[2]
        },
    ];
    let surviving = [HEALTHY_ROWS[0], HEALTHY_ROWS[1]];
    let mut store = store_from(&rows);
    let result = evaluate_all_equal(&store, spec);
    assert!(matches!(result, ConstraintResult::Violated { .. }));

    let candidates = rank_relation_repairs(&store, spec);
    let top = candidates.first().expect("repair candidate");
    assert_eq!(top.value, RESOLVED_STORY_SYID);
    assert_eq!(top.support_weight, 200);
    assert!(top.auto_applicable);
    assert_eq!(top.edits.len(), 1);
    assert_eq!(top.edits[0].key, FactKey::from("tcd/quill/story_id"));

    apply_candidate(&mut store, top);
    let repaired = evaluate_all_equal(&store, spec);
    assert!(matches!(repaired, ConstraintResult::Satisfied));

    format!(
        "{{\"name\":\"single-corrupt-tcd-relation\",\"corruption_delta\":[{{\"key\":\"tcd/quill/story_id\",\"from\":\"6\",\"to\":\"9009\"}}],\"surviving_facts\":{},\"constraint_id\":{},\"evaluation\":{},\"ranked_candidates\":{},\"post_repair_validation\":{}}}",
        facts_json(&surviving),
        json_string(&spec.id),
        json_string(state_name(&result)),
        candidates_json(&candidates),
        json_string(state_name(&repaired))
    )
}

fn ambiguous_case(spec: &ConstraintSpec) -> String {
    let rows = [
        HEALTHY_ROWS[0],
        FactRow {
            value: "2002",
            ..HEALTHY_ROWS[1]
        },
        FactRow {
            value: "3003",
            ..HEALTHY_ROWS[2]
        },
    ];
    let surviving = [HEALTHY_ROWS[0]];
    let store = store_from(&rows);
    let result = evaluate_all_equal(&store, spec);
    assert!(matches!(result, ConstraintResult::Violated { .. }));

    let candidates = rank_relation_repairs(&store, spec);
    assert_eq!(candidates.len(), 3);
    assert!(candidates
        .iter()
        .all(|candidate| !candidate.auto_applicable));

    format!(
        "{{\"name\":\"ambiguous-three-way-conflict\",\"corruption_delta\":[{{\"key\":\"story/quill/syid\",\"from\":\"6\",\"to\":\"2002\"}},{{\"key\":\"tcd/quill/story_id\",\"from\":\"6\",\"to\":\"3003\"}}],\"surviving_facts\":{},\"constraint_id\":{},\"evaluation\":{},\"ranked_candidates\":{},\"post_repair_validation\":null}}",
        facts_json(&surviving),
        json_string(&spec.id),
        json_string(state_name(&result)),
        candidates_json(&candidates)
    )
}

fn build_receipt() -> String {
    let spec = constraint();
    let cases = [
        healthy_case(&spec),
        single_corruption_case(&spec),
        ambiguous_case(&spec),
    ];
    let boundaries = TCD_BOUNDARIES_UTF16
        .iter()
        .map(u32::to_string)
        .collect::<Vec<_>>()
        .join(",");

    format!(
        "{{\"schema\":\"chaptera.pub.cr06-constraint-repair.v1\",\"experiment_id\":\"CR06-CONSTRAINT-REPAIR-01\",\"source\":{{\"kind\":\"captured-public-fixture-metadata\",\"repository\":{},\"commit\":{},\"path\":{},\"git_blob_sha\":{},\"sha256\":{},\"size\":{},\"table_seq\":{},\"cells_seq\":{},\"table_text_id\":6,\"raw_tcd_descriptor_ordinal\":{},\"resolved_tcd_story_syid\":6,\"tcd_boundaries_utf16\":[{}]}},\"healthy_fact_graph_sha256\":{},\"resolution_note\":\"tcd/quill/story_id is the resolved Story SYID obtained as SYID[raw TCD descriptor ordinal]; the raw ordinal 3 is not compared directly with TABLE textId 6.\",\"authority_boundary\":\"Relation-only graph repair over captured mature TABLE metadata. No PUB bytes are synthesized or written; recovery of original source bytes and native Publisher materialization are separate later gates.\",\"constraint_id\":{},\"cases\":[{}]}}",
        json_string(FIXTURE_REPOSITORY),
        json_string(FIXTURE_COMMIT),
        json_string(FIXTURE_PATH),
        json_string(FIXTURE_GIT_BLOB_SHA),
        json_string(FIXTURE_SHA256),
        FIXTURE_SIZE,
        TABLE_SEQ,
        CELLS_SEQ,
        RAW_TCD_DESCRIPTOR_ORDINAL,
        boundaries,
        json_string(&fact_graph_sha256(&HEALTHY_ROWS)),
        json_string(&spec.id),
        cases.join(",")
    )
}

fn main() {
    println!("{}", build_receipt());
}

#[cfg(test)]
mod tests {
    use super::{build_receipt, FIXTURE_SHA256};

    #[test]
    fn cr06_receipt_contains_unique_repair_and_ambiguity_guard() {
        let receipt = build_receipt();
        assert!(receipt.contains("\"name\":\"healthy-control\""));
        assert!(receipt.contains("\"name\":\"single-corrupt-tcd-relation\""));
        assert!(receipt.contains(FIXTURE_SHA256));
        assert!(receipt.contains("\"raw_tcd_descriptor_ordinal\":3"));
        assert!(receipt.contains("\"resolved_tcd_story_syid\":6"));
        assert!(receipt.contains("\"support_weight\":200"));
        assert!(receipt.contains("\"auto_applicable\":true"));
        assert!(receipt.contains("\"post_repair_validation\":\"Satisfied\""));
        assert!(receipt.contains("\"name\":\"ambiguous-three-way-conflict\""));
        assert!(receipt.contains("\"post_repair_validation\":null"));
    }
}
