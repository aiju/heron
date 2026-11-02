//! The static timing engine (infra/sta) for Python: heron.native.sta.

use pyo3::prelude::*;

/// The static timing engine (infra/sta, RFC 0048).
#[pymodule]
pub mod sta {
    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;

    /// Analyse cases: `netlist` as infra/hw/waves.py's export() makes it,
    /// `cases` a list of case dicts (infra/sta/src/input.rs, Case),
    /// `options` a dict of Options, on `jobs` threads (0: all). Returns, for
    /// each case, its branches' results as dicts, or {"error": why}.
    #[pyfunction]
    #[pyo3(signature = (netlist, cases, options, jobs=0))]
    fn analyse<'py>(
        py: Python<'py>,
        netlist: &Bound<'py, PyAny>,
        cases: &Bound<'py, PyAny>,
        options: &Bound<'py, PyAny>,
        jobs: usize,
    ) -> PyResult<Bound<'py, PyAny>> {
        let netlist: ::sta::Netlist = pythonize::depythonize(netlist)?;
        let cases: Vec<::sta::Case> = pythonize::depythonize(cases)?;
        let options: ::sta::Options = pythonize::depythonize(options)?;
        let design = ::sta::Design::new(&netlist).map_err(|e| PyValueError::new_err(e.0))?;
        let out: Vec<::sta::CaseOut> = py
            .detach(|| ::sta::analyse_all(&design, &cases, &options, jobs))
            .into_iter()
            .map(Into::into)
            .collect();
        Ok(pythonize::pythonize(py, &out)?)
    }

    /// What `netlist` leaves untimed, and its checks by the index each
    /// branch's `evaluated` names (infra/sta/src/coverage.rs).
    #[pyfunction]
    fn coverage<'py>(py: Python<'py>, netlist: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        let netlist: ::sta::Netlist = pythonize::depythonize(netlist)?;
        let design = ::sta::Design::new(&netlist).map_err(|e| PyValueError::new_err(e.0))?;
        Ok(pythonize::pythonize(py, &::sta::coverage(&design))?)
    }
}
