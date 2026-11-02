//! A consumer of the privateterms crate, built against the crate as a dependent gets
//! it — the packaged `.crate`, or the published release — and run: it reads a
//! declaration file from a real directory tree, resolves, detects, replaces and screens
//! locators, and exits non-zero on any departure.

use std::process::ExitCode;

use privateterms::{
    discover_levels, resolve, LevelKind, Locator, LocatorKind, Matcher, TermMode, TermRule,
    SPEC_VERSION,
};

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(problem) => {
            eprintln!("consumer smoke: {problem}");
            ExitCode::FAILURE
        }
    }
}

fn run() -> Result<(), String> {
    if SPEC_VERSION != 1 {
        return Err(format!("expected specification 1, got {SPEC_VERSION}"));
    }
    let root = std::env::temp_dir().join(format!("privateterms-smoke-{}", std::process::id()));
    let home = root.join("home");
    let checkout = home.join("work").join("quillmoss");
    std::fs::create_dir_all(&checkout).map_err(|e| e.to_string())?;
    std::fs::write(
        home.join("work").join("private-terms.yaml"),
        "schema_version: 2\nreplacements:\n  - {term: quillmoss, with: example}\nphrases: [quillmoss-bridge]\n",
    )
    .map_err(|e| e.to_string())?;
    std::fs::write(
        checkout.join("private-terms.toml"),
        "schema_version = 1\nterms = [\"vantorel\"]\n",
    )
    .map_err(|e| e.to_string())?;
    let outcome = check(&checkout, &home);
    let _ = std::fs::remove_dir_all(&root);
    outcome
}

fn check(checkout: &std::path::Path, home: &std::path::Path) -> Result<(), String> {
    let levels = discover_levels(checkout, home, None).map_err(|e| e.to_string())?;
    let kinds: Vec<LevelKind> = levels.iter().map(|l| l.kind).collect();
    if kinds != [LevelKind::Repository, LevelKind::Directory] {
        return Err(format!("unexpected levels {kinds:?}"));
    }
    let derived = vec![(
        TermRule {
            term: "quillmoss".into(),
            mode: TermMode::WholeWord,
            case_sensitive: false,
        },
        "derived".to_owned(),
    )];
    let phrases: Vec<String> = levels
        .iter()
        .flat_map(|l| l.declaration.phrases.clone())
        .collect();
    let rules = resolve(derived, &levels, &[]).map_err(|e| e.to_string())?;
    let matcher = Matcher::new(rules, &phrases).map_err(|e| e.to_string())?;
    let replaced = matcher.replace("ship quillmoss over the quillmoss-bridge");
    if replaced.text != "ship example over the quillmoss-bridge" || !replaced.remaining.is_empty() {
        return Err(format!("unexpected replacement {:?}", replaced.text));
    }
    if matcher.find("vantorel was here").is_empty() {
        return Err("the repository's own term was not found".into());
    }
    let screened = matcher.screen_locators(&[(LocatorKind::Path, "vantorel/notes.md")], 1);
    if screened
        != [Locator::Redacted {
            kind: LocatorKind::Path,
            ordinal: 1,
        }]
    {
        return Err(format!("unexpected locators {screened:?}"));
    }
    Ok(())
}
