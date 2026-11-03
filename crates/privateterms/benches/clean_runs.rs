//! Compare screening printable runs with visiting their characters, without a timer assertion.
use std::hint::black_box;
use std::time::{Duration, Instant};

use privateterms::{Action, Matcher, ResolvedRule, TermMode, TermRule};

fn measure(mut visit: impl FnMut()) -> Duration {
    let start = Instant::now();
    for _ in 0..20 {
        visit();
    }
    start.elapsed() / 20
}

fn main() {
    let runs: Vec<String> = (0..75_084)
        .map(|i| {
            let mut run = match i % 3 {
                0 => format!("solid panel {i:06} vertex 1.250 4.750"),
                1 => format!("模型 部件 {i:06} 三角形 顶点"),
                _ => format!("surface mesh {i:06} facet normal"),
            };
            if i % 1000 == 0 {
                run.push_str(" ｚｕｂｒｏｗ");
            } else if i % 20 == 0 {
                run.push_str(" QuIlLmOsS WoRkSh");
            }
            run
        })
        .collect();
    let terms: Vec<String> = (0..60)
        .map(|i| match i % 3 {
            0 => format!("Quillmoss Workshop {i}"),
            1 => format!("VÉLORIN {i}"),
            _ => format!("ｚｕｂｒｏｗｑａｔ {i}"),
        })
        .collect();
    let matcher = Matcher::new(
        terms
            .into_iter()
            .map(|term| ResolvedRule {
                rule: TermRule {
                    term,
                    mode: TermMode::Substring,
                    case_sensitive: false,
                },
                action: Action::Reject,
                origin: "benchmark".to_owned(),
            })
            .collect(),
        &[],
    )
    .unwrap();
    assert!(runs.iter().all(|run| matcher.hits(run).is_empty()));
    let visit = || {
        for run in &runs {
            for c in black_box(run).chars() {
                black_box(c);
            }
        }
    };
    let scan = || {
        for run in &runs {
            black_box(matcher.hits(black_box(run)));
        }
    };
    let mut baseline_samples = Vec::new();
    let mut scan_samples = Vec::new();
    for sample in 0..21 {
        // Alternate order so changes in host load do not favor either side.
        let (baseline, full) = if sample % 2 == 0 {
            (measure(visit), measure(scan))
        } else {
            let full = measure(scan);
            (measure(visit), full)
        };
        baseline_samples.push(baseline);
        scan_samples.push(full);
    }
    baseline_samples.sort();
    scan_samples.sort();
    let baseline = baseline_samples[baseline_samples.len() / 2];
    let scan = scan_samples[scan_samples.len() / 2];
    println!(
        "{} bytes, {} runs ({} non-ASCII), 60 terms, {} near-miss runs\nvisit: {baseline:?}\nmatcher: {scan:?}\nratio: {:.3}x",
        runs.iter().map(String::len).sum::<usize>(),
        runs.len(),
        runs.iter().filter(|run| !run.is_ascii()).count(),
        (0..runs.len()).filter(|i| i % 20 == 0).count(),
        scan.as_secs_f64() / baseline.as_secs_f64(),
    );
}
