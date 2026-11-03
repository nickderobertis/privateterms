# Private terms — Specification 1

This is the one normative statement of how a private term is declared, found, replaced
and rejected in text that is about to be made public. It defines a **data model** and
what an implementation does with it. It defines **no file format, file name or directory
layout**, and states no rule for how a declaration is parsed or stored: how an
implementation reads declarations from storage, and how it finds them, is that
implementation's own *binding* of the model. Any TOML or YAML in this document is an
**illustration** of the model, not a format it requires.

The conformance suite in [`conformance/`](../conformance/) is this specification's
executable form. Every rule below carries an identifier in brackets, and a `Cases:` line
naming the conformance case files that exercise it; every conformance case names, in
its `exercises` list, the rules it exercises. The two are reconciled by the reference
implementation's test suite, so neither can drift from the other.

The words **must**, **must not** and **is** state requirements. Spans are byte offsets
into the UTF-8 encoding of the text they are spans of.

## 1. The declaration

A **declaration** is a mapping with these members, each optional except the model
version:

| Member | Value | From version |
|---|---|---|
| `schema_version` | the model version: the whole number 1 or 2 | 1 |
| `terms` | a list of strings | 1 |
| `exceptions` | a list of exceptions, each `{term, action}` | 1 |
| `replacements` | a list of replacement entries | 2 |
| `phrases` | a list of strings | 2 |

**[DECL-VERSION]** A declaration carries its model version, 1 or 2. Version 1 defines
`terms` and `exceptions`; version 2 adds `replacements` and `phrases`. An absent member
is an empty list.
Cases: `conformance/cases/declaration.json`.

**[DECL-TERMS]** Each entry of `terms` adds a term, matched as a whole word and not
case-sensitive (section 3).
Cases: `conformance/cases/declaration.json`, `conformance/cases/precedence.json`.

**[DECL-EXCEPTIONS]** Each entry of `exceptions` is `{term, action}`, where `action` is
one of `drop`, `whole-word`, `case-sensitive` or `owner-name-only`. Only a repository's
own declaration may carry exceptions, and an exception only ever narrows the rules it
reaches (rule LEVEL-OWN-RULES says which, and how).
Cases: `conformance/cases/declaration.json`, `conformance/cases/precedence.json`, `conformance/cases/unavailable.json`.

**[DECL-REPLACEMENTS]** From version 2, each entry of `replacements` is either
`{term, with}` — replace the term's hits with the string `with` — or
`{term, reject: true}` — reject the term — and exactly one of the two. An entry naming a
term no rule carries adds that term as a whole-word, not case-sensitive term.
Cases: `conformance/cases/declaration.json`, `conformance/cases/precedence.json`.

**[DECL-PHRASES]** From version 2, each entry of `phrases` is a **public phrase**: text
declared public even though a term occurs inside it (rules MATCH-PHRASE-STANDS and
MATCH-PHRASE-EXEMPT). Phrases that are one once normalized and folded (section 3) are
kept once, the first as written.
Cases: `conformance/cases/declaration.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`, `conformance/cases/onevcs-v0.57.6-phrases.json`.

**[DECL-INVALID]** An implementation must refuse an invalid declaration whole — never
reading some smaller declaration out of it. A declaration is invalid where:

1. it carries a member the model does not define, or an exception or replacement entry
   carries one (`unknown-member`);
2. its model version is absent, not a whole number, or neither 1 nor 2
   (`unsupported-version`);
3. a version-2 member appears under version 1 (`member-requires-version-2`);
4. a term — in `terms`, an exception or a replacement entry — or a replacement string
   is empty once normalized (`empty-term`);
5. a phrase is empty once normalized (`empty-phrase`);
6. two entries of one member name one term, compared normalized and folded
   (`duplicate-entry`);
7. a replacement entry both replaces and rejects, or does neither (`replacement-shape`);
8. it carries `exceptions` and is not a repository's own declaration
   (`exceptions-outside-repository`);
9. a member has a value of the wrong shape — a string where a list belongs, an
   exception action that is none of the four (`malformed`).

The names in parentheses are the error kinds the conformance suite expects.
Cases: `conformance/cases/declaration.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`, `conformance/cases/onevcs-v0.57.6-phrases.json`, `conformance/cases/unavailable.json`.

*Illustration only* — one version-2 declaration, shown in TOML and then YAML:

```toml
schema_version = 2
terms = ["quillmoss"]
phrases = ["quillmoss-bridge"]

[[replacements]]
term = "quillmoss"
with = "example-project"

[[replacements]]
term = "vantorel"
reject = true
```

```yaml
schema_version: 2
terms: [quillmoss]
phrases: [quillmoss-bridge]
replacements:
  - {term: quillmoss, with: example-project}
  - {term: vantorel, reject: true}
```

## 2. Layered declarations and precedence

**[LEVEL-ORDER]** A check is given an ordered list of **levels**, nearest first. Each
level is tagged as a **repository**'s own, a **directory** level or a **fallback**, and
carries one declaration. How an implementation finds its levels is its binding, not the
model. A check is also given the repository's own **rules** — each a term, a mode
(section 3) and whether it is case-sensitive, as the repository's identity and manifests
derive them — and may be given a **caller list**: an ordered list of replacement
entries. Identical rules (one term once normalized, and folded unless case-sensitive,
with one mode and one case rule) are kept once, the first.
Cases: `conformance/cases/precedence.json`.

**[LEVEL-OWN-RULES]** The repository's own rules are the derived rules and the terms of
every repository level's declaration. Each exception of a repository level narrows every
own rule carrying its term (compared normalized and folded):

- `drop` removes it;
- `whole-word` makes a substring rule whole-word and leaves any other as it is;
- `case-sensitive` makes it case-sensitive, spelled as the exception spells the term —
  except an owner-name-only rule, which keeps its own spelling;
- `owner-name-only` removes it, leaving the term found only through the repository's
  qualified `owner/name` rule, which a derivation carries and no exception reaches.

An exception naming no own rule refuses the declaration (`exception-names-no-term`).
Cases: `conformance/cases/precedence.json`.

**[LEVEL-NO-REMOVAL]** Every other level's terms, and every replacement entry — of any
level, or of the caller list — naming a term no rule carries, add a whole-word, not
case-sensitive rule after the own rules. No exception reaches them: no level removes a
rule that a farther level or the repository's own derivation carries.
Cases: `conformance/cases/declaration.json`, `conformance/cases/precedence.json`.

**[LEVEL-PRECEDENCE]** Each rule's **action** — reject, or replace with a string — is
resolved per term, compared normalized and folded, from the first of these that names
the term:

1. the caller list, a later entry winning over an earlier one;
2. the levels, nearest first: the nearest level naming the term decides whether it is
   rejected or replaced, and the replacement;
3. otherwise, **reject**.

Cases: `conformance/cases/precedence.json`, `conformance/cases/replacement.json`.

**[LEVEL-ONE-DISTANCE]** Levels that a binding finds at one place (in the reference
implementation, levels sharing a directory) are at **one distance**. Where two sources
at the deciding distance resolve one term differently, the term is rejected.
Cases: `conformance/cases/precedence.json`.

## 3. Matching

One matcher is compiled over the resolved rules and the public phrases of every level,
and every question below is asked of it.

**[MATCH-NORMALIZE]** Text and terms alike are put through Unicode NFKC, and every
default-ignorable code point (`Default_Ignorable_Code_Point`, such as a zero-width space
or joiner, a soft hyphen, a variation selector) is removed, before and after NFKC. A term
is therefore found in a full-width, ligature, superscript or decomposed spelling, and
through a character no reader sees.
Cases: `conformance/cases/declaration.json`, `conformance/cases/locators.json`, `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`, `conformance/cases/replacement.json`.

**[MATCH-CASE]** A rule that is not case-sensitive is compared in lower case on both
sides, the lower case of the whole normalized text (so a word-final capital sigma is a
final sigma). A case-sensitive rule is compared on the normalized text exactly.
Cases: `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`, `conformance/cases/precedence.json`, `conformance/cases/replacement.json`.

**[MATCH-WORD]** A **word character** is a Unicode letter or digit (`Alphabetic` or
`Numeric`), or `_`. Word characters are read in the normalized text a hit is found in.
Cases: `conformance/cases/matching.json`.

**[MATCH-SUBSTRING]** A `substring` rule accepts every occurrence of its term.
Cases: `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`.

**[MATCH-WHOLE-WORD]** A `whole-word` rule accepts an occurrence with no word character
immediately before it and none immediately after it.
Cases: `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`.

**[MATCH-OWNER-NAME]** An `owner-name-only` rule's term is a qualified `owner/name`, and
it accepts an occurrence where that name stands on its own: the character before it is
not a word character, `-` or `.`; and the character after it is none of those either,
except a `.` that begins `.git` not itself followed by a word character, `-` or `.`, or a
`.` not followed by a word character. So `hiddenco/docs.git` carries `hiddenco/docs`, and
`hiddenco/docs.site` and `hiddenco/docsite` do not.
Cases: `conformance/cases/locators.json`, `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`.

**[MATCH-PHRASE-STANDS]** A public phrase is normalized and folded as a term that is not
case-sensitive is, and found without case in the text a term hit was found in — on the
case-sensitive path too, with its spans located in that same normalized text. A phrase
occurrence counts only where it **stands on its own**: the character before it is not a
word character, not `-`, and not a `.` that itself follows a word character; the
character after it is not a word character, not `-`, and not a `.` followed by a word
character. Both are read in the text the hit was found in, so a letter there keeps the
phrase from standing even where folding turns it into a letter and a mark (`İ` into `i`
and U+0307): with the phrase `rig-zorv` and a case-sensitive term `Zorv`, `İrig-Zorv` is
still found, and with the phrase `zorv-rig`, so is `Zorv-rigİ`. An occurrence whose edge
falls inside one character's folded form does not stand.
Cases: `conformance/cases/onevcs-v0.57.6-matcher.json`.

**[MATCH-PHRASE-EXEMPT]** A term hit `[s, e)` is **exempt** only where a standing phrase
occurrence `[ps, pe)` has `ps <= s` and `e <= pe`, and a rule is found in a text where at
least one of its accepted hits is not exempt — under every mode alike. With the phrase
`box-ab` and a whole-word term `ab`, the term is exempt in `ran on box-ab`, `box-ab.`,
`(box-ab)`, `BOX-AB`, and `box-ab` written with a zero-width space inside it; and still
found in `box-ab-2`, `mybox-ab`, `box-ab.lan`, `ab`, `other-ab`, `box-ab-ab` (the second
`ab` lies outside the phrase) and `box-ab and ab`. A form joined to the phrase by a word
character, such as `box-ab_x`, is never exempted; under a whole-word term it carries no
hit at all.
Cases: `conformance/cases/locators.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`, `conformance/cases/replacement.json`.

**[MATCH-HITS]** A **hit** is one accepted, non-exempt occurrence of one rule's term:
the rule, and the span of the **original** text the occurrence came from — widened to
whole characters, and covering every character that normalized into it, a removed
default-ignorable inside it included and one at its edges not. Hits are reported each
rule at each place once, ordered by start, then the longer first. The **exempted count**
of a text is the number of accepted occurrences a phrase exempted, one for each rule at
each place.
Cases: `conformance/cases/matching.json`, `conformance/cases/replacement.json`.

## 4. Outcomes

**[OUT-DETECT]** **Detect** answers the hits in a text (MATCH-HITS), and which rules
they are of. A text with no hit is clean.
Cases: `conformance/cases/matching.json`, `conformance/cases/onevcs-v0.57.6-matcher.json`.

**[OUT-REJECT]** A hit of a rule whose action is reject is never rewritten: a text
carrying one is refused.
Cases: `conformance/cases/precedence.json`, `conformance/cases/replacement.json`.

**[OUT-REPLACE]** **Replace** is one pass over the text for all rules at once: among the
non-exempt hits whose resolved action is replace, the leftmost-longest non-overlapping
ones are selected (the leftmost first; of those starting together, the longest; ties by
rule order), and each is rewritten to its replacement at its span in the original text,
every other character kept. The result is then matched again by the same matcher, and
any hit is a refusal (`term-remains`): a rejected term left in place, or a term the
rewriting formed beside the text around it.
Cases: `conformance/cases/replacement.json`.

**[OUT-REPLACEMENT-CARRIES]** Before anything is replaced, every resolved replacement
string is matched by the same matcher; one carrying a non-exempt hit is an error
(`replacement-carries-term`), and nothing is rewritten.
Cases: `conformance/cases/replacement.json`.

**[OUT-UNAVAILABLE]** Where any level's declaration cannot be read, or is invalid, the
check is **unavailable**: nothing is reported clean and nothing is rewritten.
Cases: `conformance/cases/locators.json`, `conformance/cases/onevcs-v0.57.6-phrases.json`, `conformance/cases/precedence.json`, `conformance/cases/replacement.json`, `conformance/cases/unavailable.json`.

## 5. Locators

A diagnostic names the record it is about by **locators**: strings an implementation did
not write itself — a source name, an item id, a user-defined field name, a metadata key,
a comment id, a file path, a repository identity — each with a kind `source`, `item`,
`field`, `metadata-key`, `comment`, `path` or `identity`. Fixed words an implementation
writes itself (`content`, `repositories`, a level kind, `$ONEVCS_HOME` spelled as that
variable's name) are not locators.

**[LOC-SCREEN]** Every locator a diagnostic would print is matched with the same matcher
as the text. One carrying a non-exempt hit must never be printed, hashed, digested,
truncated or partly shown: it is reported as the **redacted locator**
`{redacted: true, kind, ordinal}`, where `ordinal` counts the redacted locators of one
answer or report from 1, in emission order, and its record counts as **unfixable**, with
the reason `identifier carries a private term`. A locator that passes is printed
verbatim.
Cases: `conformance/cases/locators.json`.

**[LOC-NOT-REWRITTEN]** Replacement never rewrites a locator: one carrying a term a
replacement is declared for is still redacted.
Cases: `conformance/cases/locators.json`.

**[LOC-UNAVAILABLE]** When the check is unavailable, every locator is redacted.
Cases: `conformance/cases/locators.json`.

## Versioning

This is Specification 1. A change that makes a valid declaration invalid, a found term
not found, or a clean text found is a new specification version; the model version a
declaration carries (`schema_version`) is versioned separately and only ever grows.
