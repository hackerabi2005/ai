//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/speech_languages.py`.

#![forbid(unsafe_code)]

fn is_py_space(ch: char) -> bool {
    ch.is_whitespace() || matches!(ch, '\x1c'..='\x1f')
}

fn name_to_code(name: &str) -> Option<&'static str> {
    Some(match name {
        "english" => "en",
        "french" => "fr",
        "spanish" => "es",
        "chinese" => "zh",
        "japanese" => "ja",
        "korean" => "ko",
        "hindi" => "hi",
        "german" => "de",
        "portuguese" => "pt",
        "polish" => "pl",
        "italian" => "it",
        "dutch" => "nl",
        "russian" => "ru",
        "ukrainian" => "uk",
        "czech" => "cs",
        "slovak" => "sk",
        "hungarian" => "hu",
        "romanian" => "ro",
        "bulgarian" => "bg",
        "croatian" => "hr",
        "slovenian" => "sl",
        "serbian" => "sr",
        "danish" => "da",
        "norwegian" => "no",
        "swedish" => "sv",
        "finnish" => "fi",
        "estonian" => "et",
        "latvian" => "lv",
        "lithuanian" => "lt",
        "turkish" => "tr",
        "catalan" => "ca",
        "arabic" => "ar",
        "indonesian" => "id",
        "vietnamese" => "vi",
        "hebrew" => "he",
        "greek" => "el",
        "malay" => "ms",
        "tamil" => "ta",
        "thai" => "th",
        "urdu" => "ur",
        "latin" => "la",
        "maori" => "mi",
        "malayalam" => "ml",
        "welsh" => "cy",
        "telugu" => "te",
        "persian" => "fa",
        "bengali" => "bn",
        "azerbaijani" => "az",
        "kannada" => "kn",
        "macedonian" => "mk",
        "breton" => "br",
        "basque" => "eu",
        "icelandic" => "is",
        "armenian" => "hy",
        "nepali" => "ne",
        "mongolian" => "mn",
        "bosnian" => "bs",
        "kazakh" => "kk",
        "albanian" => "sq",
        "swahili" => "sw",
        "filipino" => "fil",
        "galician" => "gl",
        "marathi" => "mr",
        "punjabi" => "pa",
        "sinhala" => "si",
        "khmer" => "km",
        "shona" => "sn",
        "yoruba" => "yo",
        "somali" => "so",
        "afrikaans" => "af",
        "occitan" => "oc",
        "georgian" => "ka",
        "belarusian" => "be",
        "tajik" => "tg",
        "sindhi" => "sd",
        "gujarati" => "gu",
        "amharic" => "am",
        "yiddish" => "yi",
        "lao" => "lo",
        "uzbek" => "uz",
        "faroese" => "fo",
        "haitian creole" => "ht",
        "pashto" => "ps",
        "turkmen" => "tk",
        "nynorsk" => "nn",
        "maltese" => "mt",
        "sanskrit" => "sa",
        "luxembourgish" => "lb",
        "myanmar" => "my",
        "tibetan" => "bo",
        "tagalog" => "tl",
        "malagasy" => "mg",
        "assamese" => "as",
        "tatar" => "tt",
        "hawaiian" => "haw",
        "lingala" => "ln",
        "hausa" => "ha",
        "bashkir" => "ba",
        "javanese" => "jw",
        "sundanese" => "su",
        "cantonese" => "yue",
        _ => return None,
    })
}

/// Port of `normalize_language` (`s2s/speech-to-speech/src/speech_to_speech/speech_languages.py:13`).
pub fn normalize_language(language: String) -> Result<String, String> {
    let normalized = language.trim_matches(is_py_space).to_lowercase();
    Ok(name_to_code(&normalized).map_or(normalized, str::to_string))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_normalize_language_known_and_unknown() {
        assert_eq!(
            normalize_language("  English  ".to_string()),
            Ok("en".to_string())
        );
        assert_eq!(
            normalize_language("Persian".to_string()),
            Ok("fa".to_string())
        );
        assert_eq!(
            normalize_language("unknown-lang".to_string()),
            Ok("unknown-lang".to_string())
        );
    }
}
