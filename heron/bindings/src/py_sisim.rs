//! The signal-integrity simulator (infra/sisim) for Python:
//! heron.native.sisim. infra/si/engine.py builds its input from SPICE
//! netlists.

use pyo3::prelude::*;

/// The fixed-step transient simulator (infra/sisim).
#[pymodule]
pub mod sisim {
    use pyo3::exceptions::{PyRuntimeError, PyValueError};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict};

    /// Run a transient: `netlist` and `options` as dicts shaped like
    /// infra/sisim's Netlist and Options. Returns a dict with `time` and
    /// `data` as bytes of little-endian float64 (data is time-major, one
    /// value per probe), and `stats`. Ctrl-C stops the run.
    #[pyfunction]
    fn run<'py>(
        py: Python<'py>,
        netlist: &Bound<'py, PyAny>,
        options: &Bound<'py, PyAny>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let netlist: ::sisim::Netlist =
            pythonize::depythonize(netlist).map_err(|e| PyValueError::new_err(e.to_string()))?;
        let options: ::sisim::Options =
            pythonize::depythonize(options).map_err(|e| PyValueError::new_err(e.to_string()))?;
        let mut signal = None;
        let out =
            py.detach(|| {
                ::sisim::run(&netlist, &options, &mut || match Python::attach(|py| {
                    py.check_signals()
                }) {
                    Ok(()) => false,
                    Err(e) => {
                        signal = Some(e);
                        true
                    }
                })
            });
        if let Some(e) = signal {
            return Err(e);
        }
        let out = out.map_err(|e| PyRuntimeError::new_err(e.0))?;
        let bytes = |v: &[f64]| -> Vec<u8> { v.iter().flat_map(|x| x.to_le_bytes()).collect() };
        let d = PyDict::new(py);
        d.set_item("time", PyBytes::new(py, &bytes(&out.time)))?;
        d.set_item("data", PyBytes::new(py, &bytes(&out.data)))?;
        let s = PyDict::new(py);
        let st = &out.stats;
        s.set_item("steps", st.steps)?;
        s.set_item("newton", st.newton)?;
        s.set_item("newton_max", st.newton_max)?;
        s.set_item("nonconverged", st.nonconverged)?;
        s.set_item("dc_iterations", st.dc_iterations)?;
        s.set_item("pieces", st.pieces)?;
        s.set_item("largest_piece", st.largest_piece)?;
        s.set_item("seconds", st.seconds)?;
        d.set_item("stats", s)?;
        Ok(d)
    }
}
