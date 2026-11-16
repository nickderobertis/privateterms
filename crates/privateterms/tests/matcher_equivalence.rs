//! Every find, hit, replacement, exemption and locator screening answers what the
//! matcher at 6295b22 answered, before its construction was made cheaper.
//!
//! `golden/matcher-equivalence.json` holds those answers, recorded by running this test
//! at 6295b22 with `PRIVATETERMS_RECORD_EQUIVALENCE=1`. It lists only the texts whose
//! answer is not the empty one (no hit, the text unchanged, the locator plain); every
//! other text must still answer the empty one.
use std::collections::BTreeMap;
use std::path::PathBuf;

use privateterms::{
    Action, Hit, Locator, LocatorKind, Matcher, Replaced, ResolvedRule, TermMode, TermRule,
};
use serde::{Deserialize, Serialize};

const RECORD: &str = "PRIVATETERMS_RECORD_EQUIVALENCE";

/// Terms whose characters arrive through decompositions, case mappings, final sigma and
/// Hangul syllables, beside plain ASCII ones.
const TERMS: [&str; 9] = [
    "quillmoss",
    "Vélorin",
    "ﬃ",
    "σ",
    "İ",
    "가",
    "owner/zubrow",
    "Ω",
    "straße",
];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct Outcome {
    find: Vec<usize>,
    hits: Vec<Hit>,
    replaced: Replaced,
    exempted: usize,
    locators: Vec<Locator>,
}

impl Outcome {
    fn of(matcher: &Matcher, text: &str) -> Outcome {
        Outcome {
            find: matcher.find(text),
            hits: matcher.hits(text),
            replaced: matcher.replace(text),
            exempted: matcher.exempted(text),
            locators: matcher.screen_locators(&[(LocatorKind::Path, text)], 3),
        }
    }

    fn empty(text: &str) -> Outcome {
        Outcome {
            find: Vec::new(),
            hits: Vec::new(),
            replaced: Replaced {
                text: text.to_owned(),
                replaced: 0,
                remaining: Vec::new(),
            },
            exempted: 0,
            locators: vec![Locator::Plain(text.to_owned())],
        }
    }
}

/// One matcher's non-empty answers, by text.
#[derive(Debug, PartialEq, Serialize, Deserialize)]
struct Recorded {
    mode: TermMode,
    case_sensitive: bool,
    outcomes: BTreeMap<String, Outcome>,
}

fn matcher(mode: TermMode, case_sensitive: bool) -> Matcher {
    let rules = TERMS
        .iter()
        .enumerate()
        .map(|(index, term)| ResolvedRule {
            rule: TermRule {
                term: (*term).to_owned(),
                mode,
                case_sensitive,
            },
            action: if index % 2 == 0 {
                Action::Replace("[redacted]".to_owned())
            } else {
                Action::Reject
            },
            origin: "equivalence".to_owned(),
        })
        .collect();
    Matcher::new(rules, &["public quillmoss".to_owned()]).expect("the rules compile")
}

/// Texts that reach a term only through normalization or folding, texts a phrase
/// exempts, and texts the contributor prefilter rejects; then every 1021st code point
/// and every letterlike one, in place of one letter of a term, so each hits exactly
/// where it folds to that letter, and the strided ones alone too.
fn texts() -> Vec<String> {
    let curated = [
        "quillmoss",
        "QUILLMOSS in the log",
        "ｑｕｉｌｌｍｏｓｓ",
        "𝐪𝐮𝐢𝐥𝐥𝐦𝐨𝐬𝐬",
        "ⓠⓤⓘⓛⓛⓜⓞⓢⓢ",
        "quill\u{200b}moss",
        "quill\u{ad}moss",
        "a public quillmoss here",
        "PUBLIC QUILLMOSS",
        "public quillmoss-tools",
        "quillmosses",
        "xquillmoss",
        "vélorin",
        "ve\u{301}lorin",
        "VÉLORIN",
        "VE\u{301}LORIN",
        "velorin",
        "ffi",
        "ﬃ",
        "ﬀi",
        "office",
        "σ",
        "ς",
        "Σ",
        "ΟΔΟΣ",
        "οδος",
        "İ",
        "i\u{307}",
        "I",
        "ı",
        "가",
        "\u{1100}\u{1161}",
        "각",
        "ＧＡ 가나다",
        "owner/zubrow",
        "OWNER/ZUBROW.git",
        "owner/zubrow.gitx",
        "owner/zubrow-two",
        "fork-owner/zubrow",
        "ｏｗｎｅｒ／ｚｕｂｒｏｗ",
        "Ω",
        "\u{2126}",
        "ω",
        "straße",
        "STRASSE",
        "strasse",
        "straſſe",
        "Kelvin K and Å",
        "模型 部件 三角形 顶点",
        "Добрый день",
        "مرحبا",
        "🦀 ✓ — …",
        "plain ascii with nothing",
        "",
    ];
    let mut texts: Vec<String> = curated.iter().map(|text| (*text).to_owned()).collect();
    for c in (0..=0x10ffff).step_by(1021).filter_map(char::from_u32) {
        texts.push(c.to_string());
        texts.push(format!("quillmo{c}s"));
        texts.push(format!("v{c}lorin ο{c}"));
    }
    let letterlike = [
        0xc0..=0x24f,
        0x1e00..=0x1eff,
        0x2100..=0x214f,
        0x2460..=0x24ff,
        0xff00..=0xffef,
        0x1d400..=0x1d7ff,
    ];
    for c in letterlike.into_iter().flatten().filter_map(char::from_u32) {
        texts.push(format!("quillmo{c}s"));
        texts.push(format!("v{c}lorin ο{c}"));
    }
    texts
}

fn golden() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/golden/matcher-equivalence.json")
}

fn record_requested() -> bool {
    match std::env::var(RECORD) {
        Err(std::env::VarError::NotPresent) => false,
        Ok(value) if value == "1" => true,
        other => panic!("{RECORD} is either unset or 1, not {other:?}"),
    }
}

fn configurations() -> Vec<(TermMode, bool)> {
    [
        TermMode::Substring,
        TermMode::WholeWord,
        TermMode::OwnerNameOnly,
    ]
    .into_iter()
    .flat_map(|mode| [(mode, false), (mode, true)])
    .collect()
}

#[test]
fn every_public_answer_is_the_base_commits() {
    let texts = texts();
    let measured: Vec<Recorded> = configurations()
        .into_iter()
        .map(|(mode, case_sensitive)| {
            let matcher = matcher(mode, case_sensitive);
            let outcomes = texts
                .iter()
                .map(|text| (text.clone(), Outcome::of(&matcher, text)))
                .filter(|(text, outcome)| *outcome != Outcome::empty(text))
                .collect();
            Recorded {
                mode,
                case_sensitive,
                outcomes,
            }
        })
        .collect();
    if record_requested() {
        let json = serde_json::to_string_pretty(&measured).expect("outcomes serialize") + "\n";
        std::fs::write(golden(), json).expect("the golden is writable");
        return;
    }
    let recorded: Vec<Recorded> =
        serde_json::from_str(&std::fs::read_to_string(golden()).expect("the golden is checked in"))
            .expect("the golden parses");
    assert_eq!(
        recorded.len(),
        measured.len(),
        "one record per configuration"
    );
    for (recorded, measured) in recorded.iter().zip(&measured) {
        assert_eq!(
            (recorded.mode, recorded.case_sensitive),
            (measured.mode, measured.case_sensitive)
        );
        for (text, outcome) in &recorded.outcomes {
            assert!(
                texts.contains(text),
                "the golden records an unasked {text:?}"
            );
            assert_eq!(
                measured.outcomes.get(text),
                Some(outcome),
                "{:?}, case-sensitive {}: {text:?}",
                measured.mode,
                measured.case_sensitive
            );
        }
        for text in measured.outcomes.keys() {
            assert!(
                recorded.outcomes.contains_key(text),
                "{:?}, case-sensitive {}: {text:?} now has an answer it did not have",
                measured.mode,
                measured.case_sensitive
            );
        }
    }
}

#[test]
fn the_record_holds_hits_reached_only_through_normalization() {
    let recorded: Vec<Recorded> =
        serde_json::from_str(&std::fs::read_to_string(golden()).expect("the golden is checked in"))
            .expect("the golden parses");
    let folded = &recorded[0];
    assert_eq!(
        (folded.mode, folded.case_sensitive),
        (TermMode::Substring, false)
    );
    for text in [
        "𝐪𝐮𝐢𝐥𝐥𝐦𝐨𝐬𝐬",
        "ve\u{301}lorin",
        "ﬀi",
        "\u{1100}\u{1161}",
        "\u{2126}",
        "quillmoſs",
        "quillmo𝓈s",
        "v𝛔lorin ο𝛔",
    ] {
        assert!(
            !folded.outcomes[text].find.is_empty(),
            "{text:?} is recorded as a hit"
        );
    }
    assert!(!folded.outcomes.contains_key("模型 部件 三角形 顶点"));
    assert_eq!(folded.outcomes["a public quillmoss here"].exempted, 1);
}
