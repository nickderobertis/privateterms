//! Independent printable runs use the same matching and original byte spans as whole texts.
use privateterms::{Action, Hit, Matcher, ResolvedRule, TermMode, TermRule};

fn matcher() -> Matcher {
    Matcher::new(
        ["quillmoss", "vélorin", "fi", "i", "가"]
            .into_iter()
            .map(|term| ResolvedRule {
                rule: TermRule {
                    term: term.to_owned(),
                    mode: TermMode::Substring,
                    case_sensitive: false,
                },
                action: Action::Reject,
                origin: "test".to_owned(),
            })
            .collect(),
        &[],
    )
    .unwrap()
}

#[test]
fn mixed_runs_keep_original_spans_and_do_not_carry_state() {
    let matcher = matcher();
    let runs = [
        ("模型 mesh", vec![]),
        (
            "模型 QUILLMOSS 木",
            vec![
                Hit {
                    rule: 0,
                    span: 7..16,
                },
                Hit {
                    rule: 3,
                    span: 9..10,
                },
            ],
        ),
        ("surface 木", vec![]),
        (
            "木 VE\u{301}LORIN",
            vec![
                Hit {
                    rule: 1,
                    span: 4..13,
                },
                Hit {
                    rule: 3,
                    span: 11..12,
                },
            ],
        ),
        ("mesh 模型", vec![]),
        (
            "木 ﬁ İ 가",
            vec![
                Hit {
                    rule: 2,
                    span: 4..7,
                },
                Hit {
                    rule: 3,
                    span: 4..7,
                },
                Hit {
                    rule: 3,
                    span: 8..10,
                },
                Hit {
                    rule: 4,
                    span: 11..17,
                },
            ],
        ),
        ("panel 木", vec![]),
    ];
    for _ in 0..2 {
        for (text, expected) in &runs {
            assert_eq!(matcher.hits(text), *expected, "{text}");
            let mut rules: Vec<usize> = expected.iter().map(|hit| hit.rule).collect();
            rules.sort_unstable();
            rules.dedup();
            assert_eq!(matcher.find(text), rules);
        }
    }
}

#[test]
fn unstable_clean_runs_and_normalized_candidates_keep_original_spans() {
    let matcher = matcher();
    for text in [
        "ＡＢＣ\u{301}\u{200d}Ω",
        "\u{ad}\u{200d}\u{feff}",
        "ΩΩ ＢＢ 木",
    ] {
        assert!(matcher.hits(text).is_empty());
    }
    for (text, expected) in [
        ("\u{200d}ＱＵＩＬＬＭＯＳＳ", 3..30),
        ("Ａ\u{301} Ω quill\u{200d}moss Ｂ", 9..21),
    ] {
        let hits = matcher.hits(text);
        assert_eq!(
            hits.iter().find(|hit| hit.rule == 0).unwrap().span,
            expected
        );
    }
}

#[test]
fn contextual_lowercase_and_composition_can_supply_candidates() {
    for (term, text) in [("ος", "ΟΣ"), ("é", "e\u{301}"), ("가", "ᄀ\u{200d}ᅡ")] {
        let matcher = Matcher::new(
            vec![ResolvedRule {
                rule: TermRule {
                    term: term.to_owned(),
                    mode: TermMode::Substring,
                    case_sensitive: false,
                },
                action: Action::Reject,
                origin: "test".to_owned(),
            }],
            &[],
        )
        .unwrap();
        assert_eq!(
            matcher.hits(text),
            vec![Hit {
                rule: 0,
                span: 0..text.len()
            }]
        );
    }
}

#[test]
fn untracked_components_and_terms_without_letters_still_match() {
    let terms: Vec<String> = (0x400..0x460)
        .filter_map(char::from_u32)
        .map(|c| c.to_string())
        .chain(["123".to_owned(), "!!!".to_owned()])
        .collect();
    let matcher = Matcher::new(
        terms
            .iter()
            .map(|term| ResolvedRule {
                rule: TermRule {
                    term: term.clone(),
                    mode: TermMode::Substring,
                    case_sensitive: true,
                },
                action: Action::Reject,
                origin: "test".to_owned(),
            })
            .collect(),
        &[],
    )
    .unwrap();
    for (rule, term) in terms.iter().enumerate() {
        assert!(matcher.hits(term).contains(&Hit {
            rule,
            span: 0..term.len()
        }));
    }
    assert!(matcher.hits("ＡＢＣ").is_empty());
}
