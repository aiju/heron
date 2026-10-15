//! The grid router (infra/pcbroute) for Python: heron.native.pcbroute.

use pyo3::prelude::*;

/// The grid router for printed circuit boards (infra/pcbroute).
#[pymodule]
pub mod pcbroute {
    use pyo3::prelude::*;

    /// Route a problem (a dict as pcbroute::Problem has it: the grid, the
    /// rules, the shapes and the nets). Returns the solution as a dict.
    #[pyfunction]
    fn route<'py>(py: Python<'py>, problem: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let problem: ::pcbroute::Problem = pythonize::depythonize(problem)?;
        let sol = py.detach(|| ::pcbroute::route(&problem));
        Ok(pythonize::pythonize(py, &sol)?)
    }
}
