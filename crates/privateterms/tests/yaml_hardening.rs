//! The YAML binding reads declarations safely: every hostile document is refused whole,
//! through the public `parse`, with no partial declaration; YAML 1.1 boolean words are
//! strings; and every YAML read in the crate goes through its one hardened options
//! function.

use privateterms::{parse, Declaration, DeclarationErrorKind, Format, LevelKind};

fn refused(document: &str) -> DeclarationErrorKind {
    let result: Result<Declaration, _> =
        parse(document.as_bytes(), Format::Yaml, LevelKind::Repository);
    match result {
        Ok(declaration) => panic!("a hostile document was read as {declaration:?}"),
        Err(error) => error.kind,
    }
}

#[test]
fn an_alias_expansion_bomb_is_refused() {
    let mut document = String::from("schema_version: 1\nlolz:\n  - &a0 [\"lol\", \"lol\", \"lol\", \"lol\", \"lol\", \"lol\", \"lol\", \"lol\"]\n");
    for level in 1..10 {
        let previous = level - 1;
        let refs = vec![format!("*a{previous}"); 8].join(", ");
        document.push_str(&format!("  - &a{level} [{refs}]\n"));
    }
    document.push_str("terms: *a9\n");
    assert_eq!(refused(&document), DeclarationErrorKind::Malformed);
}

#[test]
fn an_alias_bomb_in_a_known_member_is_refused_too() {
    let mut document = String::from("schema_version: 1\nterms: &a0 [\"quillmoss\"]\n");
    // Each level references the one before eight times: 8^9 strings if expanded.
    let mut anchors = String::new();
    for level in 1..10 {
        let refs = vec![format!("*a{}", level - 1); 8].join(", ");
        anchors.push_str(&format!("x{level}: &a{level} [{refs}]\n"));
    }
    document.push_str(&anchors);
    assert!(matches!(
        refused(&document),
        DeclarationErrorKind::Malformed | DeclarationErrorKind::UnknownMember
    ));
}

#[test]
fn a_document_nested_past_the_depth_bound_is_refused() {
    let depth = 64;
    let document = format!(
        "schema_version: 1\nterms: {}\"quillmoss\"{}\n",
        "[".repeat(depth),
        "]".repeat(depth)
    );
    assert_eq!(refused(&document), DeclarationErrorKind::Malformed);
}

#[test]
fn a_document_nested_past_the_depth_bound_in_block_style_is_refused() {
    let mut document = String::from("schema_version: 1\nterms:\n");
    for level in 0..40 {
        document.push_str(&"  ".repeat(level + 1));
        document.push_str("- \n");
    }
    assert_eq!(refused(&document), DeclarationErrorKind::Malformed);
}

#[test]
fn a_document_past_the_size_bound_is_refused_before_it_is_read() {
    let padding = "x".repeat(1024 * 1024);
    let document = format!("schema_version: 1\nterms: [\"{padding}\"]\n");
    assert_eq!(refused(&document), DeclarationErrorKind::TooLarge);
}

#[test]
fn a_document_just_under_the_size_bound_is_read() {
    let padding = "x".repeat(1024 * 1024 - 64);
    let document = format!("schema_version: 1\nterms: [\"{padding}\"]\n");
    assert!(document.len() < 1024 * 1024);
    let declaration = parse(document.as_bytes(), Format::Yaml, LevelKind::Repository)
        .expect("a document under the bound is read");
    assert_eq!(declaration.terms, [padding]);
}

#[test]
fn a_map_with_a_duplicate_key_is_refused() {
    assert_eq!(
        refused("schema_version: 1\nterms: [quillmoss]\nterms: [vantorel]\n"),
        DeclarationErrorKind::Malformed
    );
    assert_eq!(
        refused(
            "schema_version: 1\nexceptions:\n  - term: quillmoss\n    term: vantorel\n    action: drop\n"
        ),
        DeclarationErrorKind::Malformed
    );
}

#[test]
fn an_unknown_key_is_refused() {
    assert_eq!(
        refused("schema_version: 1\nterms: [quillmoss]\nextra_terms: [vantorel]\n"),
        DeclarationErrorKind::UnknownMember
    );
}

#[test]
fn a_custom_tag_is_refused() {
    assert_eq!(
        refused("schema_version: 1\nterms: !quilltag [quillmoss]\n"),
        DeclarationErrorKind::Malformed
    );
    assert_eq!(
        refused("schema_version: 1\nterms:\n  - !quilltag quillmoss\n"),
        DeclarationErrorKind::Malformed
    );
}

#[test]
fn a_merge_key_is_an_ordinary_key_and_so_an_unknown_member() {
    assert_eq!(
        refused("base: &base\n  terms: [quillmoss]\nschema_version: 1\n<<: *base\n"),
        DeclarationErrorKind::UnknownMember
    );
}

#[test]
fn yaml_1_1_boolean_words_read_as_strings_in_terms_and_phrases() {
    let document =
        "schema_version: 2\nterms: [yes, no, on, off, y, n]\nphrases: [yes, no, on, off]\n";
    let declaration = parse(document.as_bytes(), Format::Yaml, LevelKind::Repository)
        .expect("boolean words are strings");
    assert_eq!(declaration.terms, ["yes", "no", "on", "off", "y", "n"]);
    assert_eq!(declaration.phrases, ["yes", "no", "on", "off"]);
}

#[test]
fn every_yaml_read_in_the_crate_goes_through_the_one_hardened_options_function() {
    let source = concat!(env!("CARGO_MANIFEST_DIR"), "/src");
    let mut reads = Vec::new();
    let mut stack = vec![std::path::PathBuf::from(source)];
    while let Some(dir) = stack.pop() {
        for entry in std::fs::read_dir(&dir).expect("the source tree is readable") {
            let path = entry.expect("an entry").path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            let text = std::fs::read_to_string(&path).expect("a source file");
            for (number, line) in text.lines().enumerate() {
                let code = line.split("//").next().unwrap_or_default();
                for reader in ["serde_saphyr::from_", "serde_saphyr::Deserializer", "serde_saphyr::read"] {
                    if code.contains(reader) {
                        reads.push(format!(
                            "{}:{}",
                            path.strip_prefix(source).unwrap_or(&path).display(),
                            number + 1
                        ));
                    }
                }
                if code.contains("serde_saphyr::options!") {
                    reads.push(format!("options!@{}", path.display()));
                }
            }
        }
    }
    reads.sort();
    assert_eq!(reads.len(), 2, "YAML read sites and options: {reads:#?}");
    assert!(
        reads.iter().any(|site| site.starts_with("yaml.rs:")),
        "the only read is in src/yaml.rs: {reads:#?}"
    );
    assert!(
        reads
            .iter()
            .any(|site| site.starts_with("options!@") && site.ends_with("yaml/options.rs")),
        "the only options value is built in src/yaml/options.rs: {reads:#?}"
    );
    let yaml = std::fs::read_to_string(format!("{source}/yaml.rs")).expect("src/yaml.rs");
    assert!(
        yaml.contains("serde_saphyr::from_str_with_options(raw, options::options())"),
        "src/yaml.rs reads under options::options()"
    );
}
