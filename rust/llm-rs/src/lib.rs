//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/LLM/`: generated from the signatures in `port.rs` by rust-anything.
//! Regenerate with `rust-anything refresh` after changing them.

use pyo3::prelude::*;

pub mod js;
pub mod port;
pub mod pyconv;
pub mod pynum;

#[allow(unused_imports)]
use pynum::Num;

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

fn build_text_system_prompt_inner(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> Result<String, String> {
    let out = port::build_text_system_prompt(session_prompt, tool_section, language_name)?;
    Ok(out)
}

/// `build_text_system_prompt`.
#[pyfunction]
#[pyo3(name = "build_text_system_prompt", signature = (session_prompt, *, tool_section=String::from(""), language_name=None))]
fn build_text_system_prompt(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> PyResult<String> {
    build_text_system_prompt_inner(session_prompt, tool_section, language_name).map_err(error)
}

fn remove_markdown_inner(text: String) -> Result<String, String> {
    let out = port::remove_markdown(text)?;
    Ok(out)
}

/// `remove_markdown`.
#[pyfunction]
#[pyo3(name = "remove_markdown", signature = (text))]
fn remove_markdown(text: String) -> PyResult<String> {
    remove_markdown_inner(text).map_err(error)
}

fn remove_unspeechable_inner(text: String) -> Result<String, String> {
    let out = port::remove_unspeechable(text)?;
    Ok(out)
}

/// `remove_unspeechable`.
#[pyfunction]
#[pyo3(name = "remove_unspeechable", signature = (text))]
fn remove_unspeechable(text: String) -> PyResult<String> {
    remove_unspeechable_inner(text).map_err(error)
}

fn format_language_instruction_inner(lang_name: String) -> Result<String, String> {
    let out = port::format_language_instruction(lang_name)?;
    Ok(out)
}

/// `format_language_instruction`.
#[pyfunction]
#[pyo3(name = "format_language_instruction", signature = (lang_name))]
fn format_language_instruction(lang_name: String) -> PyResult<String> {
    format_language_instruction_inner(lang_name).map_err(error)
}

fn language_name_for_prompt_inner(
    language_code: Option<String>,
    enable: bool,
) -> Result<Option<String>, String> {
    let out = port::language_name_for_prompt(language_code, enable)?;
    Ok(out)
}

/// `language_name_for_prompt`.
#[pyfunction]
#[pyo3(name = "language_name_for_prompt", signature = (language_code, *, enable))]
fn language_name_for_prompt(
    language_code: Option<String>,
    enable: bool,
) -> PyResult<Option<String>> {
    language_name_for_prompt_inner(language_code, enable).map_err(error)
}

fn resolve_auto_language_inner(language_code: Option<String>) -> Result<serde_json::Value, String> {
    let out = port::resolve_auto_language(language_code)?;
    Ok(out)
}

/// `resolve_auto_language`.
#[pyfunction]
#[pyo3(name = "resolve_auto_language", signature = (language_code))]
fn resolve_auto_language(py: Python<'_>, language_code: Option<String>) -> PyResult<Py<PyAny>> {
    resolve_auto_language_inner(language_code)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn build_voice_system_prompt_inner(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> Result<String, String> {
    let out = port::build_voice_system_prompt(session_prompt, tool_section, language_name)?;
    Ok(out)
}

/// `build_voice_system_prompt`.
#[pyfunction]
#[pyo3(name = "build_voice_system_prompt", signature = (session_prompt, *, tool_section=String::from(""), language_name=None))]
fn build_voice_system_prompt(
    session_prompt: String,
    tool_section: String,
    language_name: Option<String>,
) -> PyResult<String> {
    build_voice_system_prompt_inner(session_prompt, tool_section, language_name).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(build_text_system_prompt, m)?)?;
    m.add_function(wrap_pyfunction!(remove_markdown, m)?)?;
    m.add_function(wrap_pyfunction!(remove_unspeechable, m)?)?;
    m.add_function(wrap_pyfunction!(format_language_instruction, m)?)?;
    m.add_function(wrap_pyfunction!(language_name_for_prompt, m)?)?;
    m.add_function(wrap_pyfunction!(resolve_auto_language, m)?)?;
    m.add_function(wrap_pyfunction!(build_voice_system_prompt, m)?)?;
    Ok(())
}
