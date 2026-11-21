//! The Rust port of `jarvis-rs/python/`.

#![forbid(unsafe_code)]

use serde_json::{Map, Value, json};

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

fn as_dict(v: &Value) -> Option<&Map<String, Value>> {
    match v {
        Value::Object(o) if py_type_name(v) == "dict" && !o.contains_key("$dict") => Some(o),
        _ => None,
    }
}

fn py_is_truthy(v: &Value) -> bool {
    match v {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

fn slice_prefix(v: &Value, max_len: usize) -> Result<Value, String> {
    match v {
        Value::String(s) => Ok(Value::String(s.chars().take(max_len).collect())),
        Value::Array(arr) => Ok(Value::Array(arr.iter().take(max_len).cloned().collect())),
        Value::Object(o) if o.len() == 1 && o.contains_key("$tuple") => {
            let arr = o
                .get("$tuple")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let sliced: Vec<Value> = arr.into_iter().take(max_len).collect();
            Ok(json!({"$tuple": sliced}))
        }
        _ => {
            if as_dict(v).is_some() {
                Err(format!("KeyError: slice(None, {max_len}, None)"))
            } else {
                Err(format!(
                    "TypeError: '{}' object is not subscriptable",
                    py_type_name(v)
                ))
            }
        }
    }
}

/// Port of `page_summary` (`jarvis-rs/python/jev_bridge.py:23`).
pub fn page_summary(page: Value) -> Result<Value, String> {
    let Some(map) = as_dict(&page) else {
        return Err(format!(
            "AttributeError: '{}' object has no attribute 'get'",
            py_type_name(&page)
        ));
    };
    let empty = || Value::String(String::new());
    let url = map.get("url").cloned().unwrap_or_else(empty);
    let title = map.get("title").cloned().unwrap_or_else(empty);
    let raw_text = map.get("text").filter(|v| py_is_truthy(v));
    let text = match raw_text {
        Some(v) => slice_prefix(v, 6000)?,
        None => empty(),
    };
    let fingerprint = map.get("fingerprint").cloned().unwrap_or_else(empty);

    let mut out = Map::new();
    out.insert("url".to_string(), url);
    out.insert("title".to_string(), title);
    out.insert("text".to_string(), text);
    out.insert("fingerprint".to_string(), fingerprint);
    Ok(Value::Object(out))
}

/// Port of `classify_error` (`jarvis-rs/python/jev_bridge.py:33`).
pub fn classify_error(exc: Value) -> Result<String, String> {
    let msg = match &exc {
        Value::String(s) => s.to_lowercase(),
        Value::Null => "none".to_string(),
        Value::Bool(true) => "true".to_string(),
        Value::Bool(false) => "false".to_string(),
        other => other.to_string().to_lowercase(),
    };
    if msg.contains("api_key") || msg.contains("credential") {
        return Ok("missing_key".to_string());
    }
    if msg.contains("budget") {
        return Ok("budget_exceeded".to_string());
    }
    if [
        "allow",
        "devtools",
        "chrome",
        "daemon",
        "target",
        "closed",
        "websocket",
        "session",
        "detached",
        "broken pipe",
        "connection",
    ]
    .iter()
    .any(|k| msg.contains(k))
    {
        return Ok("chrome_not_ready".to_string());
    }
    Ok("browser_error".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_page_summary_defaults_and_truncation() {
        let p = json!({
            "url": "https://example.com",
            "title": "Example",
            "text": null,
            "fingerprint": "fp1"
        });
        assert_eq!(
            page_summary(p),
            Ok(json!({
                "url": "https://example.com",
                "title": "Example",
                "text": "",
                "fingerprint": "fp1"
            }))
        );
    }

    #[test]
    fn test_classify_error_categories() {
        assert_eq!(
            classify_error(json!("Missing EXPERIENTIAL_API_KEY")),
            Ok("missing_key".to_string())
        );
        assert_eq!(
            classify_error(json!("Step budget exceeded")),
            Ok("budget_exceeded".to_string())
        );
        assert_eq!(
            classify_error(json!("Chrome DevTools target closed")),
            Ok("chrome_not_ready".to_string())
        );
        assert_eq!(
            classify_error(json!("Some other problem")),
            Ok("browser_error".to_string())
        );
    }
}
