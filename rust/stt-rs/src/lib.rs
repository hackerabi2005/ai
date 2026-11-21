//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/STT/`: generated from the signatures in `port.rs` by rust-anything.
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

fn clean_transcript_inner(text: String) -> Result<String, String> {
    let out = port::clean_transcript(text)?;
    Ok(out)
}

/// `clean_transcript`.
#[pyfunction]
#[pyo3(name = "clean_transcript", signature = (text))]
fn clean_transcript(text: String) -> PyResult<String> {
    clean_transcript_inner(text).map_err(error)
}

fn build_prompt_inner(
    context: String,
    terms: Bound<'_, PyAny>,
    language: Bound<'_, PyAny>,
) -> Result<String, String> {
    let terms: serde_json::Value = crate::pyconv::FromPy::from_py(&terms)?;
    let language: serde_json::Value = crate::pyconv::FromPy::from_py(&language)?;
    let out = port::build_prompt(context, terms, language)?;
    Ok(out)
}

/// `build_prompt`.
#[pyfunction]
#[pyo3(name = "build_prompt", signature = (context, terms, language))]
fn build_prompt(
    context: String,
    terms: Bound<'_, PyAny>,
    language: Bound<'_, PyAny>,
) -> PyResult<String> {
    build_prompt_inner(context, terms, language).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(clean_transcript, m)?)?;
    m.add_function(wrap_pyfunction!(build_prompt, m)?)?;
    Ok(())
}
