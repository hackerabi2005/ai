//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/pipeline/`: generated from the signatures in `port.rs` by rust-anything.
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

fn set_log_transcripts_inner(enabled: bool) -> Result<(), String> {
    port::set_log_transcripts(enabled)?;
    Ok(())
}

/// `set_log_transcripts`.
#[pyfunction]
#[pyo3(name = "set_log_transcripts", signature = (enabled))]
fn set_log_transcripts(enabled: bool) -> PyResult<()> {
    set_log_transcripts_inner(enabled).map_err(error)
}

fn transcript_for_log_inner(text: Bound<'_, PyAny>) -> Result<String, String> {
    let text: serde_json::Value = crate::pyconv::FromPy::from_py(&text)?;
    let out = port::transcript_for_log(text)?;
    Ok(out)
}

/// `transcript_for_log`.
#[pyfunction]
#[pyo3(name = "transcript_for_log", signature = (text))]
fn transcript_for_log(text: Bound<'_, PyAny>) -> PyResult<String> {
    transcript_for_log_inner(text).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(set_log_transcripts, m)?)?;
    m.add_function(wrap_pyfunction!(transcript_for_log, m)?)?;
    Ok(())
}
