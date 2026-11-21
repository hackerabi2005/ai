//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/TTS/`.

#![forbid(unsafe_code)]

use fancy_regex::{Captures, Regex};
use std::sync::LazyLock;
use unicode_normalization::UnicodeNormalization;

const ZWNJ: char = '\u{200c}';
const PERSIAN_LETTERS: &str = "آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئ";
const KEPT_PUNCT: &str = ".،؛؟!:";
const MAX_NUMBER_DIGITS: usize = 12;

const ONES: [&str; 10] = [
    "", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه",
];
const TEENS: [&str; 10] = [
    "ده",
    "یازده",
    "دوازده",
    "سیزده",
    "چهارده",
    "پانزده",
    "شانزده",
    "هفده",
    "هجده",
    "نوزده",
];
const TENS: [&str; 10] = [
    "",
    "",
    "بیست",
    "سی",
    "چهل",
    "پنجاه",
    "شصت",
    "هفتاد",
    "هشتاد",
    "نود",
];
const HUNDREDS: [&str; 10] = [
    "",
    "صد",
    "دویست",
    "سیصد",
    "چهارصد",
    "پانصد",
    "ششصد",
    "هفتصد",
    "هشتصد",
    "نهصد",
];
const SCALES: [(i64, &str); 4] = [
    (1_000_000_000_000, "تریلیون"),
    (1_000_000_000, "میلیارد"),
    (1_000_000, "میلیون"),
    (1_000, "هزار"),
];

static ND_CHAR_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"^\p{Nd}$").ok());
static THOUSANDS_COMMA_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(?<=\p{Nd}),(?=\p{Nd}\p{Nd}\p{Nd}(?![\p{L}\p{N}_]))").ok());
static NUMBER_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"((?<![\p{L}\p{N}_])[−-])?(\p{Nd}+)(?:[.](\p{Nd}+))?").ok());
static ZWNJ_SPACE_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"\s*\u{200c}\s*").ok());
static ZWNJ_EDGE_RE: LazyLock<Option<Regex>> = LazyLock::new(|| {
    Regex::new(
        r"(?<![آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئ])\u{200c}|\u{200c}(?![آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهیئ])",
    )
    .ok()
});
static SPACE_BEFORE_PUNCT_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"\s+([.،؛؟!:])").ok());
static DUP_PUNCT_RE: LazyLock<Option<Regex>> = LazyLock::new(|| Regex::new(r"([.،؛؟!:])\1+").ok());

fn is_nd(ch: char) -> bool {
    if ch.is_ascii() {
        return ch.is_ascii_digit();
    }
    let mut buf = [0u8; 4];
    let s = ch.encode_utf8(&mut buf);
    ND_CHAR_RE
        .as_ref()
        .is_some_and(|re| re.is_match(s).unwrap_or(false))
}

fn nd_value(ch: char) -> u32 {
    if ch.is_ascii_digit() {
        return ch as u32 - b'0' as u32;
    }
    let code = ch as u32;
    let mut steps = 0u32;
    while let Some(prev) = code.checked_sub(steps + 1).and_then(char::from_u32) {
        if is_nd(prev) {
            steps += 1;
        } else {
            break;
        }
    }
    steps % 10
}

fn parse_nd_str(s: &str) -> i64 {
    let mut val = 0i64;
    for ch in s.chars() {
        val = val
            .saturating_mul(10)
            .saturating_add(i64::from(nd_value(ch)));
    }
    val
}

fn under_thousand(mut n: i64) -> Result<String, String> {
    let mut parts = Vec::new();
    if n >= 100 {
        let idx = usize::try_from(n / 100).unwrap_or(usize::MAX);
        let Some(&word) = HUNDREDS.get(idx) else {
            return Err("IndexError: list index out of range".to_string());
        };
        parts.push(word);
        n %= 100;
    }
    if n >= 20 {
        let idx = usize::try_from(n / 10).unwrap_or(0);
        if let Some(&word) = TENS.get(idx) {
            parts.push(word);
        }
        n %= 10;
    }
    if (10..20).contains(&n) {
        let idx = usize::try_from(n - 10).unwrap_or(0);
        if let Some(&word) = TEENS.get(idx) {
            parts.push(word);
        }
        n = 0;
    }
    if n > 0 {
        let idx = usize::try_from(n).unwrap_or(0);
        if let Some(&word) = ONES.get(idx) {
            parts.push(word);
        }
    }
    Ok(parts.join(" و "))
}

/// Port of `number_to_words` (`s2s/speech-to-speech/src/speech_to_speech/TTS/persian_normalization.py:151`).
pub fn number_to_words(mut n: i64) -> Result<String, String> {
    if n == 0 {
        return Ok("صفر".to_string());
    }
    let mut parts = Vec::new();
    for (value, name) in SCALES {
        if n >= value {
            let count = n / value;
            n %= value;
            let item = if count == 1 && value == 1_000 {
                name.to_string()
            } else {
                format!("{} {name}", under_thousand(count)?)
            };
            parts.push(item.trim().to_string());
        }
    }
    if n > 0 {
        parts.push(under_thousand(n)?);
    }
    Ok(parts.join(" و "))
}

fn digits_one_by_one(digits: &str) -> String {
    digits
        .chars()
        .map(|d| {
            if d == '0' {
                "صفر"
            } else {
                let v = nd_value(d) as usize;
                ONES.get(v).copied().unwrap_or("")
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

/// Port of `numbers_to_words` (`s2s/speech-to-speech/src/speech_to_speech/TTS/persian_normalization.py:197`).
pub fn numbers_to_words(text: String) -> Result<String, String> {
    let without_commas = if let Some(re) = THOUSANDS_COMMA_RE.as_ref() {
        re.replace_all(&text, "").into_owned()
    } else {
        text
    };
    let Some(re) = NUMBER_RE.as_ref() else {
        return Ok(without_commas);
    };
    let out = re
        .replace_all(&without_commas, |caps: &Captures<'_>| {
            let sign = caps.get(1).map(|m| m.as_str());
            let whole = caps.get(2).map_or("", |m| m.as_str());
            let frac = caps.get(3).map(|m| m.as_str());
            let prefix = if sign.is_some() { "منفی " } else { "" };
            let whole_len = whole.chars().count();
            if whole_len > MAX_NUMBER_DIGITS || (whole.starts_with('0') && whole_len > 1) {
                let frac_part = match frac {
                    Some(f) => format!(" {}", digits_one_by_one(f)),
                    None => String::new(),
                };
                return format!(" {prefix}{}{frac_part} ", digits_one_by_one(whole));
            }
            let stripped = whole.trim_start_matches('0');
            let whole_norm = if stripped.is_empty() { "0" } else { stripped };
            let mut words = number_to_words(parse_nd_str(whole_norm)).unwrap_or_default();
            if let Some(f_raw) = frac {
                let f = f_raw.trim_end_matches('0');
                if f.is_empty() {
                    return format!(" {prefix}{words} ");
                }
                let f_len = f.chars().count();
                let unit = match f_len {
                    1 => Some("دهم"),
                    2 => Some("صدم"),
                    3 => Some("هزارم"),
                    _ => None,
                };
                if let Some(u) = unit {
                    let fw = number_to_words(parse_nd_str(f)).unwrap_or_default();
                    words = format!("{words} ممیز {fw} {u}");
                } else {
                    words = format!("{words} ممیز {}", digits_one_by_one(f));
                }
            }
            format!(" {prefix}{words} ")
        })
        .into_owned();
    Ok(out)
}

fn is_invisible(ch: char) -> bool {
    matches!(
        ch,
        '\u{200b}'
            | '\u{200d}'
            | '\u{200e}'
            | '\u{200f}'
            | '\u{202a}'..='\u{202e}'
            | '\u{2066}'..='\u{2069}'
            | '\u{feff}'
            | '\u{00ad}'
    )
}

fn is_diacritic(ch: char) -> bool {
    matches!(
        ch,
        '\u{064b}'..='\u{0655}'
            | '\u{0670}'
            | '\u{06d6}'..='\u{06ed}'
            | '\u{0656}'..='\u{065f}'
    )
}

fn is_allowed(ch: char) -> bool {
    ch == ' ' || ch == ZWNJ || PERSIAN_LETTERS.contains(ch) || KEPT_PUNCT.contains(ch)
}

/// Port of `normalize` (`s2s/speech-to-speech/src/speech_to_speech/TTS/persian_normalization.py:208`).
pub fn normalize(text: String, spell_numbers: bool) -> Result<String, String> {
    let mut s = String::with_capacity(text.len());
    for ch in text.nfc() {
        if is_invisible(ch) || is_diacritic(ch) {
            continue;
        }
        match ch {
            'ي' | 'ى' | 'ۍ' | 'ې' => s.push('ی'),
            'ك' | 'ڪ' => s.push('ک'),
            'ة' | 'ۀ' | 'ۂ' | 'ۃ' => s.push('ه'),
            'أ' | 'إ' | 'ٱ' | 'ٲ' | 'ٳ' => s.push('ا'),
            'ؤ' => s.push('و'),
            'ء' | 'ـ' | '٬' => {}
            '٫' => s.push('.'),
            '\u{06f0}'..='\u{06f9}' => {
                if let Some(d) = char::from_u32(u32::from(b'0') + (ch as u32 - 0x06f0)) {
                    s.push(d);
                }
            }
            '\u{0660}'..='\u{0669}' => {
                if let Some(d) = char::from_u32(u32::from(b'0') + (ch as u32 - 0x0660)) {
                    s.push(d);
                }
            }
            '٪' | '%' => s.push_str(" درصد "),
            other => s.push(other),
        }
    }

    if spell_numbers {
        s = numbers_to_words(s)?;
    }

    let mut mapped = String::with_capacity(s.len());
    for ch in s.chars() {
        let m = match ch {
            ',' | '،' => Some('،'),
            '?' | '؟' => Some('؟'),
            ';' | '؛' => Some('؛'),
            '٬' => None,
            '٫' | '…' => Some('.'),
            '»' | '«' | '“' | '”' | '‘' | '’' | '"' | '\'' | '`' | '(' | ')' | '[' | ']' | '{'
            | '}' | '–' | '—' | '−' | '-' | '‐' | '/' | '\\' | '*' | '_' | '|' | '×' | '='
            | '+' => Some(' '),
            other if is_allowed(other) => Some(other),
            _ => Some(' '),
        };
        if let Some(c) = m {
            mapped.push(c);
        }
    }

    while mapped.contains("\u{200c}\u{200c}") {
        mapped = mapped.replace("\u{200c}\u{200c}", "\u{200c}");
    }
    if let Some(re) = ZWNJ_SPACE_RE.as_ref() {
        mapped = re
            .replace_all(&mapped, |caps: &Captures<'_>| {
                let m = caps.get(0).map_or("", |m| m.as_str());
                if m.contains(' ') { " " } else { "\u{200c}" }
            })
            .into_owned();
    }
    if let Some(re) = ZWNJ_EDGE_RE.as_ref() {
        mapped = re.replace_all(&mapped, "").into_owned();
    }
    if let Some(re) = SPACE_BEFORE_PUNCT_RE.as_ref() {
        mapped = re
            .replace_all(&mapped, |caps: &Captures<'_>| {
                caps.get(1).map_or("", |m| m.as_str()).to_string()
            })
            .into_owned();
    }
    if let Some(re) = DUP_PUNCT_RE.as_ref() {
        mapped = re
            .replace_all(&mapped, |caps: &Captures<'_>| {
                caps.get(1).map_or("", |m| m.as_str()).to_string()
            })
            .into_owned();
    }

    let mut collapsed = String::with_capacity(mapped.len());
    let mut in_space = false;
    for ch in mapped.chars() {
        if ch.is_whitespace() || matches!(ch, '\x1c'..='\x1f') {
            if !collapsed.is_empty() {
                in_space = true;
            }
        } else {
            if in_space {
                collapsed.push(' ');
                in_space = false;
            }
            collapsed.push(ch);
        }
    }

    let trimmed = collapsed.trim_start_matches(|c: char| c == ' ' || KEPT_PUNCT.contains(c));
    Ok(trimmed.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_number_to_words_persian() {
        assert_eq!(number_to_words(0), Ok("صفر".to_string()));
        assert_eq!(number_to_words(1402), Ok("هزار و چهارصد و دو".to_string()));
        assert_eq!(number_to_words(1_000_000), Ok("یک میلیون".to_string()));
        assert!(number_to_words(i64::MAX).is_err());
    }

    #[test]
    fn test_normalize_farsi_sentence() {
        assert_eq!(
            normalize(
                "سلام! سال ۱۴۰۲ است، قیمت ۱٬۲۵۰٬۰۰۰ تومان (۵۰٪ تخفیف)؟".to_string(),
                true
            ),
            Ok(
                "سلام! سال هزار و چهارصد و دو است، قیمت یک میلیون و دویست و پنجاه هزار تومان پنجاه درصد تخفیف؟"
                    .to_string()
            )
        );
    }
}
