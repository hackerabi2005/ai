//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/STT/`.

#![forbid(unsafe_code)]

use serde_json::Value;

const TRANSCRIPTION_INSTRUCTION: &str = "Transcribe this audio with punctuation and capitalization. Include all spoken words and verbal fillers. Write numbers in their standard written form. Use <ev:*> and <sty:*> special tokens to recognize all non-speech verbatims and speaking style.";

const ANNOTATION_TOKENS: &[&str] = &[
    "<ev:breath>",
    "<ev:crying>",
    "<ev:effort_strain>",
    "<ev:gesture_noise>",
    "<ev:laughter>",
    "<ev:mouth_noise>",
    "<ev:music_vocal>",
    "<ev:pause_timing>",
    "<ev:shout_exclaim>",
    "<ev:throat_cough>",
    "<spk:0>",
    "<spk:1>",
    "<spk:2>",
    "<spk:3>",
    "<spk:4>",
    "<spk:5>",
    "<spk:6>",
    "<spk:7>",
    "<spk:8>",
    "<spk:9>",
    "<sty:end:anger_contempt>",
    "<sty:end:authority_assertion>",
    "<sty:end:calm_reflective>",
    "<sty:end:fear_urgency>",
    "<sty:end:flat>",
    "<sty:end:positive_affect>",
    "<sty:end:sadness_regret>",
    "<sty:end:social_intent>",
    "<sty:end:uncertainty_surprise>",
    "<sty:end:vocal_intensity_pitch>",
    "<sty:end:vocal_texture_delivery>",
    "<sty:stt:anger_contempt>",
    "<sty:stt:authority_assertion>",
    "<sty:stt:calm_reflective>",
    "<sty:stt:fear_urgency>",
    "<sty:stt:flat>",
    "<sty:stt:positive_affect>",
    "<sty:stt:sadness_regret>",
    "<sty:stt:social_intent>",
    "<sty:stt:uncertainty_surprise>",
    "<sty:stt:vocal_intensity_pitch>",
    "<sty:stt:vocal_texture_delivery>",
];

fn is_py_space(ch: char) -> bool {
    ch.is_whitespace() || matches!(ch, '\x1c'..='\x1f')
}

fn is_punct(ch: char) -> bool {
    matches!(
        ch,
        ',' | '.' | '!' | '?' | ';' | ':' | '，' | '。' | '！' | '？' | '；' | '：' | '、'
    )
}

/// Port of `clean_transcript` (`s2s/speech-to-speech/src/speech_to_speech/STT/nemotron_transcribe.py:58`).
pub fn clean_transcript(text: String) -> Result<String, String> {
    let mut current = text;
    if current.contains('<') {
        for tok in ANNOTATION_TOKENS {
            if current.contains(tok) {
                current = current.replace(tok, " ");
            }
        }
    }

    let mut collapsed = String::with_capacity(current.len());
    let mut in_space = false;
    for ch in current.chars() {
        if is_py_space(ch) {
            if !collapsed.is_empty() {
                in_space = true;
            }
        } else {
            if in_space && !is_punct(ch) {
                collapsed.push(' ');
            }
            in_space = false;
            collapsed.push(ch);
        }
    }

    if collapsed.chars().any(char::is_alphanumeric) {
        Ok(collapsed)
    } else {
        Ok(String::new())
    }
}

fn language_name(code: &str) -> Option<&'static str> {
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

fn title_case(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut cap_next = true;
    for ch in s.chars() {
        if ch.is_alphabetic() {
            if cap_next {
                for upper in ch.to_uppercase() {
                    out.push(upper);
                }
                cap_next = false;
            } else {
                for lower in ch.to_lowercase() {
                    out.push(lower);
                }
            }
        } else {
            out.push(ch);
            cap_next = true;
        }
    }
    out
}

fn py_type_name(v: &Value) -> &'static str {
    match v {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(n) => {
            if n.is_f64() {
                "float"
            } else {
                "int"
            }
        }
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(o) if o.len() == 1 => match o.keys().next().map(String::as_str) {
            Some("$tuple") => "tuple",
            Some("$set") => "set",
            Some("$bytes") => "bytes",
            Some("$int") => "int",
            Some("$float" | "$num") => "float",
            _ => "dict",
        },
        Value::Object(_) => "dict",
    }
}

fn iter_values(v: &Value) -> Result<Vec<Value>, String> {
    match v {
        Value::Array(arr) => Ok(arr.clone()),
        Value::String(s) => Ok(s.chars().map(|c| Value::String(c.to_string())).collect()),
        Value::Object(o)
            if o.len() == 1 && (o.contains_key("$tuple") || o.contains_key("$set")) =>
        {
            Ok(o.get("$tuple")
                .or_else(|| o.get("$set"))
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default())
        }
        Value::Object(o) if py_type_name(v) == "dict" && !o.contains_key("$dict") => {
            Ok(o.keys().cloned().map(Value::String).collect())
        }
        _ => Err(format!(
            "TypeError: '{}' object is not iterable",
            py_type_name(v)
        )),
    }
}

/// Port of `build_prompt` (`s2s/speech-to-speech/src/speech_to_speech/STT/nemotron_transcribe.py:68`).
pub fn build_prompt(
    context: String,
    terms: serde_json::Value,
    language: serde_json::Value,
) -> Result<String, String> {
    let items = iter_values(&terms)?;
    let mut unique_terms: Vec<String> = Vec::new();
    for item in items {
        let Some(s) = item.as_str() else {
            return Err("ValueError: STT context_terms must contain nonempty strings".to_string());
        };
        let trimmed = s.trim_matches(is_py_space);
        if trimmed.is_empty() {
            return Err("ValueError: STT context_terms must contain nonempty strings".to_string());
        }
        let owned = trimmed.to_string();
        if !unique_terms.contains(&owned) {
            unique_terms.push(owned);
        }
    }

    let mut parts: Vec<String> = vec![TRANSCRIPTION_INSTRUCTION.to_string()];
    if !context.is_empty() {
        parts.push(context);
    }
    if !unique_terms.is_empty() {
        parts.push(format!("Context terms: {}.", unique_terms.join(", ")));
        parts.push("Use these spellings only when supported by the audio.".to_string());
    }

    if let Some(lang) = language.as_str() {
        let lower = lang.to_lowercase();
        if !lang.is_empty() && lower != "auto" {
            let normalized = lower.replace('_', "-");
            let code = normalized.split('-').next().unwrap_or("");
            let Some(name) = language_name(code) else {
                return Err(
                    "ValueError: Nemotron STT language must be a recognized ISO language code"
                        .to_string(),
                );
            };
            parts.push(format!("Language: {}. Do not translate.", title_case(name)));
        }
    }

    Ok(parts.join(" "))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_clean_transcript_strips_annotations_and_fixes_punct() {
        assert_eq!(
            clean_transcript(
                "<spk:0> <ev:breath> Hello , world ! <sty:stt:calm_reflective> How are you ? <sty:end:calm_reflective>"
                    .to_string()
            ),
            Ok("Hello, world! How are you?".to_string())
        );
        assert_eq!(
            clean_transcript("<ev:laughter> <ev:breath> . ! ?".to_string()),
            Ok(String::new())
        );
    }

    #[test]
    fn test_build_prompt_dedupes_terms_and_resolves_language() {
        let p = build_prompt(
            "Voice assistant session.".to_string(),
            json!(["Jarvis", "Nemotron", "Jarvis"]),
            json!("en-US"),
        );
        assert!(p.is_ok());
        assert!(build_prompt(String::new(), json!(["valid", "   "]), json!("en")).is_err());
        assert!(build_prompt(String::new(), json!(["Jarvis"]), json!("xx-unknown")).is_err());
    }
}
