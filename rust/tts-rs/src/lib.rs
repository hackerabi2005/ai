//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/TTS/`: generated from the signatures in `port.rs` by rust-anything.
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

fn number_to_words_inner(n: i64) -> Result<String, String> {
    let out = port::number_to_words(n)?;
    Ok(out)
}

/// `number_to_words`.
#[pyfunction]
#[pyo3(name = "number_to_words", signature = (n))]
fn number_to_words(n: i64) -> PyResult<String> {
    number_to_words_inner(n).map_err(error)
}

fn numbers_to_words_inner(text: String) -> Result<String, String> {
    let out = port::numbers_to_words(text)?;
    Ok(out)
}

/// `numbers_to_words`.
#[pyfunction]
#[pyo3(name = "numbers_to_words", signature = (text))]
fn numbers_to_words(text: String) -> PyResult<String> {
    numbers_to_words_inner(text).map_err(error)
}

fn normalize_inner(text: String, spell_numbers: bool) -> Result<String, String> {
    let out = port::normalize(text, spell_numbers)?;
    Ok(out)
}

/// `normalize`.
#[pyfunction]
#[pyo3(name = "normalize", signature = (text, *, spell_numbers=true))]
fn normalize(text: String, spell_numbers: bool) -> PyResult<String> {
    normalize_inner(text, spell_numbers).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(number_to_words, m)?)?;
    m.add_function(wrap_pyfunction!(numbers_to_words, m)?)?;
    m.add_function(wrap_pyfunction!(normalize, m)?)?;
    Ok(())
}
