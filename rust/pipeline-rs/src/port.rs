//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/pipeline/`.

#![forbid(unsafe_code)]

use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};

static LOG_TRANSCRIPTS: AtomicBool = AtomicBool::new(false);

/// Port of `set_log_transcripts` (`s2s/speech-to-speech/src/speech_to_speech/pipeline/transcript_logging.py:35`).
pub fn set_log_transcripts(enabled: bool) -> Result<(), String> {
    LOG_TRANSCRIPTS.store(enabled, Ordering::SeqCst);
    Ok(())
}

fn py_repr_val(v: &Value) -> String {
    match v {
        Value::Null => "None".to_string(),
        Value::Bool(true) => "True".to_string(),
        Value::Bool(false) => "False".to_string(),
        Value::Number(n) => {
            if let Some(i) = n.as_i64()
                && !n.is_f64()
            {
                return i.to_string();
            }
            if let Some(u) = n.as_u64()
                && !n.is_f64()
            {
                return u.to_string();
            }
            if let Some(f) = n.as_f64() {
                return crate::js::number_to_string(f);
            }
            n.to_string()
        }
        Value::String(s) => format!("'{}'", s.replace('\\', "\\\\").replace('\'', "\\'")),
        Value::Array(items) => {
            let inner: Vec<String> = items.iter().map(py_repr_val).collect();
            format!("[{}]", inner.join(", "))
        }
        Value::Object(map) => {
            if let Some(s) = map.get("$int").and_then(Value::as_str)
                && map.len() == 1
            {
                return s.to_string();
            }
            let inner: Vec<String> = map
                .iter()
                .map(|(k, val)| format!("'{}': {}", k, py_repr_val(val)))
                .collect();
            format!("{{{}}}", inner.join(", "))
        }
    }
}

fn py_str_val(v: &Value) -> String {
    match v {
        Value::Null => String::new(),
        Value::String(s) => s.clone(),
        other => py_repr_val(other),
    }
}

/// Port of `transcript_for_log` (`s2s/speech-to-speech/src/speech_to_speech/pipeline/transcript_logging.py:47`).
pub fn transcript_for_log(text: serde_json::Value) -> Result<String, String> {
    let value = py_str_val(&text);
    if LOG_TRANSCRIPTS.load(Ordering::SeqCst) {
        Ok(value)
    } else {
        Ok(format!("chars={}", value.chars().count()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn test_transcript_for_log_modes() {
        let _ = set_log_transcripts(false);
        assert_eq!(
            transcript_for_log(json!("Hello")),
            Ok("chars=5".to_string())
        );
        assert_eq!(transcript_for_log(Value::Null), Ok("chars=0".to_string()));
        let _ = set_log_transcripts(true);
        assert_eq!(transcript_for_log(json!("Hello")), Ok("Hello".to_string()));
        let _ = set_log_transcripts(false);
    }
}
