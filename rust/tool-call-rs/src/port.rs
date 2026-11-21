//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/`.

#![forbid(unsafe_code)]

const JSON_TOOL_CALL_END: &str = "</tool_call>";
const ENTER_CODE: &str = "<code>";
const END_CODE: &str = "</code>";

/// Port of `find_json_tool_call_end` (`s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/function_call.py:277`).
pub fn find_json_tool_call_end(block: String) -> Result<Option<i64>, String> {
    let mut in_string = false;
    let mut escaped = false;
    for (char_idx, (byte_idx, ch)) in block.char_indices().enumerate() {
        if in_string {
            if escaped {
                escaped = false;
            } else if ch == '\\' {
                escaped = true;
            } else if ch == '"' {
                in_string = false;
            }
        } else if ch == '"' {
            in_string = true;
        } else if block[byte_idx..].starts_with(JSON_TOOL_CALL_END) {
            return Ok(Some((char_idx + JSON_TOOL_CALL_END.len()) as i64));
        }
    }
    Ok(None)
}

fn py_re_escape(pattern: &str) -> String {
    let mut out = String::with_capacity(pattern.len() + 8);
    for ch in pattern.chars() {
        if matches!(
            ch,
            '(' | ')'
                | '['
                | ']'
                | '{'
                | '}'
                | '?'
                | '*'
                | '+'
                | '-'
                | '|'
                | '^'
                | '$'
                | '\\'
                | '.'
                | '&'
                | '~'
                | '#'
                | ' '
                | '\t'
                | '\n'
                | '\r'
                | '\x0b'
                | '\x0c'
        ) {
            out.push('\\');
        }
        out.push(ch);
    }
    out
}

/// Port of `build_block_regex` (`s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/tool_prompt.py:100`).
pub fn build_block_regex(
    enter_code: Option<String>,
    end_code: Option<String>,
) -> Result<String, String> {
    let enter = match (&enter_code, &end_code) {
        (Some(s), _) => s.as_str(),
        (None, None) => ENTER_CODE,
        (None, Some(_)) => {
            return Err(
                "TypeError: decoding to str: need a bytes-like object, NoneType found".to_string(),
            );
        }
    };
    let end = end_code.as_deref().unwrap_or(END_CODE);
    Ok(format!("{}.*?{}", py_re_escape(enter), py_re_escape(end)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_find_json_tool_call_end_ignores_quoted_tags_and_counts_chars() {
        assert_eq!(
            find_json_tool_call_end(
                "<tool_call>{\"name\": \"Zürich ✈️\", \"arguments\": {}}</tool_call>".to_string()
            ),
            Ok(Some(61))
        );
        assert_eq!(
            find_json_tool_call_end("<tool_call>{\"x\": \"</tool_call>\"}</tool_call>".to_string()),
            Ok(Some(44))
        );
        assert_eq!(find_json_tool_call_end("no tag".to_string()), Ok(None));
    }

    #[test]
    fn test_build_block_regex_escapes_python_special_chars() {
        assert_eq!(
            build_block_regex(None, None),
            Ok("<code>.*?</code>".to_string())
        );
        assert_eq!(
            build_block_regex(Some("[TOOL]".to_string()), Some("[/TOOL]".to_string())),
            Ok("\\[TOOL\\].*?\\[/TOOL\\]".to_string())
        );
        assert!(build_block_regex(None, Some("x".to_string())).is_err());
    }
}
