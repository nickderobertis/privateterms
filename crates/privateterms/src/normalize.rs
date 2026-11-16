//! Normalization (Specification 1, *Matching*): NFKC with every default-ignorable code
//! point removed, then lower case for a rule that is not case-sensitive — and, so a hit
//! can be reported and rewritten where it sits, a map from the normalized text back to
//! the original.

use std::borrow::Cow;
use std::collections::HashMap;
use std::sync::OnceLock;

use icu_normalizer::{ComposingNormalizerBorrowed, DecomposingNormalizerBorrowed};
use icu_properties::props::{
    CanonicalCombiningClass, ChangesWhenLowercased, DefaultIgnorableCodePoint,
};
use icu_properties::{CodePointMapData, CodePointSetData};

fn ignorable(c: char) -> bool {
    CodePointSetData::new::<DefaultIgnorableCodePoint>().contains(c)
}

/// `text` in NFKC with every default-ignorable code point removed.
pub(crate) fn normalize(text: &str) -> Cow<'_, str> {
    // ASCII is already in NFKC and carries nothing ignorable.
    if text.is_ascii() {
        return Cow::Borrowed(text);
    }
    if !text.chars().any(ignorable) {
        let normalized = ComposingNormalizerBorrowed::new_nfkc().normalize(text);
        if !normalized.chars().any(ignorable) {
            return normalized;
        }
    }
    let stripped: String = text.chars().filter(|c| !ignorable(*c)).collect();
    Cow::Owned(nfkc_stripped(&stripped))
}

/// NFKC of text that carries no default-ignorable, with any NFKC itself produces removed.
fn nfkc_stripped(stripped: &str) -> String {
    ComposingNormalizerBorrowed::new_nfkc()
        .normalize(stripped)
        .chars()
        .filter(|c| !ignorable(*c))
        .collect()
}

/// ASCII may be folded by the candidate automaton. Every other character must be
/// inert under normalization and unchanged by lowercase; otherwise use the full scan.
/// Inert characters cannot compose with their ASCII neighbors either.
pub(crate) fn candidate_text_is_stable(text: &str) -> bool {
    if text.is_ascii() {
        return true;
    }
    static STABLE: OnceLock<Box<[bool]>> = OnceLock::new();
    let stable = STABLE.get_or_init(|| {
        #[allow(deprecated)]
        // ICU's derived inertness property is exactly the normalization guarantee needed here.
        let inert = CodePointSetData::new::<icu_properties::props::NfkcInert>();
        (0..=0x10ffff)
            .map(|cp| {
                char::from_u32(cp).is_some_and(|c| {
                    inert.contains(c)
                        && !ignorable(c)
                        && !CodePointSetData::new::<ChangesWhenLowercased>().contains(c)
                })
            })
            .collect()
    });
    text.chars().all(|c| c.is_ascii() || stable[c as usize])
}

/// Already-normalized text in lower case, for a rule that ignores case.
pub(crate) fn fold(text: &str) -> Cow<'_, str> {
    if text.is_ascii() {
        if text.bytes().any(|b| b.is_ascii_uppercase()) {
            Cow::Owned(text.to_ascii_lowercase())
        } else {
            Cow::Borrowed(text)
        }
    } else {
        Cow::Owned(text.to_lowercase())
    }
}

/// The key two spellings of one term share once normalized and folded.
pub(crate) fn term_key(term: &str) -> String {
    fold(&normalize(term)).into_owned()
}

/// One segment of the original text: the bytes `original` normalize, on their own, to
/// the bytes `normalized` of the normalized text.
#[derive(Debug, Clone, Copy)]
struct Segment {
    normalized: (usize, usize),
    original: (usize, usize),
}

/// A text, its normalization, and the map between them.
pub(crate) struct Mapped<'a> {
    pub(crate) normalized: Cow<'a, str>,
    /// `None` when the normalized text is the original byte for byte.
    segments: Option<Vec<Segment>>,
}

impl<'a> Mapped<'a> {
    pub(crate) fn new(text: &'a str) -> Mapped<'a> {
        if text.is_ascii() {
            return Mapped {
                normalized: Cow::Borrowed(text),
                segments: None,
            };
        }
        let whole = normalize(text).into_owned();
        let kept: Vec<(usize, char)> = text
            .char_indices()
            .filter(|(_, c)| !ignorable(*c))
            .collect();
        let segments = segment(&kept).filter(|(joined, _)| *joined == whole);
        let segments = match segments {
            Some((_, segments)) => segments,
            // A text whose pieces do not normalize to its whole is mapped as one piece:
            // a hit anywhere in it is reported over all of it.
            None => vec![Segment {
                normalized: (0, whole.len()),
                original: match (kept.first(), kept.last()) {
                    (Some(first), Some(last)) => (first.0, last.0 + last.1.len_utf8()),
                    _ => (0, 0),
                },
            }],
        };
        Mapped {
            normalized: Cow::Owned(whole),
            segments: Some(segments),
        }
    }

    /// The span of the original text a span of the normalized text came from.
    pub(crate) fn original(&self, (start, end): (usize, usize)) -> (usize, usize) {
        let Some(segments) = &self.segments else {
            return (start, end);
        };
        let first = segments.partition_point(|s| s.normalized.1 <= start);
        let last = segments.partition_point(|s| s.normalized.0 < end);
        match (
            segments.get(first),
            last.checked_sub(1).and_then(|l| segments.get(l)),
        ) {
            (Some(a), Some(b)) => (a.original.0, b.original.1.max(a.original.0)),
            _ => (0, 0),
        }
    }
}

/// Cut `kept` (the original's characters with their byte offsets, default-ignorables
/// removed) into pieces that normalize independently, and the normalized text they join
/// to.
fn segment(kept: &[(usize, char)]) -> Option<(String, Vec<Segment>)> {
    let ccc = CodePointMapData::<CanonicalCombiningClass>::new();
    let starter = |c: char| ccc.get(c) == CanonicalCombiningClass::NotReordered;
    let text_of = |range: &[(usize, char)]| range.iter().map(|(_, c)| *c).collect::<String>();
    let mut joined = String::new();
    let mut segments = Vec::new();
    let mut start = 0;
    let mut index = 1;
    while index <= kept.len() {
        let cut = index == kept.len() || {
            let c = kept[index].1;
            starter(c) && {
                // The group the next segment would begin with: this starter and the
                // non-starters after it. A cut is sound where normalizing the current
                // piece and that group apart gives what normalizing them together does.
                let mut group_end = index + 1;
                while group_end < kept.len() && !starter(kept[group_end].1) {
                    group_end += 1;
                }
                let apart = nfkc_stripped(&text_of(&kept[start..index]))
                    + &nfkc_stripped(&text_of(&kept[index..group_end]));
                apart == nfkc_stripped(&text_of(&kept[start..group_end]))
            }
        };
        if cut {
            let piece = nfkc_stripped(&text_of(&kept[start..index]));
            let from = joined.len();
            joined.push_str(&piece);
            let last = kept[index - 1];
            segments.push(Segment {
                normalized: (from, joined.len()),
                original: (kept[start].0, last.0 + last.1.len_utf8()),
            });
            start = index;
        }
        index += 1;
    }
    Some((joined, segments))
}

/// A span of `fold(normalized)` as the span of `normalized` it was folded from, widened
/// to whole characters where an edge falls inside one character's folded form.
pub(crate) fn unfold(normalized: &str, (fs, fe): (usize, usize)) -> (usize, usize) {
    if normalized.is_ascii() {
        return (fs, fe);
    }
    let mut start = None;
    let mut at = 0;
    for (from, c) in normalized.char_indices() {
        let width = c.to_lowercase().map(char::len_utf8).sum::<usize>();
        let next = at + width;
        if start.is_none() && fs < next {
            start = Some(from);
        }
        if fe <= next {
            return (start.unwrap_or(from), from + c.len_utf8());
        }
        at = next;
    }
    (start.unwrap_or(normalized.len()), normalized.len())
}

/// A span of `fold(normalized)` as the span of `normalized`, or `None` where either edge
/// falls inside one character's folded form (the phrase rule: such an occurrence does
/// not stand at all).
pub(crate) fn in_normalized(normalized: &str, (ps, pe): (usize, usize)) -> Option<(usize, usize)> {
    let mut start = None;
    let mut at = 0;
    for (from, c) in normalized.char_indices() {
        if at == ps {
            start = Some(from);
        }
        at += c.to_lowercase().map(char::len_utf8).sum::<usize>();
        if at == pe {
            return start.map(|start| (start, from + c.len_utf8()));
        }
        if at > pe {
            return None;
        }
    }
    None
}

/// Necessary decomposed character sets, tested before allocating normalized text.
/// Canonical decomposition makes composition across input characters irrelevant.
pub(crate) struct Contributors {
    table: Box<[u64]>,
    required: Vec<u64>,
}

/// For each character, every non-ignorable code point other than itself whose NFKD,
/// lowercased one character at a time, contains it: the code points a term's character
/// can arrive in. Built once per process.
fn sources() -> &'static HashMap<char, Vec<usize>> {
    static SOURCES: OnceLock<HashMap<char, Vec<usize>>> = OnceLock::new();
    SOURCES.get_or_init(|| {
        let decomposition = DecomposingNormalizerBorrowed::new_nfkd();
        let mut sources: HashMap<char, Vec<usize>> = HashMap::new();
        for c in contributing().filter(|c| !ignorable(*c)) {
            for d in decomposition.normalize_iter(std::iter::once(c)) {
                for lower in d.to_lowercase() {
                    if lower != c {
                        sources.entry(lower).or_default().push(c as usize);
                    }
                    // String lowercasing also produces final sigma contextually.
                    if lower == 'σ' {
                        sources.entry('ς').or_default().push(c as usize);
                    }
                }
            }
        }
        sources
    })
}

/// Ascending, every code point that can be a source: one NFKD or lowercasing changes,
/// and σ, which is the source of ς. Any other code point decomposes and lowercases to
/// itself alone, so walking only these, about one in forty, builds the same map.
fn contributing() -> impl Iterator<Item = char> {
    #[allow(deprecated)]
    // ICU's derived inertness property is exactly "NFKD maps it to itself", the guarantee
    // skipping a code point needs; no UCD property states it.
    let inert = CodePointSetData::new::<icu_properties::props::NfkdInert>();
    let lowered = CodePointSetData::new::<ChangesWhenLowercased>();
    let mut points: Vec<u32> = inert
        .iter_ranges_complemented()
        .chain(lowered.iter_ranges())
        .flatten()
        .chain(std::iter::once('σ' as u32))
        .collect();
    points.sort_unstable();
    points.dedup();
    points.into_iter().filter_map(char::from_u32)
}

impl Contributors {
    pub(crate) fn new(terms: impl Iterator<Item = String>) -> Self {
        let decomposition = DecomposingNormalizerBorrowed::new_nfkd();
        let sources = sources();
        let mut table = vec![0u64; 0x110000].into_boxed_slice();
        // At most 64 distinct alphabetic components are tracked. Dropping further
        // requirements only admits extra candidates; it cannot hide a hit. Terms
        // without tracked components have a zero mask and always take the full path.
        let mut bits = HashMap::new();
        let mut required = Vec::new();
        for term in terms {
            let mut mask = 0;
            for c in decomposition
                .normalize_iter(term.chars())
                .filter(|c| c.is_alphabetic())
            {
                let next = bits.len();
                if next >= 64 && !bits.contains_key(&c) {
                    continue;
                }
                let bit = *bits.entry(c).or_insert(1u64 << next.min(63));
                mask |= bit;
            }
            required.push(mask);
        }
        for (c, bit) in bits {
            table[c as usize] |= bit;
            if let Some(contributors) = sources.get(&c) {
                for &cp in contributors {
                    table[cp] |= bit;
                }
            }
        }
        required.sort_unstable();
        required.dedup();
        Self { table, required }
    }

    pub(crate) fn possible(&self, text: &str) -> bool {
        let seen = text
            .chars()
            .fold(0, |seen, c| seen | self.table[c as usize]);
        self.required.iter().any(|mask| seen & mask == *mask)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The source map built from every code point, as it was before `contributing`
    /// narrowed the walk.
    fn sources_from_every_code_point() -> HashMap<char, Vec<usize>> {
        let decomposition = DecomposingNormalizerBorrowed::new_nfkd();
        let mut sources: HashMap<char, Vec<usize>> = HashMap::new();
        for c in (0..=0x10ffff)
            .filter_map(char::from_u32)
            .filter(|c| !ignorable(*c))
        {
            for d in decomposition.normalize_iter(std::iter::once(c)) {
                for lower in d.to_lowercase() {
                    if lower != c {
                        sources.entry(lower).or_default().push(c as usize);
                    }
                    if lower == 'σ' {
                        sources.entry('ς').or_default().push(c as usize);
                    }
                }
            }
        }
        sources
    }

    // A structural assertion rather than a public-API journey: whether a code point the
    // narrowed walk skips could have reached a term is a question about all 1,114,112 of
    // them, which no affordable set of matched texts asks. `tests/matcher_equivalence.rs`
    // holds the matcher's outcomes themselves to the base commit's.
    #[test]
    fn the_narrowed_walk_builds_the_map_every_code_point_builds() {
        let narrowed = sources();
        assert_eq!(narrowed, &sources_from_every_code_point());
        assert!(contributing().count() * 20 < 0x110000);
    }
}
