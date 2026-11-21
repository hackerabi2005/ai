//! The Rust port of `s2s/speech-to-speech/src/speech_to_speech/utils/`.

#![forbid(unsafe_code)]

use serde_json::json;
use std::fmt::Write as _;

/// Port of `safe_identifier` (`s2s/speech-to-speech/src/speech_to_speech/utils/request_tracing.py:18`).
pub fn safe_identifier(value: serde_json::Value) -> Result<Option<String>, String> {
    let Some(s) = value.as_str() else {
        return Ok(None);
    };
    if (1..=128).contains(&s.len())
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'_' | b'.' | b'-'))
    {
        Ok(Some(s.to_string()))
    } else {
        Ok(None)
    }
}

/// Port of `next_power_of_2` (`s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:61`).
pub fn next_power_of_2(x: i64) -> Result<serde_json::Value, String> {
    if x == 0 {
        return Ok(json!(1));
    }
    let abs_val: u128 = (i128::from(x) - 1).unsigned_abs();
    let bit_len = 128 - abs_val.leading_zeros();
    let res = 1u128 << bit_len;
    if let Ok(i) = i64::try_from(res) {
        Ok(json!(i))
    } else {
        Ok(json!({ "$int": res.to_string() }))
    }
}

fn is_py_nonprintable(ch: char) -> bool {
    let u = ch as u32;
    u < 0x20
        || (0x7f..=0xa0).contains(&u)
        || u == 0x00ad
        || (0x0600..=0x0605).contains(&u)
        || u == 0x061c
        || u == 0x06dd
        || u == 0x070f
        || u == 0x08e2
        || u == 0x1680
        || u == 0x180e
        || (0x2000..=0x200f).contains(&u)
        || (0x2028..=0x202f).contains(&u)
        || (0x205f..=0x206f).contains(&u)
        || u == 0x3000
        || u == 0xfeff
        || (0xfff9..=0xfffb).contains(&u)
}

fn py_repr_str(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(s.len() + 4);
    out.push(quote);
    for ch in s.chars() {
        if ch == quote || ch == '\\' {
            out.push('\\');
            out.push(ch);
        } else if ch == '\t' {
            out.push_str("\\t");
        } else if ch == '\n' {
            out.push_str("\\n");
        } else if ch == '\r' {
            out.push_str("\\r");
        } else if is_py_nonprintable(ch) {
            let code = ch as u32;
            if code <= 0xff {
                let _ = write!(out, "\\x{code:02x}");
            } else if code <= 0xffff {
                let _ = write!(out, "\\u{code:04x}");
            } else {
                let _ = write!(out, "\\U{code:08x}");
            }
        } else {
            out.push(ch);
        }
    }
    out.push(quote);
    out
}

/// Port of `validate_device` (`s2s/speech-to-speech/src/speech_to_speech/utils/utils.py:103`).
pub fn validate_device(
    device: String,
    supported: Vec<String>,
    component: String,
) -> Result<(), String> {
    let base = device.split(':').next().unwrap_or(device.as_str());
    if device != "auto" && !supported.iter().any(|s| s == base) {
        return Err(format!(
            "ValueError: {component} supports device 'auto' or one of: {}; got {}.",
            supported.join(", "),
            py_repr_str(&device)
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_safe_identifier_ascii_bounds() {
        assert_eq!(
            safe_identifier(json!("req_123-abc.456")),
            Ok(Some("req_123-abc.456".to_string()))
        );
        assert_eq!(safe_identifier(json!("Zürich")), Ok(None));
        assert_eq!(safe_identifier(json!("")), Ok(None));
    }

    #[test]
    fn test_next_power_of_2_edges() {
        assert_eq!(next_power_of_2(0), Ok(json!(1)));
        assert_eq!(next_power_of_2(1), Ok(json!(1)));
        assert_eq!(next_power_of_2(512), Ok(json!(512)));
        assert_eq!(next_power_of_2(1000), Ok(json!(1024)));
        assert_eq!(next_power_of_2(-1), Ok(json!(4)));
        assert_eq!(
            next_power_of_2(i64::MAX),
            Ok(json!({ "$int": "9223372036854775808" }))
        );
    }

    #[test]
    fn test_validate_device_accepts_and_rejects() {
        assert_eq!(
            validate_device(
                "cuda:0".to_string(),
                vec!["cuda".to_string(), "cpu".to_string()],
                "SileroVAD".to_string()
            ),
            Ok(())
        );
        assert!(
            validate_device(
                "mps".to_string(),
                vec!["cuda".to_string(), "cpu".to_string()],
                "SileroVAD".to_string()
            )
            .is_err()
        );
    }
}
