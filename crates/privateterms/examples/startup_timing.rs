//! DEMONSTRATION ONLY, never lands: hosted timing of matcher construction and of one
//! long-lived matcher's throughput on non-matching Unicode text.
use std::hint::black_box;
use std::process::Command;
use std::time::Instant;

use privateterms::{Action, Matcher, ResolvedRule, TermMode, TermRule};

const RUN_LABEL: &str = "run-2";
const PROCESSES: usize = 30;
const PASSES: usize = 15;

fn matcher() -> (Matcher, u128) {
    let terms = [
        "quillmoss",
        "Vélorin",
        "zubrowqat",
        "owner/zubrow",
        "brennmark",
        "ștefanor",
        "Kåreholt",
        "ｍｉｒｖａｌｅ",
        "tessaly-ops",
        "corvinhal",
        "Østervang",
        "nightjar-labs",
        "pellucid",
        "Ἀρκάδι",
        "thornwick",
        "lumenreach",
        "ГРАНИТ",
        "vashtor",
        "émeraude-co",
        "quistel",
        "harrowgate",
        "selkirra",
        "dunmorrow",
        "ambervale",
    ];
    let rules = terms
        .iter()
        .enumerate()
        .map(|(i, term)| ResolvedRule {
            rule: TermRule {
                term: (*term).to_owned(),
                mode: [
                    TermMode::Substring,
                    TermMode::WholeWord,
                    TermMode::OwnerNameOnly,
                ][i % 3],
                case_sensitive: i % 4 == 0,
            },
            action: if i % 2 == 0 {
                Action::Replace("[redacted]".to_owned())
            } else {
                Action::Reject
            },
            origin: "timing".to_owned(),
        })
        .collect();
    let phrases = ["public quillmoss".to_owned()];
    let start = Instant::now();
    let matcher = Matcher::new(rules, &phrases).expect("rules compile");
    (matcher, start.elapsed().as_nanos())
}

fn corpus() -> Vec<String> {
    (0..20_000)
        .map(|i| match i % 5 {
            0 => format!("模型 部件 {i:06} 三角形 顶点 网格"),
            1 => format!("Добрый день, отчёт {i:06} готов к проверке"),
            2 => format!("café résumé naïve {i:06} façade coöperate"),
            3 => format!("🦀 ✓ build {i:06} — passed … ✔ ①②③"),
            _ => format!("Ελληνικά κείμενο {i:06} δοκιμή ﬁle ｆｕｌｌ"),
        })
        .collect()
}

fn main() {
    if std::env::args().nth(1).as_deref() == Some("child") {
        let (matcher, nanos) = matcher();
        black_box(&matcher);
        println!("{nanos}");
        return;
    }
    let exe = std::env::current_exe().expect("own path");
    let builds: Vec<f64> = (0..PROCESSES)
        .map(|_| {
            let out = Command::new(&exe)
                .arg("child")
                .output()
                .expect("child runs");
            assert!(out.status.success());
            String::from_utf8(out.stdout)
                .unwrap()
                .trim()
                .parse::<f64>()
                .unwrap()
                / 1e6
        })
        .collect();
    let (matcher, _) = matcher();
    let corpus = corpus();
    let bytes: usize = corpus.iter().map(String::len).sum();
    assert!(
        corpus.iter().all(|text| matcher.find(text).is_empty()),
        "corpus must not match"
    );
    let rates: Vec<f64> = (0..PASSES)
        .map(|_| {
            let start = Instant::now();
            for text in &corpus {
                black_box(matcher.find(black_box(text)));
            }
            bytes as f64 / start.elapsed().as_secs_f64() / 1e6
        })
        .collect();
    let mean = |v: &[f64]| v.iter().sum::<f64>() / v.len() as f64;
    println!(
        "STARTUP-TIMING label={RUN_LABEL} os={} build_ms_mean={:.3} build_ms_min={:.3} build_ms_max={:.3} processes={PROCESSES} throughput_mb_s_mean={:.3} throughput_mb_s_min={:.3} throughput_mb_s_max={:.3} passes={PASSES} corpus_bytes={bytes}",
        std::env::consts::OS,
        mean(&builds),
        builds.iter().cloned().fold(f64::MAX, f64::min),
        builds.iter().cloned().fold(0.0, f64::max),
        mean(&rates),
        rates.iter().cloned().fold(f64::MAX, f64::min),
        rates.iter().cloned().fold(0.0, f64::max),
    );
    println!("STARTUP-TIMING-BUILDS label={RUN_LABEL} {builds:?}");
    println!("STARTUP-TIMING-RATES label={RUN_LABEL} {rates:?}");
}
