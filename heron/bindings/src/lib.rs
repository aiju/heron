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
}
