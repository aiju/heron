//! The draft 1b hardware's register-transfer model (studies/v1b_hw/rtl)
//! for Python: heron.native.v1b_rtl. studies/v1b_hw/rtl_native.py makes
//! the ROM from ucode.py's tables.

use pyo3::prelude::*;

#[pymodule]
pub mod v1b_rtl {
    use std::sync::Arc;

    use pyo3::exceptions::PyValueError;
    use pyo3::prelude::*;
    use pyo3::types::PyBytes;

    use v1b_rtl::{Rom as Engine, System};

    /// The microcode and decode ROMs: `names` the control fields, `rows`
    /// the distinct microinstructions as lists of field values, `index`
    /// the row at each of the 65536 ROM addresses, `decode` the decode
    /// ROM, `illegal` the first parcels it sends to the illegal-instruction
    /// routine, `irq_entry` the interrupt entry routine's address.
    #[pyclass(frozen)]
    pub struct Rom {
        pub rom: Arc<Engine>,
    }

    #[pymethods]
    impl Rom {
        #[new]
        fn new(
            names: Vec<String>,
            rows: Vec<Vec<u32>>,
            index: Vec<u32>,
            decode: Vec<u32>,
            illegal: Vec<bool>,
            irq_entry: u32,
        ) -> PyResult<Rom> {
            let rom = Engine::new(&names, &rows, &index, decode, illegal, irq_entry)
                .map_err(PyValueError::new_err)?;
            Ok(Rom { rom: Arc::new(rom) })
        }
    }

    /// The whole machine of rtl.py: `image` RAM from address 0, `inp` the
    /// console input.
    #[pyclass]
    struct Machine {
        s: System,
    }

    #[pymethods]
    impl Machine {
        #[new]
        #[pyo3(signature = (rom, image, inp=b"".as_slice()))]
        fn new(rom: &Rom, image: &[u8], inp: &[u8]) -> Machine {
            Machine {
                s: System::new(rom.rom.clone(), image, inp),
            }
        }

        /// Run until HALT; more than max_cycles is an error. Ctrl-C stops it.
        #[pyo3(signature = (max_cycles=50_000_000))]
        fn run(&mut self, py: Python<'_>, max_cycles: u64) -> PyResult<()> {
            let s = &mut self.s;
            py.detach(|| s.run(max_cycles))
                .map_err(PyValueError::new_err)
        }

        /// Cycles since the reset routine's fetch.
        #[getter]
        fn cycles(&self) -> u64 {
            self.s.cpu.cycles
        }
        #[getter]
        fn halted(&self) -> bool {
            self.s.cpu.halted
        }
        /// r0-r15, HI and the scratch locations: the whole register file.
        #[getter]
        fn rf(&self) -> [u32; 32] {
            self.s.cpu.rf
        }
        #[getter]
        fn pc(&self) -> u32 {
            self.s.cpu.pc
        }
        /// The flags as (n, z, c, v, i).
        #[getter]
        fn flags(&self) -> (u32, u32, u32, u32, u32) {
            let c = &self.s.cpu;
            (c.n, c.z, c.c, c.v, c.i)
        }
        #[getter]
        fn mem<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.s.ram.mem)
        }
        #[getter]
        fn out<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
            PyBytes::new(py, &self.s.ram.dev.out)
        }
        /// {instruction address: cycles}, from each opcode fetch to the next.
        fn pc_cycles(&self) -> std::collections::HashMap<u32, u64> {
            self.s.pc_cycles.clone()
        }
    }
}
