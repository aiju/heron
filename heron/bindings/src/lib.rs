//! The Python bindings for the Rust engines (RFC 0015), as the extension
//! module `heron._native`. Python code uses it as `heron.native`, which
//! builds it first if needed.

use pyo3::prelude::*;

#[pymodule(name = "_native")]
mod native {
    use super::*;

    /// The bindings crate's version.
    #[pyfunction]
    fn version() -> &'static str {
        env!("CARGO_PKG_VERSION")
    }

    /// The chip-level simulator (infra/hwsim).
    #[pymodule]
    mod hwsim {
        use std::collections::HashMap;

        use pyo3::exceptions::PyValueError;
        use pyo3::prelude::*;
        use pyo3::types::PyBytes;

        /// Run a machine: `netlist` as Netlist.export() makes it, `config`
        /// as in infra/hwsim/src/machine.rs (a machine module's CONFIG and
        /// the run's settings), `roms` the ROM images by chip reference,
        /// `ram` the RAM image. Returns the outcome as a dict. Ctrl-C stops
        /// the run.
        #[pyfunction]
        #[pyo3(signature = (netlist, config, roms, ram=None))]
        fn run<'py>(
            py: Python<'py>,
            netlist: &Bound<'py, PyAny>,
            config: &Bound<'py, PyAny>,
            roms: HashMap<String, Bound<'py, PyBytes>>,
            ram: Option<Bound<'py, PyBytes>>,
        ) -> PyResult<Bound<'py, PyAny>> {
            let netlist: ::hwsim::Netlist = pythonize::depythonize(netlist)?;
            let config: ::hwsim::Config = pythonize::depythonize(config)?;
            let roms: HashMap<String, Vec<u8>> = roms
                .into_iter()
                .map(|(k, v)| (k, v.as_bytes().to_vec()))
                .collect();
            let ram = ram.map(|r| r.as_bytes().to_vec());
            let mut signal = None;
            let outcome =
                py.detach(|| {
                    ::hwsim::run(&netlist, &config, &roms, ram.as_deref(), &mut || {
                        match Python::attach(|py| py.check_signals()) {
                            Ok(()) => false,
                            Err(e) => {
                                signal = Some(e);
                                true
                            }
                        }
                    })
                });
            if let Some(e) = signal {
                return Err(e);
            }
            let outcome = outcome.map_err(|e| PyValueError::new_err(e.0))?;
            Ok(pythonize::pythonize(py, &outcome)?)
        }
    }
}
