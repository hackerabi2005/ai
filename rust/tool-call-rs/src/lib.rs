//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/LLM/tool_call/`: generated from the signatures in `port.rs` by rust-anything.
//! Regenerate with `rust-anything refresh` after changing them.

use pyo3::prelude::*;

pub mod port;

fn error(message: String) -> PyErr {
    use pyo3::exceptions as e;
    let (kind, text) = message.split_once(": ").unwrap_or(("", message.as_str()));
    let text = text.to_string();
    match kind {
        "TypeError" => e::PyTypeError::new_err(text),
        "KeyError" => e::PyKeyError::new_err(text),
        "IndexError" => e::PyIndexError::new_err(text),
        "OverflowError" => e::PyOverflowError::new_err(text),
        "ZeroDivisionError" => e::PyZeroDivisionError::new_err(text),
        "AttributeError" => e::PyAttributeError::new_err(text),
        "RuntimeError" => e::PyRuntimeError::new_err(text),
        "NotImplementedError" => e::PyNotImplementedError::new_err(text),
        "LookupError" => e::PyLookupError::new_err(text),
        "ArithmeticError" => e::PyArithmeticError::new_err(text),
        "UnicodeError" => e::PyUnicodeError::new_err(text),
        "ValueError" => e::PyValueError::new_err(text),
        _ => e::PyValueError::new_err(message),
    }
}

fn find_json_tool_call_end_inner(block: String) -> Result<Option<i64>, String> {
    let out = port::find_json_tool_call_end(block)?;
    Ok(out)
}

/// `find_json_tool_call_end`.
#[pyfunction]
#[pyo3(name = "find_json_tool_call_end", signature = (block))]
fn find_json_tool_call_end(block: String) -> PyResult<Option<i64>> {
    find_json_tool_call_end_inner(block).map_err(error)
}

fn build_block_regex_inner(
    enter_code: Option<String>,
    end_code: Option<String>,
) -> Result<String, String> {
    let out = port::build_block_regex(enter_code, end_code)?;
    Ok(out)
}

/// `build_block_regex`.
#[pyfunction]
#[pyo3(name = "build_block_regex", signature = (enter_code=None, end_code=None))]
fn build_block_regex(enter_code: Option<String>, end_code: Option<String>) -> PyResult<String> {
    build_block_regex_inner(enter_code, end_code).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(find_json_tool_call_end, m)?)?;
    m.add_function(wrap_pyfunction!(build_block_regex, m)?)?;
    Ok(())
}
