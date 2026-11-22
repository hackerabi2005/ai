//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/LLM/`.

#![forbid(unsafe_code)]

use fancy_regex::{Captures, Regex};
use serde_json::json;
use std::sync::LazyLock;

const TEXT_SYSTEM_PROMPT_LEAD: &str = "You are a helpful assistant in a text conversation.";

const TEXT_SYSTEM_PROMPT_TAIL: &str = "## Text Rules
- Write clearly and directly. Match length to the request: concise for simple questions, fuller when the task genuinely needs it.
- Use markdown when it helps (lists, code blocks, tables, emphasis); don't over-format simple answers.
- This is a written channel: no spoken-style filler and no action/emote text like *laughs*.
- Use tools when they help fulfill the request. No preamble sentence is required before a tool call.
- For slow or external tools, just call the tool and use the result; you don't need to announce it.
- If unsure whether a tool is needed, just answer directly.";

const VOICE_SYSTEM_PROMPT_LEAD: &str = "You are in a spoken conversation. The user speaks and hears you.
The session prompt defines persona, facts, goals, and tool descriptions. These channel rules only control spoken output and tool-use behavior.";

const VOICE_SYSTEM_PROMPT_TAIL: &str = "## Voice Rules
- Keep replies brief by default: usually one spoken sentence, two if needed. Go longer only when asked.
- Speak naturally. No markdown, bullets, headings, visual formatting, or action/emote text like *laughs*.
- Treat transcripts as noisy. Correct likely mishearings only if asked or meaning depends on it.
- Speech is the default. Use tools when they help fulfill the request or fit the moment.
- Never mention tools or their function names in spoken output.
- For information tools, act immediately rather than merely offering. You may give one brief acknowledgement before the first call. After tool results, make further calls without speaking. Once you have enough results, give one final answer; do not narrate individual calls.
- For expression/background tools, speak first. If asked to show an expression, use a short pattern like \"Sure, here's my best <emotion>.\" Otherwise use a fitting empathetic sentence.
- After completed expression/background/physical-action tools, do not add a second spoken comment unless the result has user-facing information.
- Use motion, dance, emotion, and similar tools sparingly when they add empathy, celebration, playfulness, or a requested physical action.
- If unsure whether a tool is needed, just speak.";

static FENCED_CODE_RE: LazyLock<Option<Regex>> = LazyLock::new(|| {
    Regex::new(r"(?ms)^[ \t]{0,3}`{3,}[^\r\n]*\r?\n(?P<body>.*?)(?:^[ \t]{0,3}`{3,}[ \t]*$)").ok()
});
static INLINE_CODE_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(?P<ticks>`{1,})(?P<body>[^\n]*?)(?P=ticks)").ok());
static HEADING_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(?m)^[ \t]{0,3}#{1,6}(?:[ \t]+|$)").ok());
static BULLET_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"(?m)^[ \t]{0,3}[-*+][ \t]+").ok());
static EMPHASIS_RE: LazyLock<Option<Regex>> = LazyLock::new(|| {
    Regex::new(
        r"(?<![\p{L}\p{N}_*_])(?P<delimiter>\*{1,3}|_{1,2})(?![*_])(?P<body>\S(?:[^\n]*?\S)??)(?P=delimiter)(?![\p{L}\p{N}_*_])",
    )
    .ok()
});
static UNICODE_ALNUM_RE: LazyLock<Option<Regex>> =
    LazyLock::new(|| Regex::new(r"^[\p{L}\p{N}]$").ok());

fn is_py_space(ch: char) -> bool {
    ch.is_whitespace() || matches!(ch, '\x1c'..='\x1f')
}

/// Port of `build_text_system_prompt` (`s2s/speech-to-speech/src/speech_to_speech/LLM/text_prompt.py:30`).
pub fn build_text_system_prompt(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> Result<String, String> {
    let tools = tool_section.trim_matches(is_py_space);
    let optional_tools = if tools.is_empty() {
        String::new()
    } else {
        format!("\n\n{tools}")
    };
    let optional_language = match language_name.as_deref() {
        Some(lang) if !lang.is_empty() => {
            format!("\n\n{}", format_language_instruction(lang.to_string())?)
        }
        _ => String::new(),
    };
    Ok(format!(
        "{TEXT_SYSTEM_PROMPT_LEAD}\n\nSession Prompt:\n{}{optional_tools}{optional_language}\n\n{TEXT_SYSTEM_PROMPT_TAIL}\n",
        session_prompt.trim_matches(is_py_space)
    ))
}

/// Port of `remove_markdown` (`s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py:118`).
pub fn remove_markdown(text: String) -> Result<String, String> {
    let (mut has_backtick, mut has_hash, mut has_bullet, mut has_emphasis) =
        (false, false, false, false);
    for &b in text.as_bytes() {
        match b {
            b'`' => has_backtick = true,
            b'#' => has_hash = true,
            b'-' | b'+' => has_bullet = true,
            b'*' => {
                has_bullet = true;
                has_emphasis = true;
            }
            b'_' => has_emphasis = true,
            _ => {}
        }
    }
    if !(has_backtick || has_hash || has_bullet || has_emphasis) {
        return Ok(text);
    }

    let mut protected_code: Vec<String> = Vec::new();
    let mut cur = text;
    if has_backtick {
        if cur.contains("```")
            && let Some(re) = FENCED_CODE_RE.as_ref()
        {
            cur = re
                .replace_all(&cur, |caps: &Captures<'_>| {
                    let idx = protected_code.len();
                    let body = caps.name("body").map_or("", |m| m.as_str()).to_string();
                    protected_code.push(body);
                    format!("\x00markdown-code-{idx}\x00")
                })
                .into_owned();
        }
        if cur.contains('`')
            && let Some(re) = INLINE_CODE_RE.as_ref()
        {
            cur = re
                .replace_all(&cur, |caps: &Captures<'_>| {
                    let idx = protected_code.len();
                    let body = caps.name("body").map_or("", |m| m.as_str()).to_string();
                    protected_code.push(body);
                    format!("\x00markdown-code-{idx}\x00")
                })
                .into_owned();
        }
    }
    if has_hash
        && cur.contains('#')
        && let Some(re) = HEADING_RE.as_ref()
    {
        cur = re.replace_all(&cur, "").into_owned();
    }
    if has_bullet
        && cur.bytes().any(|b| matches!(b, b'-' | b'*' | b'+'))
        && let Some(re) = BULLET_RE.as_ref()
    {
        cur = re.replace_all(&cur, "").into_owned();
    }
    if has_emphasis
        && cur.bytes().any(|b| matches!(b, b'*' | b'_'))
        && let Some(re) = EMPHASIS_RE.as_ref()
    {
        cur = re
            .replace_all(&cur, |caps: &Captures<'_>| {
                caps.name("body").map_or("", |m| m.as_str()).to_string()
            })
            .into_owned();
    }
    for (idx, body) in protected_code.iter().enumerate() {
        let tok = format!("\x00markdown-code-{idx}\x00");
        cur = cur.replace(&tok, body);
    }
    Ok(cur)
}

fn is_py_alnum(ch: char) -> bool {
    if ch.is_ascii() {
        return ch.is_ascii_alphanumeric();
    }
    if !ch.is_alphanumeric() {
        return false;
    }
    let mut buf = [0u8; 4];
    let s = ch.encode_utf8(&mut buf);
    UNICODE_ALNUM_RE
        .as_ref()
        .is_some_and(|re| re.is_match(s).unwrap_or(false))
}

fn is_speechable_char(ch: char) -> bool {
    is_py_alnum(ch)
        || ch == '_'
        || is_py_space(ch)
        || matches!(
            ch,
            '.' | ','
                | '!'
                | '?'
                | ';'
                | ':'
                | '\''
                | '"'
                | '-'
                | '('
                | ')'
                | '/'
                | '\\'
                | '@'
                | '#'
                | '%'
                | '&'
                | '*'
                | '+'
                | '='
                | '$'
                | '€'
                | '£'
                | '¥'
                | '₹'
                | '₽'
                | '¢'
                | '['
                | ']'
                | '{'
                | '}'
                | '<'
                | '>'
                | '~'
                | '`'
                | '^'
                | '|'
                | '…'
                | '—'
                | '–'
                | '，'
                | '。'
                | '！'
                | '？'
                | '；'
                | '：'
                | '、'
                | '\n'
                | '\r'
                | '\t'
        )
}

/// Port of `remove_unspeechable` (`s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py:131`).
pub fn remove_unspeechable(text: String) -> Result<String, String> {
    let mut out = String::with_capacity(text.len());
    for raw_ch in text.chars() {
        let ch = match raw_ch {
            '\u{2018}' | '\u{2019}' => '\'',
            '\u{201c}' | '\u{201d}' => '"',
            other => other,
        };
        if is_speechable_char(ch) {
            out.push(ch);
        }
    }
    Ok(out)
}

/// Port of `format_language_instruction` (`s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py:143`).
pub fn format_language_instruction(lang_name: String) -> Result<String, String> {
    Ok(format!("Please reply to my message in {lang_name}."))
}

fn whisper_language_name(code: &str) -> Option<&'static str> {
    Some(match code {
        "en" => "english",
        "fr" => "french",
        "es" => "spanish",
        "zh" => "chinese",
        "ja" => "japanese",
        "ko" => "korean",
        "hi" => "hindi",
        "de" => "german",
        "pt" => "portuguese",
        "pl" => "polish",
        "it" => "italian",
        "nl" => "dutch",
        "ru" => "russian",
        "uk" => "ukrainian",
        "cs" => "czech",
        "sk" => "slovak",
        "hu" => "hungarian",
        "ro" => "romanian",
        "bg" => "bulgarian",
        "hr" => "croatian",
        "sl" => "slovenian",
        "sr" => "serbian",
        "da" => "danish",
        "no" => "norwegian",
        "sv" => "swedish",
        "fi" => "finnish",
        "et" => "estonian",
        "lv" => "latvian",
        "lt" => "lithuanian",
        "tr" => "turkish",
        "ca" => "catalan",
        "ar" => "arabic",
        "id" => "indonesian",
        "vi" => "vietnamese",
        "he" => "hebrew",
        "el" => "greek",
        "ms" => "malay",
        "ta" => "tamil",
        "th" => "thai",
        "ur" => "urdu",
        "la" => "latin",
        "mi" => "maori",
        "ml" => "malayalam",
        "cy" => "welsh",
        "te" => "telugu",
        "fa" => "persian",
        "bn" => "bengali",
        "az" => "azerbaijani",
        "kn" => "kannada",
        "mk" => "macedonian",
        "br" => "breton",
        "eu" => "basque",
        "is" => "icelandic",
        "hy" => "armenian",
        "ne" => "nepali",
        "mn" => "mongolian",
        "bs" => "bosnian",
        "kk" => "kazakh",
        "sq" => "albanian",
        "sw" => "swahili",
        "fil" => "filipino",
        "gl" => "galician",
        "mr" => "marathi",
        "pa" => "punjabi",
        "si" => "sinhala",
        "km" => "khmer",
        "sn" => "shona",
        "yo" => "yoruba",
        "so" => "somali",
        "af" => "afrikaans",
        "oc" => "occitan",
        "ka" => "georgian",
        "be" => "belarusian",
        "tg" => "tajik",
        "sd" => "sindhi",
        "gu" => "gujarati",
        "am" => "amharic",
        "yi" => "yiddish",
        "lo" => "lao",
        "uz" => "uzbek",
        "fo" => "faroese",
        "ht" => "haitian creole",
        "ps" => "pashto",
        "tk" => "turkmen",
        "nn" => "nynorsk",
        "mt" => "maltese",
        "sa" => "sanskrit",
        "lb" => "luxembourgish",
        "my" => "myanmar",
        "bo" => "tibetan",
        "tl" => "tagalog",
        "mg" => "malagasy",
        "as" => "assamese",
        "tt" => "tatar",
        "haw" => "hawaiian",
        "ln" => "lingala",
        "ha" => "hausa",
        "ba" => "bashkir",
        "jw" => "javanese",
        "su" => "sundanese",
        "yue" => "cantonese",
        _ => return None,
    })
}

fn resolve_code_and_name(language_code: Option<String>) -> (Option<String>, Option<String>) {
    let Some(code) = language_code else {
        return (None, None);
    };
    if code.is_empty() {
        return (Some(code), None);
    }
    let clean = code
        .strip_suffix("-auto")
        .map_or_else(|| code.clone(), str::to_string);
    let name = whisper_language_name(&clean).map(str::to_string);
    (Some(clean), name)
}

/// Port of `language_name_for_prompt` (`s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py:148`).
pub fn language_name_for_prompt(
    language_code: Option<String>,
    enable: bool,
) -> Result<Option<String>, String> {
    if !enable {
        return Ok(None);
    }
    let (_, name) = resolve_code_and_name(language_code);
    Ok(name)
}

/// Port of `resolve_auto_language` (`s2s/speech-to-speech/src/speech_to_speech/LLM/utils.py:156`).
pub fn resolve_auto_language(language_code: Option<String>) -> Result<serde_json::Value, String> {
    let (clean, name) = resolve_code_and_name(language_code);
    Ok(json!({ "$tuple": [clean, name] }))
}

/// Port of `build_voice_system_prompt` (`s2s/speech-to-speech/src/speech_to_speech/LLM/voice_prompt.py:35`).
pub fn build_voice_system_prompt(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> Result<String, String> {
    let tools = tool_section.trim_matches(is_py_space);
    let optional_tools = if tools.is_empty() {
        String::new()
    } else {
        format!("\n\n{tools}")
    };
    let optional_language = match language_name.as_deref() {
        Some(lang) if !lang.is_empty() => {
            format!("\n\n{}", format_language_instruction(lang.to_string())?)
        }
        _ => String::new(),
    };
    Ok(format!(
        "{VOICE_SYSTEM_PROMPT_LEAD}\n\nSession Prompt:\n{}{optional_tools}{optional_language}\n\n{VOICE_SYSTEM_PROMPT_TAIL}\n",
        session_prompt.trim_matches(is_py_space)
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_remove_markdown_preserves_code_and_strips_emphasis() {
        assert_eq!(
            remove_markdown("# Title\n- *Bold* and `code *star*`".to_string()),
            Ok("Title\nBold and code *star*".to_string())
        );
    }

    #[test]
    fn test_remove_unspeechable_normalizes_quotes_and_drops_emoji() {
        assert_eq!(
            remove_unspeechable("Hello \u{2018}world\u{2019} 😀!".to_string()),
            Ok("Hello 'world' !".to_string())
        );
    }

    #[test]
    fn test_resolve_auto_language_and_prompt() {
        assert_eq!(
            language_name_for_prompt(Some("fr-auto".to_string()), true),
            Ok(Some("french".to_string()))
        );
        assert_eq!(
            language_name_for_prompt(Some("fr-auto".to_string()), false),
            Ok(None)
        );
        assert_eq!(
            resolve_auto_language(Some("en-auto".to_string())),
            Ok(json!({ "$tuple": ["en", "english"] }))
        );
    }
}
