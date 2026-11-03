//! The conformance runner: every case under `conformance/cases/`, run through the crate's
//! public API exactly as `conformance/README.md` states the runner contract, plus the
//! citation reconciliation between the cases and `spec/private-terms.md`, and the
//! round trip of every valid declaration the suite holds through both encodings.

use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

use privateterms::{
    parse, redact_all, resolve, to_toml, to_yaml, Action, Declaration, Format, Level, LevelKind,
    Locator, LocatorKind, Matcher, Replacement, TermMode, TermRule, LOCATOR_UNFIXABLE_REASON,
};
use serde_json::{json, Value};

fn repository() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

struct Case {
    file: String,
    id: String,
    body: Value,
}

fn cases() -> Vec<Case> {
    let dir = repository().join("conformance/cases");
    let mut files: Vec<PathBuf> = std::fs::read_dir(&dir)
        .expect("conformance/cases is readable")
        .map(|entry| entry.expect("an entry").path())
        .filter(|path| path.extension().is_some_and(|ext| ext == "json"))
        .collect();
    files.sort();
    assert!(!files.is_empty(), "the suite holds case files");
    let mut all = Vec::new();
    let mut ids = BTreeSet::new();
    for path in files {
        let file = path.file_name().unwrap().to_string_lossy().into_owned();
        let text = std::fs::read_to_string(&path).expect("a case file");
        let document: Value = serde_json::from_str(&text)
            .unwrap_or_else(|error| panic!("{file} is not JSON: {error}"));
        let listed = document["cases"]
            .as_array()
            .unwrap_or_else(|| panic!("{file} has no `cases` list"));
        for body in listed {
            let id = body["id"]
                .as_str()
                .unwrap_or_else(|| panic!("a case in {file} has no id"))
                .to_owned();
            assert!(ids.insert(id.clone()), "case id {id} appears twice");
            all.push(Case {
                file: file.clone(),
                id,
                body: body.clone(),
            });
        }
    }
    all
}

fn level_kind(value: &Value) -> LevelKind {
    serde_json::from_value(value.clone()).expect("a level kind")
}

/// A model value, encoded the two ways this crate binds a declaration and read back
/// through the public `parse`: both must give the same answer.
fn read_declaration(value: &Value, kind: LevelKind) -> Result<Declaration, String> {
    if !value.is_object() {
        // A value that is not a mapping has no TOML document; YAML alone says it.
        let yaml_text = serde_saphyr::to_string(value).expect("a value encodes as YAML");
        return parse(yaml_text.as_bytes(), Format::Yaml, kind)
            .map_err(|e| e.kind.name().to_owned());
    }
    let toml_text = toml::to_string(value).expect("a case's declaration encodes as TOML");
    let yaml_text = serde_saphyr::to_string(value).expect("a case's declaration encodes as YAML");
    let from_toml = parse(toml_text.as_bytes(), Format::Toml, kind);
    let from_yaml = parse(yaml_text.as_bytes(), Format::Yaml, kind);
    match (from_toml, from_yaml) {
        (Ok(a), Ok(b)) => {
            assert_eq!(a, b, "TOML and YAML read one model value differently");
            Ok(a)
        }
        (Err(a), Err(b)) => {
            assert_eq!(
                a.kind, b.kind,
                "TOML and YAML refuse one model value differently"
            );
            Err(a.kind.name().to_owned())
        }
        (a, b) => panic!("TOML and YAML disagree on one model value: {a:?} / {b:?}"),
    }
}

/// The levels of a case, or the kind of the error that makes its check unavailable.
fn levels(case: &Value) -> Result<Vec<Level>, String> {
    let mut levels = Vec::new();
    for (index, level) in case["levels"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .iter()
        .enumerate()
    {
        let kind = level_kind(&level["kind"]);
        if level["unreadable"].as_bool() == Some(true) {
            return Err("unreadable".to_owned());
        }
        let declaration = read_declaration(&level["declaration"], kind)?;
        let location = level["location"]
            .as_str()
            .map(str::to_owned)
            .unwrap_or_else(|| format!("level-{index}"));
        levels.push(Level {
            kind,
            dir: PathBuf::from(location),
            declaration,
        });
    }
    Ok(levels)
}

fn rules(case: &Value) -> Vec<(TermRule, String)> {
    case["rules"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|rule| {
            (
                TermRule {
                    term: rule["term"].as_str().expect("a rule term").to_owned(),
                    mode: serde_json::from_value(rule["mode"].clone()).expect("a rule mode"),
                    case_sensitive: rule["case_sensitive"].as_bool().unwrap_or(false),
                },
                "derived".to_owned(),
            )
        })
        .collect()
}

fn caller(case: &Value) -> Vec<Replacement> {
    serde_json::from_value(case["caller"].clone()).unwrap_or_default()
}

fn action_json(action: &Action) -> Value {
    match action {
        Action::Reject => json!("reject"),
        Action::Replace(with) => json!({ "replace": with }),
    }
}

fn mode_json(mode: TermMode) -> Value {
    serde_json::to_value(mode).expect("a mode")
}

fn locators(case: &Value) -> Vec<(LocatorKind, String)> {
    case["locators"]
        .as_array()
        .cloned()
        .unwrap_or_default()
        .into_iter()
        .map(|locator| {
            (
                serde_json::from_value(locator["kind"].clone()).expect("a locator kind"),
                locator["value"]
                    .as_str()
                    .expect("a locator value")
                    .to_owned(),
            )
        })
        .collect()
}

/// What a case's operation gives, in the expected-outcome vocabulary of the README.
fn run(case: &Value) -> Value {
    let operation = case["operation"].as_str().expect("an operation");
    let first_ordinal = case["first_ordinal"].as_u64().unwrap_or(1) as u32;
    let unavailable = |error: String| {
        if operation == "screen-locators" {
            let owned = locators(case);
            let borrowed: Vec<(LocatorKind, &str)> =
                owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
            screened(&redact_all(&borrowed, first_ordinal))
        } else if operation == "validate" {
            json!({ "outcome": "declaration-error", "error": error })
        } else {
            json!({ "outcome": "unavailable", "error": error })
        }
    };
    let levels = match levels(case) {
        Ok(levels) => levels,
        Err(error) => return unavailable(error),
    };
    if operation == "validate" {
        return json!({ "outcome": "valid" });
    }
    let resolved = match resolve(rules(case), &levels, &caller(case)) {
        Ok(resolved) => resolved,
        Err(error) => return unavailable(error.kind.name().to_owned()),
    };
    if operation == "resolve" {
        let listed: Vec<Value> = resolved
            .iter()
            .map(|r| {
                json!({
                    "term": r.rule.term,
                    "mode": mode_json(r.rule.mode),
                    "case_sensitive": r.rule.case_sensitive,
                    "action": action_json(&r.action),
                })
            })
            .collect();
        return json!({ "outcome": "resolved", "rules": listed });
    }
    let phrases: Vec<String> = levels
        .iter()
        .flat_map(|level| level.declaration.phrases.iter().cloned())
        .collect();
    let matcher = Matcher::new(resolved, &phrases).expect("a case's matcher builds");
    let term = |index: usize| matcher.rules()[index].rule.term.clone();
    match operation {
        "detect" => {
            let text = case["text"].as_str().expect("a text");
            let hits = matcher.hits(text);
            let found: BTreeSet<String> = matcher.find(text).into_iter().map(term).collect();
            let hit_terms: BTreeSet<String> = hits.iter().map(|hit| term(hit.rule)).collect();
            assert_eq!(
                found, hit_terms,
                "find and hits agree on which rules a text carries"
            );
            let listed: Vec<Value> = hits
                .iter()
                .map(|hit| {
                    json!({
                        "term": term(hit.rule),
                        "span": [hit.span.start, hit.span.end],
                        "text": &text[hit.span.clone()],
                    })
                })
                .collect();
            json!({
                "outcome": if found.is_empty() { "clean" } else { "detected" },
                "found": found,
                "hits": listed,
                "exempted": matcher.exempted(text),
            })
        }
        "replace" => {
            let text = case["text"].as_str().expect("a text");
            if matcher.check_replacements().is_err() {
                let replaced = matcher.replace(text);
                assert_eq!(
                    replaced.text, text,
                    "nothing is replaced when a replacement carries a term"
                );
                assert!(
                    !replaced.remaining.is_empty(),
                    "and the outcome is still a refusal"
                );
                return json!({ "outcome": "error", "error": "replacement-carries-term" });
            }
            let replaced = matcher.replace(text);
            if replaced.remaining.is_empty() {
                json!({ "outcome": "replaced", "text": replaced.text, "replaced": replaced.replaced })
            } else {
                let remaining: BTreeSet<String> =
                    replaced.remaining.iter().map(|i| term(*i)).collect();
                json!({ "outcome": "refused", "refusal": "term-remains", "remaining": remaining, "text": replaced.text })
            }
        }
        "screen-locators" => {
            let owned = locators(case);
            let borrowed: Vec<(LocatorKind, &str)> =
                owned.iter().map(|(k, v)| (*k, v.as_str())).collect();
            screened(&matcher.screen_locators(&borrowed, first_ordinal))
        }
        other => panic!("unknown operation {other}"),
    }
}

fn screened(locators: &[Locator]) -> Value {
    let unfixable = locators
        .iter()
        .any(|l| matches!(l, Locator::Redacted { .. }));
    json!({
        "outcome": "screened",
        "locators": serde_json::to_value(locators).expect("locators serialize"),
        "unfixable": unfixable,
        "reason": if unfixable { Value::from(LOCATOR_UNFIXABLE_REASON) } else { Value::Null },
    })
}

/// Whether `actual` carries every member `expected` states, equal; members the case does
/// not state are not compared.
fn matches_expectation(expected: &Value, actual: &Value) -> Result<(), String> {
    let Value::Object(expected) = expected else {
        return Err("`expect` is not an object".to_owned());
    };
    for (key, want) in expected {
        let got = actual.get(key).unwrap_or(&Value::Null);
        let equal = match key.as_str() {
            // Sets: compared without order.
            "found" | "remaining" => {
                let as_set = |v: &Value| -> BTreeSet<String> {
                    v.as_array()
                        .map(|a| {
                            a.iter()
                                .filter_map(|x| x.as_str().map(str::to_owned))
                                .collect()
                        })
                        .unwrap_or_default()
                };
                as_set(want) == as_set(got)
            }
            _ => want == got,
        };
        if !equal {
            return Err(format!("`{key}`: expected {want}, got {got}"));
        }
    }
    Ok(())
}

#[test]
fn every_conformance_case_passes() {
    let mut failures = Vec::new();
    let all = cases();
    for case in &all {
        let actual = run(&case.body);
        if let Err(problem) = matches_expectation(&case.body["expect"], &actual) {
            failures.push(format!(
                "{}#{}: {problem}\n  actual: {actual}",
                case.file, case.id
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} of {} cases failed:\n{}",
        failures.len(),
        all.len(),
        failures.join("\n")
    );
}

/// The rule ids `spec/private-terms.md` defines, each with the case files it cites.
fn spec_rules() -> BTreeMap<String, BTreeSet<String>> {
    let spec =
        std::fs::read_to_string(repository().join("spec/private-terms.md")).expect("the spec");
    let mut rules: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut current: Option<String> = None;
    for line in spec.lines() {
        // A rule is introduced as `**[RULE-ID]**` and its citations follow on a line
        // starting `Cases:` naming case files in backticks.
        if let Some(start) = line.find("**[") {
            if let Some(end) = line[start + 3..].find("]**") {
                let id = line[start + 3..start + 3 + end].to_owned();
                assert!(
                    rules.insert(id.clone(), BTreeSet::new()).is_none(),
                    "rule {id} is defined twice"
                );
                current = Some(id);
                continue;
            }
        }
        let trimmed = line.trim_start();
        if let (Some(id), Some(list)) = (&current, trimmed.strip_prefix("Cases:")) {
            for cited in list.split('`').skip(1).step_by(2) {
                rules
                    .get_mut(id)
                    .unwrap()
                    .insert(cited.trim_start_matches("conformance/cases/").to_owned());
            }
        }
    }
    rules
}

#[test]
fn every_rule_cites_its_cases_and_every_case_cites_a_rule() {
    let rules = spec_rules();
    assert!(!rules.is_empty(), "the spec defines rules");
    let mut by_rule: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    let mut problems = Vec::new();
    for case in cases() {
        let exercised = case.body["exercises"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        if exercised.is_empty() {
            problems.push(format!("{}#{} cites no rule", case.file, case.id));
        }
        for rule in exercised {
            let rule = rule.as_str().unwrap_or_default().to_owned();
            if !rules.contains_key(&rule) {
                problems.push(format!(
                    "{}#{} cites {rule}, which the spec does not define",
                    case.file, case.id
                ));
            }
            by_rule.entry(rule).or_default().insert(case.file.clone());
        }
    }
    for (rule, cited) in &rules {
        let exercised = by_rule.get(rule).cloned().unwrap_or_default();
        if exercised.is_empty() {
            problems.push(format!("{rule} is exercised by no case"));
        }
        if *cited != exercised {
            problems.push(format!(
                "{rule} cites {cited:?} but the cases exercising it are in {exercised:?}"
            ));
        }
    }
    assert!(problems.is_empty(), "{}", problems.join("\n"));
}

#[test]
fn every_valid_declaration_round_trips_through_both_encodings_and_every_invalid_one_is_refused() {
    let mut valid = 0;
    for case in cases() {
        for level in case.body["levels"].as_array().cloned().unwrap_or_default() {
            if level["unreadable"].as_bool() == Some(true) {
                continue;
            }
            let kind = level_kind(&level["kind"]);
            match read_declaration(&level["declaration"], kind) {
                Ok(declaration) => {
                    valid += 1;
                    for (written, format) in [
                        (to_toml(&declaration), Format::Toml),
                        (to_yaml(&declaration), Format::Yaml),
                    ] {
                        let back = parse(written.as_bytes(), format, kind).unwrap_or_else(|e| {
                            panic!(
                                "{}#{}: {format:?} written form refused: {e}",
                                case.file, case.id
                            )
                        });
                        assert_eq!(
                            back, declaration,
                            "{}#{}: {format:?} round trip",
                            case.file, case.id
                        );
                    }
                }
                Err(_) => {
                    // Refused by parse in both encodings already (read_declaration asserts
                    // they agree), and never read as a declaration.
                }
            }
        }
    }
    assert!(valid > 0, "the suite holds valid declarations");
}
