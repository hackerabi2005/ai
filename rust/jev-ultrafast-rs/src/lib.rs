//! Python bindings for `borwse harness/jev-ultrafast/jev_ultrafast/`: generated from the signatures in `port.rs` by rust-anything.
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

fn fingerprint_inner(state: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let state: serde_json::Value = crate::pyconv::FromPy::from_py(&state)?;
    let out = port::fingerprint(state)?;
    Ok(out)
}

/// `fingerprint`.
#[pyfunction]
#[pyo3(name = "fingerprint", signature = (state))]
fn fingerprint(py: Python<'_>, state: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    fingerprint_inner(state)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn validate_choice_inner(
    answer: Bound<'_, PyAny>,
    ids: Bound<'_, PyAny>,
) -> Result<serde_json::Value, String> {
    let answer: serde_json::Value = crate::pyconv::FromPy::from_py(&answer)?;
    let ids: serde_json::Value = crate::pyconv::FromPy::from_py(&ids)?;
    let out = port::validate_choice(answer, ids)?;
    Ok(out)
}

/// `validate_choice`.
#[pyfunction]
#[pyo3(name = "validate_choice", signature = (answer, ids))]
fn validate_choice(
    py: Python<'_>,
    answer: Bound<'_, PyAny>,
    ids: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    validate_choice_inner(answer, ids)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn action_space_inner(actions: Bound<'_, PyAny>) -> Result<serde_json::Value, String> {
    let actions: serde_json::Value = crate::pyconv::FromPy::from_py(&actions)?;
    let out = port::action_space(actions)?;
    Ok(out)
}

/// `action_space`.
#[pyfunction]
#[pyo3(name = "action_space", signature = (actions))]
fn action_space(py: Python<'_>, actions: Bound<'_, PyAny>) -> PyResult<Py<PyAny>> {
    action_space_inner(actions)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

fn field_context_inner(
    goal: Bound<'_, PyAny>,
    action: Bound<'_, PyAny>,
    page: Bound<'_, PyAny>,
    history: Bound<'_, PyAny>,
) -> Result<serde_json::Value, String> {
    let goal: serde_json::Value = crate::pyconv::FromPy::from_py(&goal)?;
    let action: serde_json::Value = crate::pyconv::FromPy::from_py(&action)?;
    let page: serde_json::Value = crate::pyconv::FromPy::from_py(&page)?;
    let history: serde_json::Value = crate::pyconv::FromPy::from_py(&history)?;
    let out = port::field_context(goal, action, page, history)?;
    Ok(out)
}

/// `field_context`.
#[pyfunction]
#[pyo3(name = "field_context", signature = (goal, action, page, history))]
fn field_context(
    py: Python<'_>,
    goal: Bound<'_, PyAny>,
    action: Bound<'_, PyAny>,
    page: Bound<'_, PyAny>,
    history: Bound<'_, PyAny>,
) -> PyResult<Py<PyAny>> {
    field_context_inner(goal, action, page, history)
        .map_err(error)
        .and_then(|v| crate::pyconv::ToPy::to_py(&v, py))
}

#[pymodule]
#[pyo3(name = "_native")]
fn native_module(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(fingerprint, m)?)?;
    m.add_function(wrap_pyfunction!(validate_choice, m)?)?;
    m.add_function(wrap_pyfunction!(action_space, m)?)?;
    m.add_function(wrap_pyfunction!(field_context, m)?)?;
    Ok(())
}
