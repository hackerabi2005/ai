//! The Rust port of `borwse harness/jev-ultrafast/jev_ultrafast/`.

#![forbid(unsafe_code)]

use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use std::fmt::Write as _;

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

fn subscript_str<'a>(v: &'a Value, key: &str) -> Result<&'a Value, String> {
    if let Some(map) = as_dict(v) {
        return map.get(key).ok_or_else(|| format!("KeyError: '{key}'"));
    }
    match py_type_name(v) {
        "list" => Err("TypeError: list indices must be integers or slices, not str".to_string()),
        "tuple" => Err("TypeError: tuple indices must be integers or slices, not str".to_string()),
        "str" => Err("TypeError: string indices must be integers, not 'str'".to_string()),
        t => Err(format!("TypeError: '{t}' object is not subscriptable")),
    }
}

fn dict_with_get(v: &Value) -> Result<&Map<String, Value>, String> {
    as_dict(v).ok_or_else(|| {
        format!(
            "AttributeError: '{}' object has no attribute 'get'",
            py_type_name(v)
        )
    })
}

fn py_escape_json_str(s: &str, out: &mut String) {
    out.push('"');
    for ch in s.chars() {
        match ch {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\x08' => out.push_str("\\b"),
            '\x0c' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 || (c as u32) > 0x7e => {
                let code = c as u32;
                if code <= 0xffff {
                    let _ = write!(out, "\\u{code:04x}");
                } else {
                    let u = code - 0x10000;
                    let high = 0xd800 + (u >> 10);
                    let low = 0xdc00 + (u & 0x3ff);
                    let _ = write!(out, "\\u{high:04x}\\u{low:04x}");
                }
            }
            c => out.push(c),
        }
    }
    out.push('"');
}

fn py_json_dumps_sorted(v: &Value, out: &mut String) -> Result<(), String> {
    match v {
        Value::Null => out.push_str("null"),
        Value::Bool(true) => out.push_str("true"),
        Value::Bool(false) => out.push_str("false"),
        Value::Number(n) => out.push_str(&n.to_string()),
        Value::String(s) => py_escape_json_str(s, out),
        Value::Array(items) => {
            out.push('[');
            for (i, item) in items.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                py_json_dumps_sorted(item, out)?;
            }
            out.push(']');
        }
        Value::Object(map) => {
            if let Some(arr) = map.get("$tuple").and_then(Value::as_array)
                && map.len() == 1
            {
                return py_json_dumps_sorted(&Value::Array(arr.clone()), out);
            }
            if let Some(s) = map.get("$int").and_then(Value::as_str)
                && map.len() == 1
            {
                out.push_str(s);
                return Ok(());
            }
            let mut keys: Vec<&String> = map.keys().collect();
            keys.sort();
            out.push('{');
            for (i, k) in keys.iter().enumerate() {
                if i > 0 {
                    out.push_str(", ");
                }
                py_escape_json_str(k, out);
                out.push_str(": ");
                if let Some(val) = map.get(*k) {
                    py_json_dumps_sorted(val, out)?;
                }
            }
            out.push('}');
        }
    }
    Ok(())
}

/// Port of `fingerprint` (`borwse harness/jev-ultrafast/jev_ultrafast/browser.py:662`).
pub fn fingerprint(state: Value) -> Result<Value, String> {
    let mut content = Map::new();
    for k in ["url", "text", "actions", "scroll"] {
        let val = subscript_str(&state, k)?;
        content.insert(k.to_string(), val.clone());
    }
    let mut dumped = String::new();
    py_json_dumps_sorted(&Value::Object(content), &mut dumped)?;
    let mut hasher = Sha256::new();
    hasher.update(dumped.as_bytes());
    let digest = hasher.finalize();
    let mut hex = String::with_capacity(64);
    for b in digest {
        let _ = write!(hex, "{b:02x}");
    }
    Ok(Value::String(hex))
}

fn extract_finite_unit_num(v: &Value) -> Option<f64> {
    match v {
        Value::Number(n) => {
            let f = n.as_f64()?;
            (f.is_finite() && (0.0..=1.0).contains(&f)).then_some(f)
        }
        Value::Object(o) if o.len() == 1 => {
            if let Some(s) = o.get("$num").and_then(Value::as_str) {
                return (s == "-0").then_some(0.0);
            }
            if let Some(s) = o.get("$float").and_then(Value::as_str) {
                let f: f64 = s.parse().ok()?;
                return (f.is_finite() && (0.0..=1.0).contains(&f)).then_some(f);
            }
            if let Some(s) = o.get("$int").and_then(Value::as_str) {
                return match s {
                    "0" => Some(0.0),
                    "1" => Some(1.0),
                    _ => None,
                };
            }
            None
        }
        _ => None,
    }
}

fn extract_ids_set(ids: &Value, choice: &str) -> Option<(BTreeSet<String>, bool)> {
    match ids {
        Value::Array(arr) => {
            let mut set = BTreeSet::new();
            for item in arr {
                set.insert(item.as_str()?.to_string());
            }
            let contains = set.contains(choice);
            Some((set, contains))
        }
        Value::String(s) => {
            let set: BTreeSet<String> = s.chars().map(|c| c.to_string()).collect();
            Some((set, s.contains(choice)))
        }
        Value::Object(o)
            if o.len() == 1 && (o.contains_key("$tuple") || o.contains_key("$set")) =>
        {
            let arr = o
                .get("$tuple")
                .or_else(|| o.get("$set"))
                .and_then(Value::as_array)?;
            let mut set = BTreeSet::new();
            for item in arr {
                set.insert(item.as_str()?.to_string());
            }
            let contains = set.contains(choice);
            Some((set, contains))
        }
        _ => {
            let map = as_dict(ids)?;
            let set: BTreeSet<String> = map.keys().cloned().collect();
            let contains = set.contains(choice);
            Some((set, contains))
        }
    }
}

/// Port of `validate_choice` (`borwse harness/jev-ultrafast/jev_ultrafast/model.py:44`).
pub fn validate_choice(answer: Value, ids: Value) -> Result<Value, String> {
    let invalid = || "ValueError: Invalid TypeSafe response; no action executed.".to_string();
    let Some(ans_map) = as_dict(&answer) else {
        return Err(invalid());
    };
    let Some(probs_val) = ans_map.get("probabilities") else {
        return Err(invalid());
    };
    let Some(probs_map) = as_dict(probs_val) else {
        return Err(invalid());
    };
    let Some(conf_val) = ans_map.get("confidence") else {
        return Err(invalid());
    };
    let Some(choice_str) = ans_map.get("choice").and_then(Value::as_str) else {
        return Err(invalid());
    };
    let Some((ids_set, choice_in_ids)) = extract_ids_set(&ids, choice_str) else {
        return Err(invalid());
    };
    if !choice_in_ids {
        return Err(invalid());
    }
    let prob_keys: BTreeSet<String> = probs_map.keys().cloned().collect();
    if prob_keys != ids_set {
        return Err(invalid());
    }
    let Some(_conf) = extract_finite_unit_num(conf_val) else {
        return Err(invalid());
    };
    let mut sum = 0.0_f64;
    let mut max_p = f64::NEG_INFINITY;
    let mut choice_p = None;
    for (k, v) in probs_map {
        let Some(p) = extract_finite_unit_num(v) else {
            return Err(invalid());
        };
        sum += p;
        if p > max_p {
            max_p = p;
        }
        if k == choice_str {
            choice_p = Some(p);
        }
    }
    let Some(chosen_prob) = choice_p else {
        return Err(invalid());
    };
    if (sum - 1.0).abs() >= 0.02 || chosen_prob < max_p - 1e-6 {
        return Err(invalid());
    }
    Ok(answer)
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
        _ => {
            if let Some(map) = as_dict(v) {
                Ok(map.keys().cloned().map(Value::String).collect())
            } else {
                Err(format!(
                    "TypeError: '{}' object is not iterable",
                    py_type_name(v)
                ))
            }
        }
    }
}

/// Port of `action_space` (`borwse harness/jev-ultrafast/jev_ultrafast/model.py:62`).
pub fn action_space(actions: Value) -> Result<Value, String> {
    let items = iter_values(&actions)?;
    let mut elements: Vec<Map<String, Value>> = Vec::new();
    let mut indices: HashMap<String, usize> = HashMap::new();
    let mut targets: Map<String, Value> = Map::new();
    let mut controls: Map<String, Value> = Map::new();

    for action in items {
        let kind_val = subscript_str(&action, "kind")?;
        let kind_str = kind_val.as_str().unwrap_or("");
        let op_opt = match kind_str {
            "click" => Some("CLICK"),
            "fill" => Some("TYPE_TEXT"),
            "select" => Some("SELECT"),
            _ => None,
        };
        let Some(operation) = op_opt else {
            let id_val = subscript_str(&action, "id")?;
            let id_str = id_val.as_str().ok_or_else(|| {
                format!(
                    "AttributeError: '{}' object has no attribute 'upper'",
                    py_type_name(id_val)
                )
            })?;
            controls.insert(id_str.to_uppercase(), action);
            continue;
        };

        let node_val = subscript_str(&action, "node")?;
        let node_key = serde_json::to_string(node_val).unwrap_or_default();
        let elem_idx = if let Some(&existing_idx) = indices.get(&node_key) {
            existing_idx
        } else {
            let new_idx = elements.len() + 1;
            let index_str = new_idx.to_string();
            let mut element = Map::new();
            for k in ["role", "value", "checked", "selected", "expanded"] {
                if let Ok(v) = subscript_str(&action, k) {
                    element.insert(k.to_string(), v.clone());
                }
            }
            let label_val = subscript_str(&action, "label")?;
            let label_str = label_val.as_str().ok_or_else(|| {
                format!(
                    "AttributeError: '{}' object has no attribute 'split'",
                    py_type_name(label_val)
                )
            })?;
            let base_label = label_str.split(" → ").next().unwrap_or("");
            element.insert("index".to_string(), Value::String(index_str));
            element.insert("label".to_string(), Value::String(base_label.to_string()));
            element.insert("operations".to_string(), Value::Array(Vec::new()));
            if kind_str == "select" {
                let cur_val = subscript_str(&action, "current_value")
                    .cloned()
                    .unwrap_or_else(|_| Value::String(String::new()));
                element.insert("value".to_string(), cur_val);
                element.insert("options".to_string(), Value::Array(Vec::new()));
            }
            elements.push(element);
            indices.insert(node_key, new_idx);
            new_idx
        };

        let index_str = elem_idx.to_string();
        if !targets.contains_key(operation) {
            targets.insert(operation.to_string(), Value::Object(Map::new()));
        }

        let mut target_key = index_str.clone();
        if let Some(element) = elements.get_mut(elem_idx - 1) {
            if let Some(Value::Array(ops)) = element.get_mut("operations") {
                let op_val = Value::String(operation.to_string());
                if !ops.contains(&op_val) {
                    ops.push(op_val);
                }
            }
            if kind_str == "select" {
                let label_val = subscript_str(&action, "label")?.clone();
                let value_val = subscript_str(&action, "value")?.clone();
                if let Some(Value::Array(opts)) = element.get_mut("options") {
                    target_key = format!("{index_str}:{}", opts.len() + 1);
                    let mut opt_map = Map::new();
                    opt_map.insert("index".to_string(), Value::String(target_key.clone()));
                    opt_map.insert("label".to_string(), label_val);
                    opt_map.insert("value".to_string(), value_val);
                    opts.push(Value::Object(opt_map));
                }
            }
        }

        if let Some(Value::Object(group)) = targets.get_mut(operation) {
            group.insert(target_key, action);
        }
    }

    let elements_val = Value::Array(elements.into_iter().map(Value::Object).collect());
    Ok(json!({
        "$tuple": [elements_val, Value::Object(targets), Value::Object(controls)]
    }))
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

fn slice_last(v: &Value, count: usize) -> Result<Vec<Value>, String> {
    match v {
        Value::Array(arr) => {
            let start = arr.len().saturating_sub(count);
            Ok(arr[start..].to_vec())
        }
        Value::String(s) => {
            let chars: Vec<char> = s.chars().collect();
            let start = chars.len().saturating_sub(count);
            Ok(chars[start..]
                .iter()
                .map(|c| Value::String(c.to_string()))
                .collect())
        }
        Value::Object(o) if o.len() == 1 && o.contains_key("$tuple") => {
            let arr = o
                .get("$tuple")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();
            let start = arr.len().saturating_sub(count);
            Ok(arr[start..].to_vec())
        }
        _ => {
            if as_dict(v).is_some() {
                Err(format!("KeyError: slice(-{count}, None, None)"))
            } else {
                Err(format!(
                    "TypeError: '{}' object is not subscriptable",
                    py_type_name(v)
                ))
            }
        }
    }
}

/// Port of `field_context` (`borwse harness/jev-ultrafast/jev_ultrafast/model.py:219`).
pub fn field_context(
    goal: Value,
    action: Value,
    page: Value,
    history: Value,
) -> Result<Value, String> {
    let action_map = dict_with_get(&action)?;
    let mut field = Map::new();
    for k in ["label", "role", "value"] {
        field.insert(
            k.to_string(),
            action_map.get(k).cloned().unwrap_or(Value::Null),
        );
    }

    let title = subscript_str(&page, "title")?.clone();
    let text_raw = subscript_str(&page, "text")?;
    let text = slice_prefix(text_raw, 6000)?;
    let mut page_out = Map::new();
    page_out.insert("title".to_string(), title);
    page_out.insert("text".to_string(), text);

    let history_tail = slice_last(&history, 6)?;
    let mut recent_actions = Vec::with_capacity(history_tail.len());
    for h in history_tail {
        let h_map = dict_with_get(&h)?;
        let mut entry = Map::new();
        for k in ["action", "text"] {
            entry.insert(k.to_string(), h_map.get(k).cloned().unwrap_or(Value::Null));
        }
        recent_actions.push(Value::Object(entry));
    }

    let mut out = Map::new();
    out.insert("goal".to_string(), goal);
    out.insert("field".to_string(), Value::Object(field));
    out.insert("page".to_string(), Value::Object(page_out));
    out.insert("recent_actions".to_string(), Value::Array(recent_actions));
    Ok(Value::Object(out))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fingerprint_canonical_sha256() {
        let state = json!({
            "url": "https://www.google.com/travel/flights?hl=en",
            "text": "Zürich → London ✈️",
            "scroll": {"x": 0, "y": 420},
            "actions": [],
            "screenshot": "ignored"
        });
        let fp = fingerprint(state);
        assert_eq!(
            fp,
            Ok(Value::String(
                "21d84bcc0d562eb7f0c654c3d3b9433d0358dac914db145696e1a7a7352d8b9a".to_string()
            ))
        );
    }

    #[test]
    fn test_validate_choice_rejects_bool_and_non_max() {
        let valid = json!({
            "choice": "a",
            "confidence": 1.0,
            "probabilities": {"a": 1.0, "b": 0.0}
        });
        assert!(validate_choice(valid, json!(["a", "b"])).is_ok());

        let bool_conf = json!({
            "choice": "a",
            "confidence": true,
            "probabilities": {"a": 1.0, "b": 0.0}
        });
        assert!(validate_choice(bool_conf, json!(["a", "b"])).is_err());

        let non_max = json!({
            "choice": "b",
            "confidence": 1.0,
            "probabilities": {"a": 0.9, "b": 0.1}
        });
        assert!(validate_choice(non_max, json!(["a", "b"])).is_err());
    }

    #[test]
    fn test_action_space_groups_elements_and_select_options() {
        let actions = json!([
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search → Dropdown", "role": "textbox", "value": "", "node": 10},
            {"id": "s1", "kind": "select", "label": "Ticket → One way", "role": "combobox", "value": "one_way", "current_value": "round_trip", "node": 30},
            {"id": "wait", "kind": "wait", "label": "Wait"}
        ]);
        let res = action_space(actions);
        assert!(res.is_ok());
    }

    #[test]
    fn test_field_context_truncates_history_and_text() {
        let ctx = field_context(
            json!("Goal"),
            json!({"label": "Search", "role": "textbox", "value": ""}),
            json!({"title": "Title", "text": "Hello"}),
            json!([
                {"action": "1"},
                {"action": "2"},
                {"action": "3"},
                {"action": "4"},
                {"action": "5"},
                {"action": "6"},
                {"action": "7", "text": "last"}
            ]),
        );
        assert!(ctx.is_ok());
    }
}
