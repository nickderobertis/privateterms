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
