//! The crate's own storage bindings — file names, the TOML and YAML encodings and level
//! discovery — driven through the public API over real files. None of this is the
//! specification's: these are the bindings onevcs and onetaskgraph consume.

use std::path::Path;

use privateterms::{
    discover_levels, parse, read_dir_level, to_toml, to_yaml, Declaration, DeclarationErrorKind,
    Exception, ExceptionAction, Format, LevelKind, Replacement, FILE_NAMES,
};

fn write(dir: &Path, name: &str, text: &str) {
    std::fs::create_dir_all(dir).expect("a directory");
    std::fs::write(dir.join(name), text).expect("a declaration file");
}

const V1_TOML: &str = r#"
schema_version = 1
terms = ["quillmoss", "vantorel"]

[[exceptions]]
term = "quillmoss"
action = "case-sensitive"
"#;

const V1_YAML: &str = r#"
schema_version: 1
terms:
  - quillmoss
  - vantorel
exceptions:
  - term: quillmoss
    action: case-sensitive
"#;

const V2_TOML: &str = r#"
schema_version = 2
terms = ["ostrevane"]
phrases = ["ostrevane-bridge", "on"]

[[replacements]]
term = "ostrevane"
with = "example-project"

[[replacements]]
term = "pellucine"
reject = true
"#;

const V2_YAML: &str = r#"
schema_version: 2
terms: [ostrevane]
phrases: [ostrevane-bridge, on]
replacements:
  - term: ostrevane
    with: example-project
  - {term: pellucine, reject: true}
"#;

fn v1() -> Declaration {
    Declaration {
        schema_version: 1,
        terms: vec!["quillmoss".into(), "vantorel".into()],
        exceptions: vec![Exception {
            term: "quillmoss".into(),
            action: ExceptionAction::CaseSensitive,
        }],
        replacements: vec![],
        phrases: vec![],
    }
}

fn v2() -> Declaration {
    Declaration {
        schema_version: 2,
        terms: vec!["ostrevane".into()],
        exceptions: vec![],
        replacements: vec![
            Replacement::Replace {
                term: "ostrevane".into(),
                with: "example-project".into(),
            },
            Replacement::Reject {
                term: "pellucine".into(),
            },
        ],
        phrases: vec!["ostrevane-bridge".into(), "on".into()],
    }
}

#[test]
fn version_1_and_2_files_in_toml_and_yaml_give_identical_declarations() {
    let home = tempfile::tempdir().expect("a temporary directory");
    for (index, (name, text, kind, expected)) in [
        ("private-terms.toml", V1_TOML, LevelKind::Repository, v1()),
        ("private-terms.yaml", V1_YAML, LevelKind::Repository, v1()),
        ("private-terms.yml", V1_YAML, LevelKind::Repository, v1()),
        ("private-terms.toml", V2_TOML, LevelKind::Directory, v2()),
        ("private-terms.yaml", V2_YAML, LevelKind::Directory, v2()),
        ("private-terms.yml", V2_YAML, LevelKind::Fallback, v2()),
    ]
    .into_iter()
    .enumerate()
    {
        let dir = home.path().join(format!("case-{index}"));
        write(&dir, name, text);
        let level = read_dir_level(&dir, kind)
            .expect("a valid declaration file is read")
            .expect("the directory holds one");
        assert_eq!(level.declaration, expected, "{name}");
        assert_eq!(level.kind, kind);
        assert_eq!(level.dir, dir);
    }
}

#[test]
fn the_three_file_names_are_the_bindings() {
    assert_eq!(
        FILE_NAMES,
        [
            "private-terms.toml",
            "private-terms.yaml",
            "private-terms.yml"
        ]
    );
    let dir = tempfile::tempdir().expect("a temporary directory");
    write(dir.path(), "private-terms.json", "{\"schema_version\": 1}");
    write(dir.path(), "terms.toml", "schema_version = 1\n");
    assert!(read_dir_level(dir.path(), LevelKind::Directory)
        .expect("other names are not declarations")
        .is_none());
}

#[test]
fn both_encodings_write_what_parse_reads_back() {
    for declaration in [v1(), v2()] {
        let kind = if declaration.exceptions.is_empty() {
            LevelKind::Directory
        } else {
            LevelKind::Repository
        };
        let toml = to_toml(&declaration);
        let yaml = to_yaml(&declaration);
        assert_eq!(
            parse(toml.as_bytes(), Format::Toml, kind).expect("TOML"),
            declaration
        );
        assert_eq!(
            parse(yaml.as_bytes(), Format::Yaml, kind).expect("YAML"),
            declaration
        );
    }
}

#[test]
fn two_declaration_files_in_one_directory_are_refused_as_ambiguous() {
    let pairs = [
        ("private-terms.toml", "private-terms.yaml"),
        ("private-terms.toml", "private-terms.yml"),
        ("private-terms.yaml", "private-terms.yml"),
    ];
    for (a, b) in pairs {
        let dir = tempfile::tempdir().expect("a temporary directory");
        write(
            dir.path(),
            a,
            if a.ends_with("toml") {
                V1_TOML
            } else {
                V1_YAML
            },
        );
        write(dir.path(), b, V1_YAML);
        let error = read_dir_level(dir.path(), LevelKind::Repository)
            .expect_err("two files in one directory are refused");
        assert_eq!(
            error.kind,
            DeclarationErrorKind::AmbiguousFiles,
            "{a} + {b}"
        );
        assert_eq!(error.path.as_deref(), Some(dir.path()));
    }
}

#[test]
fn level_discovery_walks_a_real_tree_nearest_first() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let home = root.path().join("home");
    let outer = home.join("work");
    let inner = outer.join("clients");
    let checkout = inner.join("quillmoss");
    let fallback = root.path().join("host-fallback");
    write(
        &checkout,
        "private-terms.toml",
        "schema_version = 1\nterms = [\"r1\"]\n",
    );
    write(
        &inner,
        "private-terms.yaml",
        "schema_version: 1\nterms: [a1]\n",
    );
    write(
        &outer,
        "private-terms.yml",
        "schema_version: 2\nterms: [a2]\n",
    );
    write(
        &home,
        "private-terms.toml",
        "schema_version = 2\nterms = [\"h1\"]\n",
    );
    write(
        &fallback,
        "private-terms.yaml",
        "schema_version: 2\nterms: [f1]\n",
    );
    // Above the home directory nothing is read, even a declaration that is there.
    write(
        root.path(),
        "private-terms.toml",
        "not = valid toml = at all",
    );

    let levels = discover_levels(&checkout, &home, Some(&fallback)).expect("every level reads");
    let seen: Vec<(LevelKind, &Path, &str)> = levels
        .iter()
        .map(|level| {
            (
                level.kind,
                level.dir.as_path(),
                level.declaration.terms[0].as_str(),
            )
        })
        .collect();
    assert_eq!(
        seen,
        [
            (LevelKind::Repository, checkout.as_path(), "r1"),
            (LevelKind::Directory, inner.as_path(), "a1"),
            (LevelKind::Directory, outer.as_path(), "a2"),
            (LevelKind::Directory, home.as_path(), "h1"),
            (LevelKind::Fallback, fallback.as_path(), "f1"),
        ]
    );
}

#[test]
fn a_directory_without_a_declaration_adds_no_level() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let home = root.path().join("home");
    let checkout = home.join("a").join("b").join("repo");
    std::fs::create_dir_all(&checkout).expect("a checkout");
    write(
        &home.join("a"),
        "private-terms.yml",
        "schema_version: 1\nterms: [a1]\n",
    );
    let levels = discover_levels(&checkout, &home, None).expect("levels");
    assert_eq!(levels.len(), 1);
    assert_eq!(levels[0].kind, LevelKind::Directory);
    assert_eq!(levels[0].dir, home.join("a"));
}

#[test]
fn a_checkout_outside_home_walks_up_to_but_excluding_the_root() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let home = root.path().join("home");
    let checkout = root.path().join("srv").join("repo");
    std::fs::create_dir_all(&home).expect("a home");
    write(
        &root.path().join("srv"),
        "private-terms.toml",
        "schema_version = 1\nterms = [\"s1\"]\n",
    );
    // The home directory is not an ancestor of this checkout, so it is not read.
    write(
        &home,
        "private-terms.toml",
        "schema_version = 1\nterms = [\"h1\"]\n",
    );
    let levels = discover_levels(&checkout, &home, None).expect("levels");
    let terms: Vec<&str> = levels
        .iter()
        .map(|l| l.declaration.terms[0].as_str())
        .collect();
    assert!(
        terms.contains(&"s1"),
        "the checkout's ancestor is read: {terms:?}"
    );
    assert!(
        !terms.contains(&"h1"),
        "a home that is not an ancestor is not read: {terms:?}"
    );
    let filesystem_root = checkout.ancestors().last().expect("a root");
    assert!(levels.iter().all(|level| level.dir != filesystem_root));
}

#[test]
fn a_checkout_that_is_home_has_only_its_own_level() {
    let home = tempfile::tempdir().expect("a temporary directory");
    write(home.path(), "private-terms.toml", "schema_version = 1\n");
    let levels = discover_levels(home.path(), home.path(), None).expect("levels");
    assert_eq!(levels.len(), 1);
    assert_eq!(levels[0].kind, LevelKind::Repository);
}

#[test]
fn an_invalid_or_unreadable_level_fails_discovery_naming_its_file() {
    let root = tempfile::tempdir().expect("a temporary directory");
    let home = root.path().join("home");
    let checkout = home.join("repo");
    std::fs::create_dir_all(&checkout).expect("a checkout");
    // A directory level declaring exceptions is invalid for its kind.
    write(&home, "private-terms.toml", V1_TOML);
    let error = discover_levels(&checkout, &home, None).expect_err("refused");
    assert_eq!(
        error.kind,
        DeclarationErrorKind::ExceptionsOutsideRepository
    );
    assert_eq!(error.path, Some(home.join("private-terms.toml")));

    // A declaration name that is a directory cannot be read.
    std::fs::remove_file(home.join("private-terms.toml")).expect("removed");
    std::fs::create_dir(home.join("private-terms.yml")).expect("a directory in its place");
    let error = discover_levels(&checkout, &home, None).expect_err("refused");
    assert_eq!(error.kind, DeclarationErrorKind::Unreadable);
    assert_eq!(error.path, Some(home.join("private-terms.yml")));
}

#[test]
fn a_document_that_does_not_parse_or_is_not_utf8_is_malformed() {
    // onevcs v0.57.6's phrase-file tests that are about its file's own encoding.
    for (bytes, format) in [
        (
            &b"schema_version: 2\nphrases: [\"rig-zorv\"\n"[..],
            Format::Yaml,
        ),
        (
            &b"schema_version = 2\nphrases = [\"rig-zorv\"\n"[..],
            Format::Toml,
        ),
        (
            &b"schema_version: 2\nphrases: [\"\xff\"]\n"[..],
            Format::Yaml,
        ),
        (
            &b"schema_version = 1\nterms = [\"\xff\"]\n"[..],
            Format::Toml,
        ),
    ] {
        let error = parse(bytes, format, LevelKind::Fallback).expect_err("refused");
        assert_eq!(error.kind, DeclarationErrorKind::Malformed);
    }
}

#[test]
fn a_toml_duplicate_key_is_malformed() {
    let error = parse(
        b"schema_version = 1\nterms = [\"a1\"]\nterms = [\"b1\"]\n",
        Format::Toml,
        LevelKind::Repository,
    )
    .expect_err("refused");
    assert_eq!(error.kind, DeclarationErrorKind::Malformed);
}
