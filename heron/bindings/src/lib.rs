//! The Python bindings for the Rust engines (RFC 0015), as the extension
//! module `heron._native`. Python code uses it as `heron.native`, which
//! builds it first if needed. Each engine is a submodule.

use pyo3::prelude::*;

mod py_fen;
mod py_hwsim;
mod py_pcbroute;
mod py_sisim;
mod py_toolchain;
mod py_v1;
mod py_v2;

#[pymodule(name = "_native")]
mod native {
    use super::*;

    #[pymodule_export]
    use crate::py_fen::fen;
    #[pymodule_export]
    use crate::py_hwsim::hwsim;
    #[pymodule_export]
    use crate::py_pcbroute::pcbroute;
    #[pymodule_export]
    use crate::py_sisim::sisim;
    #[pymodule_export]
    use crate::py_toolchain::toolchain;
    #[pymodule_export]
    use crate::py_v1::v1;
    #[pymodule_export]
    use crate::py_v2::v2;

    /// The bindings crate's version.
    #[pyfunction]
    fn version() -> &'static str {
        env!("CARGO_PKG_VERSION")
    }
}
