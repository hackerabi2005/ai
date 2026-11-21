//! Python bindings for `jarvis-rs/python/`: generated from the signatures in `port.rs` by rust-anything.
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

fn page_summary_inner(page: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let page: serde_json::Value = crate::pyconv::FromPy::from_py(&page)?;
    let out = port::page_summary(page)?;
    Ok(out)
}

/// `page_summary`.
#[pyfunction]
#[pyo3(name = "page_summary", signature = (page))]
fn page_summary(py: Python<'_>, page: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    page_summary_inner(page)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn classify_error_inner(exc: Bound<'_, PyAny>) -> Result<String, String> {
    let exc: serde_json::Value = crate::pyconv::FromPy::from_py(&exc)?;
    let out = port::classify_error(exc)?;
    Ok(out)
}

/// `classify_error`.
#[pyfunction]
#[pyo3(name = "classify_error", signature = (exc))]
fn classify_error(exc: Bound<'_, PyAny>) -> PyResult<String> {
    classify_error_inner(exc).map_err(error)
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(page_summary, m)?)?;
    m.add_function(wrap_pyfunction!(classify_error, m)?)?;
    Ok(())
}
