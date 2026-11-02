//! Contract 0's public API, named item by item with its stated signature and fields, so a
//! renamed, reshaped or missing item fails to compile; and its serialization contract.

use std::ops::Range;
use std::path::{Path, PathBuf};

use privateterms::{
    discover_levels, parse, read_dir_level, redact_all, resolve, to_toml, to_yaml, Action,
    Declaration, DeclarationError, DeclarationErrorKind, Exception, ExceptionAction, Format, Hit,
    Level, LevelKind, Locator, LocatorKind, Matcher, Member, Replaced, Replacement,
    ReplacementCarriesTerm, ResolvedRule, TermMode, TermRule, Unbuildable, FILE_NAMES,
    LOCATOR_UNFIXABLE_REASON, SPEC_VERSION,
};
use schemars::JsonSchema;
use serde::de::DeserializeOwned;
use serde::Serialize;
use serde_json::json;

#[test]
fn the_constants_are_as_stated() {
    let version: u32 = SPEC_VERSION;
    assert_eq!(version, 1);
    let names: [&str; 3] = FILE_NAMES;
    assert_eq!(
        names,
        [
            "private-terms.toml",
            "private-terms.yaml",
            "private-terms.yml"
        ]
    );
    assert_eq!(
        LOCATOR_UNFIXABLE_REASON,
        "identifier carries a private term"
    );
}

#[test]
#[allow(
    clippy::type_complexity,
    reason = "each signature is spelled out literally on purpose: a type alias would let a reshaped signature compile"
)]
fn every_function_has_its_stated_signature() {
    let _: fn(&[u8], Format, LevelKind) -> Result<Declaration, DeclarationError> = parse;
    let _: fn(&Declaration) -> String = to_toml;
    let _: fn(&Declaration) -> String = to_yaml;
    let _: fn(&Path, LevelKind) -> Result<Option<Level>, DeclarationError> = read_dir_level;
    let _: fn(&Path, &Path, Option<&Path>) -> Result<Vec<Level>, DeclarationError> =
        discover_levels;
    let _: fn(
        Vec<(TermRule, String)>,
        &[Level],
        &[Replacement],
    ) -> Result<Vec<ResolvedRule>, DeclarationError> = resolve;
    let _: fn(&[(LocatorKind, &str)], u32) -> Vec<Locator> = redact_all;
    let _: fn(Vec<ResolvedRule>, &[String]) -> Result<Matcher, Unbuildable> = Matcher::new;
    let _: fn(&Matcher) -> &[ResolvedRule] = Matcher::rules;
    let _: fn(&Matcher, &str) -> Vec<usize> = Matcher::find;
    let _: fn(&Matcher, &str) -> Vec<Hit> = Matcher::hits;
    let _: fn(&Matcher, &str) -> usize = Matcher::exempted;
    let _: fn(&Matcher, &str) -> Replaced = Matcher::replace;
    let _: fn(&Matcher) -> Result<(), ReplacementCarriesTerm> = Matcher::check_replacements;
    let _: fn(&Matcher, &[(LocatorKind, &str)], u32) -> Vec<Locator> = Matcher::screen_locators;
}

/// One value of every enum variant and every struct, built from its stated fields.
fn samples() -> Samples {
    let declaration = Declaration {
        schema_version: 2,
        terms: vec!["quillmoss".to_owned()],
        exceptions: vec![Exception {
            term: "quillmoss".to_owned(),
            action: ExceptionAction::Drop,
        }],
        replacements: vec![
            Replacement::Replace {
                term: "quillmoss".to_owned(),
                with: "example".to_owned(),
            },
            Replacement::Reject {
                term: "vantorel".to_owned(),
            },
        ],
        phrases: vec!["quillmoss-bridge".to_owned()],
    };
    let rule = TermRule {
        term: "quillmoss".to_owned(),
        mode: TermMode::WholeWord,
        case_sensitive: false,
    };
    Samples {
        level: Level {
            kind: LevelKind::Repository,
            dir: PathBuf::from("/checkouts/example"),
            declaration: declaration.clone(),
        },
        resolved: ResolvedRule {
            rule: rule.clone(),
            action: Action::Replace("example".to_owned()),
            origin: "derived".to_owned(),
        },
        hit: Hit {
            rule: 0,
            span: Range { start: 4, end: 13 },
        },
        replaced: Replaced {
            text: "see example".to_owned(),
            replaced: 1,
            remaining: vec![],
        },
        error: DeclarationError {
            kind: DeclarationErrorKind::DuplicateEntry,
            member: Some(Member::Terms),
            entry: Some(2),
            path: Some(PathBuf::from("/checkouts/example/private-terms.toml")),
        },
        unbuildable: Unbuildable {
            reason: "a public phrase is empty once normalized".to_owned(),
        },
        carrying: ReplacementCarriesTerm { rule: 0 },
        declaration,
        rule,
    }
}

struct Samples {
    declaration: Declaration,
    rule: TermRule,
    level: Level,
    resolved: ResolvedRule,
    hit: Hit,
    replaced: Replaced,
    error: DeclarationError,
    unbuildable: Unbuildable,
    carrying: ReplacementCarriesTerm,
}

/// The bound every public type of Contract 0 meets, checked at compile time.
fn round_trips<T>(value: &T)
where
    T: Serialize + DeserializeOwned + JsonSchema + PartialEq + std::fmt::Debug,
{
    let json = serde_json::to_value(value).expect("serializes");
    let back: T = serde_json::from_value(json.clone()).expect("deserializes");
    assert_eq!(&back, value, "{json}");
    let schema = schemars::schema_for!(T);
    assert!(schema.as_value().is_object(), "a JSON schema");
}

#[test]
fn every_public_type_serializes_deserializes_and_has_a_schema() {
    let s = samples();
    for format in [Format::Toml, Format::Yaml] {
        round_trips(&format);
    }
    for kind in [
        LevelKind::Repository,
        LevelKind::Directory,
        LevelKind::Fallback,
    ] {
        round_trips(&kind);
    }
    round_trips(&s.declaration);
    round_trips(&s.declaration.exceptions[0]);
    for action in [
        ExceptionAction::Drop,
        ExceptionAction::WholeWord,
        ExceptionAction::CaseSensitive,
        ExceptionAction::OwnerNameOnly,
    ] {
        round_trips(&action);
    }
    for replacement in &s.declaration.replacements {
        round_trips(replacement);
    }
    round_trips(&s.level);
    for mode in [
        TermMode::Substring,
        TermMode::WholeWord,
        TermMode::OwnerNameOnly,
    ] {
        round_trips(&mode);
    }
    round_trips(&s.rule);
    round_trips(&Action::Reject);
    round_trips(&Action::Replace("example".to_owned()));
    round_trips(&s.resolved);
    round_trips(&s.hit);
    round_trips(&s.replaced);
    for kind in [
        LocatorKind::Source,
        LocatorKind::Item,
        LocatorKind::Field,
        LocatorKind::MetadataKey,
        LocatorKind::Comment,
        LocatorKind::Path,
        LocatorKind::Identity,
    ] {
        round_trips(&kind);
        round_trips(&Locator::Redacted { kind, ordinal: 2 });
    }
    round_trips(&Locator::Plain("README.md".to_owned()));
    round_trips(&s.error);
    round_trips(&DeclarationErrorKind::AmbiguousFiles);
    round_trips(&Member::Replacements);
    round_trips(&s.unbuildable);
    round_trips(&s.carrying);
}

#[test]
fn a_replacement_serializes_as_term_with_or_term_reject_true_exactly() {
    let replace = Replacement::Replace {
        term: "quillmoss".into(),
        with: "example".into(),
    };
    let reject = Replacement::Reject {
        term: "vantorel".into(),
    };
    assert_eq!(
        serde_json::to_value(&replace).unwrap(),
        json!({"term": "quillmoss", "with": "example"})
    );
    assert_eq!(
        serde_json::to_value(&reject).unwrap(),
        json!({"term": "vantorel", "reject": true})
    );
    assert_eq!(
        serde_json::from_value::<Replacement>(json!({"term": "quillmoss", "with": "example"}))
            .unwrap(),
        replace
    );
    assert_eq!(
        serde_json::from_value::<Replacement>(json!({"term": "vantorel", "reject": true})).unwrap(),
        reject
    );
    for refused in [
        json!({"term": "quillmoss", "with": "example", "reject": true}),
        json!({"term": "quillmoss"}),
        json!({"term": "quillmoss", "reject": false}),
        json!({"term": "quillmoss", "with": "example", "extra": 1}),
        json!({"with": "example"}),
    ] {
        assert!(
            serde_json::from_value::<Replacement>(refused.clone()).is_err(),
            "{refused} is refused"
        );
    }
}

#[test]
fn a_locator_serializes_as_a_string_or_exactly_the_redacted_object_and_displays() {
    let plain = Locator::Plain("docs/notes.md".into());
    let redacted = Locator::Redacted {
        kind: LocatorKind::Item,
        ordinal: 2,
    };
    assert_eq!(
        serde_json::to_value(&plain).unwrap(),
        json!("docs/notes.md")
    );
    assert_eq!(
        serde_json::to_string(&redacted).unwrap(),
        r#"{"redacted":true,"kind":"item","ordinal":2}"#
    );
    assert_eq!(
        serde_json::to_value(Locator::Redacted {
            kind: LocatorKind::MetadataKey,
            ordinal: 1
        })
        .unwrap(),
        json!({"redacted": true, "kind": "metadata-key", "ordinal": 1})
    );
    assert_eq!(plain.to_string(), "docs/notes.md");
    assert_eq!(redacted.to_string(), "<redacted item 2>");
    assert!(serde_json::from_value::<Locator>(
        json!({"redacted": false, "kind": "item", "ordinal": 2})
    )
    .is_err());
    assert!(serde_json::from_value::<Locator>(
        json!({"redacted": true, "kind": "item", "ordinal": 2, "value": "x"})
    )
    .is_err());
}

#[test]
fn a_declaration_deserialized_through_serde_is_validated() {
    assert!(serde_json::from_value::<Declaration>(
        json!({"schema_version": 1, "phrases": ["quillmoss-bridge"]})
    )
    .is_err());
    assert!(serde_json::from_value::<Declaration>(json!({"terms": ["quillmoss"]})).is_err());
    let declaration: Declaration =
        serde_json::from_value(json!({"schema_version": 1, "terms": ["quillmoss"]})).unwrap();
    assert_eq!(declaration.terms, ["quillmoss"]);
}
