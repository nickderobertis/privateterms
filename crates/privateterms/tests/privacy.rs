//! No error message or `Debug` rendering the crate produces discloses a term, a phrase,
//! a replacement or a path. The declarations here use invented spellings that occur in
//! neither the file path an error names (except where a test puts one there on purpose)
//! nor any fixed diagnostic text, and every rendering is searched for each of them.

use std::path::Path;

use privateterms::{
    discover_levels, parse, read_dir_level, resolve, Format, LevelKind, Matcher, Replacement,
    TermMode, TermRule,
};

/// Invented spellings: none is a word, a fixed diagnostic word or part of a temp path.
const SECRETS: [&str; 6] = [
    "zubrowqat",
    "vexillorn",
    "quorpamine",
    "trelvashi",
    "ombrizent",
    "kalthuvex",
];

fn assert_discloses_nothing(rendered: &str, also: &[&str]) {
    let lowered = rendered.to_lowercase();
    for secret in SECRETS.iter().chain(also) {
        assert!(
            !lowered.contains(&secret.to_lowercase()),
            "a rendering disclosed `{secret}`: {rendered}"
        );
    }
}

/// Every invalid declaration this test can build, each carrying the secrets.
fn hostile_documents() -> Vec<(String, Format, LevelKind)> {
    let [a, b, c, d, e, f] = SECRETS;
    let toml = |s: String| (s, Format::Toml, LevelKind::Directory);
    let yaml = |s: String| (s, Format::Yaml, LevelKind::Directory);
    vec![
        toml(format!("schema_version = 1\n{a} = [\"{b}\"]\n")),
        toml(format!("schema_version = 9\nterms = [\"{a}\"]\n")),
        toml(format!(
            "schema_version = 1\nterms = [\"{a}\"]\nphrases = [\"{b}\"]\n"
        )),
        toml(format!(
            "schema_version = 2\nterms = [\"{a}\", \"{}\"]\n",
            a.to_uppercase()
        )),
        toml(format!(
            "schema_version = 2\n[[replacements]]\nterm = \"{a}\"\nwith = \"{b}\"\nreject = true\n"
        )),
        toml(format!(
            "schema_version = 2\n[[replacements]]\nterm = \"{a}\"\nwith = \"{c}\"\n{d} = 1\n"
        )),
        toml(format!(
            "schema_version = 1\n[[exceptions]]\nterm = \"{a}\"\naction = \"drop\"\n"
        )),
        toml(format!(
            "schema_version = 1\n[[exceptions]]\nterm = \"{a}\"\naction = \"{e}\"\n"
        )),
        toml(format!("schema_version = 2\nphrases = [\"{f}\", \"\"]\n")),
        toml(format!("schema_version = 2\nterms = [\"{a}\"\n{b}")),
        toml(format!("{a} {b} = = \"{c}\"")),
        yaml(format!("schema_version: 2\nterms: [{a}]\nterms: [{b}]\n")),
        yaml(format!("schema_version: 2\nterms: !{a} [{b}]\n")),
        yaml(format!("schema_version: 2\nterms: [{a}\n  {b}: [")),
        yaml(format!("schema_version: 2\n{c}: &{d} [{e}]\nterms: *{d}\n")),
        yaml(format!("schema_version: \"{a}\"\nphrases: [{b}]\n")),
        yaml(format!("- {a}\n- {b}\n")),
    ]
}

#[test]
fn no_parse_error_discloses_a_term_or_phrase() {
    for (document, format, kind) in hostile_documents() {
        let error = parse(document.as_bytes(), format, kind)
            .expect_err("every hostile document is refused");
        assert_discloses_nothing(&error.to_string(), &[]);
        assert_discloses_nothing(&format!("{error:?}"), &[]);
        assert_discloses_nothing(&format!("{error:#?}"), &[]);
    }
}

#[test]
fn a_declaration_under_a_directory_named_with_a_term_renders_neither_the_name_nor_content() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let named = root.path().join(SECRETS[0]);
    std::fs::create_dir_all(&named).expect("a directory named with an invented term");
    let file = named.join("private-terms.toml");
    for (document, _, _) in hostile_documents()
        .into_iter()
        .filter(|(_, format, _)| *format == Format::Toml)
    {
        std::fs::write(&file, document).expect("a declaration file");
        let error = read_dir_level(&named, LevelKind::Directory).expect_err("refused");
        assert_eq!(
            error.path.as_deref(),
            Some(file.as_path()),
            "the path is a separate field"
        );
        let path_text = file.to_string_lossy().into_owned();
        assert_discloses_nothing(&error.to_string(), &[&path_text]);
        assert_discloses_nothing(&format!("{error:?}"), &[&path_text]);
        assert_discloses_nothing(&format!("{error:#?}"), &[&path_text]);
    }
    // Two files in that directory: the error is about the directory itself.
    std::fs::write(&file, "schema_version = 1\n").expect("a valid file");
    std::fs::write(named.join("private-terms.yml"), "schema_version: 1\n").expect("a second");
    let error = read_dir_level(&named, LevelKind::Directory).expect_err("ambiguous");
    assert_eq!(error.path.as_deref(), Some(named.as_path()));
    assert_discloses_nothing(&error.to_string(), &[]);
    assert_discloses_nothing(&format!("{error:?}"), &[]);
}

#[test]
fn a_discovery_error_renders_no_path() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let home = root.path().join("home");
    let level = home.join(SECRETS[1]);
    let checkout = level.join(SECRETS[2]);
    std::fs::create_dir_all(&checkout).expect("a checkout");
    std::fs::write(
        level.join("private-terms.yaml"),
        format!(
            "schema_version: 1\nexceptions: [{{term: {}, action: drop}}]\n",
            SECRETS[3]
        ),
    )
    .expect("a level");
    let error = discover_levels(&checkout, &home, None).expect_err("refused");
    assert_discloses_nothing(&error.to_string(), &[]);
    assert_discloses_nothing(&format!("{error:?}"), &[]);
}

#[test]
fn resolution_and_matcher_errors_disclose_nothing() {
    let level = privateterms::Level {
        kind: LevelKind::Repository,
        dir: Path::new(SECRETS[0]).to_path_buf(),
        declaration: parse(
            format!(
                "schema_version = 1\n[[exceptions]]\nterm = \"{}\"\naction = \"drop\"\n",
                SECRETS[1]
            )
            .as_bytes(),
            Format::Toml,
            LevelKind::Repository,
        )
        .expect("a valid repository declaration"),
    };
    let rule = |term: &str| {
        (
            TermRule {
                term: term.to_owned(),
                mode: TermMode::WholeWord,
                case_sensitive: false,
            },
            SECRETS[5].to_owned(),
        )
    };
    let error = resolve(vec![rule(SECRETS[2])], &[level], &[]).expect_err("names no term");
    assert_discloses_nothing(&error.to_string(), &[]);
    assert_discloses_nothing(&format!("{error:?}"), &[]);

    let resolved = resolve(
        vec![rule(SECRETS[2]), rule(SECRETS[3])],
        &[],
        &[Replacement::Replace {
            term: SECRETS[2].into(),
            with: format!("the {} project", SECRETS[3]),
        }],
    )
    .expect("resolves");
    let matcher = Matcher::new(resolved, &[SECRETS[4].to_owned()]).expect("builds");
    let carrying = matcher
        .check_replacements()
        .expect_err("the replacement carries a term");
    assert_discloses_nothing(&carrying.to_string(), &[]);
    assert_discloses_nothing(&format!("{carrying:?}"), &[]);

    let unbuildable = Matcher::new(Vec::new(), &["\u{200b}".to_owned()])
        .err()
        .expect("an empty phrase is refused");
    assert_discloses_nothing(&unbuildable.to_string(), &[]);
    assert_discloses_nothing(&format!("{unbuildable:?}"), &[]);
}
