//! Python bindings for `s2s/speech-to-speech/src/speech_to_speech/utils/`: generated from the signatures in `port.rs` by rust-anything.
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

fn safe_identifier_inner(value: Bound<'_, PyAny>) -> Result<Option<String>, String> {
    let value: serde_json::Value = crate::pyconv::FromPy::from_py(&value)?;
    let out = port::safe_identifier(value)?;
    Ok(out)
}

/// `safe_identifier`.
#[pyfunction]
#[pyo3(name = "safe_identifier", signature = (value))]
fn safe_identifier(value: Bound<'_, PyAny>) -> PyResult<Option<String>> {
    safe_identifier_inner(value).map_err(error)
}

fn next_power_of_2_inner(x: i64) -> Result<serde_json::Value, String> {
    let out = port::next_power_of_2(x)?;
    Ok(out)
}

/// `next_power_of_2`.
#[pyfunction]
#[pyo3(name = "next_power_of_2", signature = (x))]
fn next_power_of_2(py: Python<'_>, x: i64) -> PyResult<Py<PyAny>> {
    next_power_of_2_inner(x)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn validate_device_inner(
    device: String,
    supported: Vec<String>,
    component: String,
) -> Result<(), String> {
    port::validate_device(device, supported, component)?;
    Ok(())
}

/// `validate_device`.
#[pyfunction]
#[pyo3(name = "validate_device", signature = (device, supported, component))]
fn validate_device(device: String, supported: Vec<String>, component: String) -> PyResult<()> {
    validate_device_inner(device, supported, component).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(safe_identifier, m)?)?;
    m.add_function(wrap_pyfunction!(next_power_of_2, m)?)?;
    m.add_function(wrap_pyfunction!(validate_device, m)?)?;
    Ok(())
}
