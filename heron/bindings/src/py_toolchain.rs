//! The toolchain (infra/toolchain) for Python: heron.native.toolchain.
//! infra/obj.py, infra/link.py and infra/asm.py keep their classes, and
//! call these to read and write files, to link and to assemble. The
//! assembler finds an ISA's encoder by its name; the ISAs that have one
//! are draft 1a and 1b (studies/v1_isa/isa).
//!
//! An object file crosses as a tuple (isa, flags, entry, sections,
//! symbols, relocs), with sections (name, flags, addr, size, align, data,
//! code), symbols (name, section, value, flags) and relocations (section,
//! offset, kind, symbol, addend).

use pyo3::prelude::*;

pyo3::create_exception!(
    toolchain,
    ObjError,
    pyo3::exceptions::PyException,
    "Not a valid object file or library."
);
pyo3::create_exception!(
    toolchain,
    AsmFailed,
    pyo3::exceptions::PyException,
    "Assembly failed: args are (message, (file, line) or None)."
);
pyo3::create_exception!(
    toolchain,
    LinkFailed,
    pyo3::exceptions::PyException,
    "The link failed: args[0] lists why."
);

#[pymodule]
pub mod toolchain {
    use pyo3::exceptions::{PyOSError, PyValueError};
    use pyo3::prelude::*;
    use pyo3::types::{PyBytes, PyDict};
    use toolchain::asm::{self, AsmError, Assembler as Engine};
    use toolchain::link::Linker;
    use toolchain::obj::{self, ObjectFile, Reloc, Section, Symbol};

    #[pymodule_export]
    use super::{AsmFailed, LinkFailed, ObjError};

    type PySection = (String, u32, u32, u32, u32, Vec<u8>, u32);
    type PySymbol = (String, u32, u32, u32);
    type PyReloc = (u32, u32, u32, u32, i32);
    type PyObject = (
        String,
        u32,
        u32,
        Vec<PySection>,
        Vec<PySymbol>,
        Vec<PyReloc>,
    );

    fn to_py(o: ObjectFile) -> PyObject {
        let secs = o
            .sections
            .into_iter()
            .map(|s| (s.name, s.flags, s.addr, s.size, s.align, s.data, s.code))
            .collect();
        let syms = o
            .symbols
            .into_iter()
            .map(|s| (s.name, s.section, s.value, s.flags))
            .collect();
        let rels = o
            .relocs
            .into_iter()
            .map(|r| (r.section, r.offset, r.kind, r.symbol, r.addend))
            .collect();
        (o.isa, o.flags, o.entry, secs, syms, rels)
    }

    fn from_py(o: PyObject, name: &str) -> ObjectFile {
        let (isa, flags, entry, secs, syms, rels) = o;
        let mut out = ObjectFile::new(&isa, flags, entry, name);
        out.sections = secs
            .into_iter()
            .map(|(name, flags, addr, size, align, data, code)| Section {
                name,
                flags,
                addr,
                size,
                align,
                data,
                code,
            })
            .collect();
        out.symbols = syms
            .into_iter()
            .map(|(name, section, value, flags)| Symbol {
                name,
                section,
                value,
                flags,
            })
            .collect();
        out.relocs = rels
            .into_iter()
            .map(|(section, offset, kind, symbol, addend)| Reloc {
                section,
                offset,
                kind,
                symbol,
                addend,
            })
            .collect();
        out
    }

    fn read(data: &[u8], name: &str) -> PyResult<ObjectFile> {
        ObjectFile::from_bytes(data, name).map_err(|e| ObjError::new_err(e.0))
    }

    /// An object file's contents from its bytes; `name` is for messages.
    #[pyfunction]
    fn read_object(data: &[u8], name: &str) -> PyResult<PyObject> {
        Ok(to_py(read(data, name)?))
    }

    /// An object file's bytes.
    #[pyfunction]
    fn write_object<'py>(py: Python<'py>, o: PyObject) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &from_py(o, "").to_bytes())
    }

    /// The members of a library, from its bytes: [(name, object file)].
    #[pyfunction]
    fn read_archive(data: &[u8], path: &str) -> PyResult<Vec<(String, PyObject)>> {
        let members = obj::read_archive(data, path).map_err(|e| ObjError::new_err(e.0))?;
        Ok(members.into_iter().map(|(n, o)| (n, to_py(o))).collect())
    }

    /// A library's bytes from its members: [(name, object file bytes)].
    #[pyfunction]
    fn write_archive<'py>(py: Python<'py>, members: Vec<(String, Vec<u8>)>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &obj::archive_of(&members))
    }

    /// The bytes to store for a relocation; ValueError if the value doesn't
    /// fit.
    #[pyfunction]
    fn reloc_value<'py>(
        py: Python<'py>,
        kind: u32,
        s: i64,
        a: i64,
        p: i64,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let data = obj::reloc_value(kind, s, a, p).map_err(PyValueError::new_err)?;
        Ok(PyBytes::new(py, &data))
    }

    /// Link object files (each (name, bytes)) and libraries (each
    /// [(member name, object name, bytes)]). Returns a dict: exe (the
    /// executable's bytes), symbols [(name, address)] in the order they
    /// were defined, labels [(name, address)] by address, contents
    /// [(address, bytes)], code, end, map. LinkFailed if it can't.
    #[pyfunction]
    #[pyo3(signature = (objects, libraries, isa=None, base=None, gc=true, entry=None, mem_top=0x10000))]
    #[allow(clippy::too_many_arguments)]
    fn link<'py>(
        py: Python<'py>,
        objects: Vec<(String, Vec<u8>)>,
        libraries: Vec<Vec<(String, String, Vec<u8>)>>,
        isa: Option<&str>,
        base: Option<u64>,
        gc: bool,
        entry: Option<&str>,
        mem_top: u64,
    ) -> PyResult<Bound<'py, pyo3::types::PyDict>> {
        let fail = |e: toolchain::link::LinkError| LinkFailed::new_err(e.0);
        let mut ln = Linker::new(isa, base, gc, entry, mem_top);
        for (name, data) in objects {
            ln.add(read(&data, &name)?).map_err(fail)?;
        }
        for lib in libraries {
            let mut members = Vec::new();
            for (member, name, data) in lib {
                members.push((member, read(&data, &name)?));
            }
            ln.add_library(members).map_err(fail)?;
        }
        let out = ln.link().map_err(fail)?;
        let d = pyo3::types::PyDict::new(py);
        d.set_item("exe", PyBytes::new(py, &out.exe.to_bytes()))?;
        d.set_item("isa", out.exe.isa)?;
        d.set_item("symbols", out.symbols)?;
        d.set_item("labels", out.labels)?;
        let contents: Vec<(u64, Bound<'py, PyBytes>)> = out
            .contents
            .iter()
            .map(|(a, b)| (*a, PyBytes::new(py, b)))
            .collect();
        d.set_item("contents", contents)?;
        d.set_item("code", out.code)?;
        d.set_item("end", out.end)?;
        d.set_item("map", out.map)?;
        Ok(d)
    }

    fn asm_err(e: AsmError) -> PyErr {
        AsmFailed::new_err((e.msg, e.at.map(|(file, line)| (file.to_string(), line))))
    }

    /// An assembler for one ISA (by name), making an image or, with
    /// `relocatable`, an object file. AsmFailed for errors in the source,
    /// OSError for files that can't be read.
    #[pyclass(module = "heron._native.toolchain")]
    struct Assembler {
        a: Engine,
    }

    #[pymethods]
    impl Assembler {
        #[new]
        fn new(isa: &str, relocatable: bool) -> PyResult<Self> {
            let enc = v1_isa::asm::encoder(isa)
                .ok_or_else(|| PyValueError::new_err(format!("no assembler for ISA {isa}")))?;
            Ok(Assembler {
                a: Engine::new(enc, relocatable),
            })
        }

        /// Read a source file (or take its text); `path` names it in
        /// messages and is where .include looks.
        #[pyo3(signature = (path, text=None))]
        fn load(&mut self, py: Python<'_>, path: &str, text: Option<&str>) -> PyResult<()> {
            match self.a.load(path, text) {
                Ok(()) => Ok(()),
                Err(asm::Error::Asm(e)) => Err(asm_err(e)),
                Err(asm::Error::Io { path, err }) => Err(match err.raw_os_error() {
                    Some(errno) => {
                        let strerror = py.import("os")?.call_method1("strerror", (errno,))?;
                        PyOSError::new_err((errno, strerror.unbind(), path))
                    }
                    None => PyOSError::new_err(format!("{path}: {err}")),
                }),
            }
        }

        /// Assemble an image: a dict with mem [(address, bytes)] in runs of
        /// consecutive bytes, and symbols [(name, value)] in the order they
        /// were defined.
        fn assemble<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            let img = self.a.assemble().map_err(asm_err)?;
            let mut runs: Vec<(i64, Vec<u8>)> = Vec::new();
            for (&a, &b) in &img.mem {
                match runs.last_mut() {
                    Some((start, bytes)) if *start + bytes.len() as i64 == a => bytes.push(b),
                    _ => runs.push((a, vec![b])),
                }
            }
            let d = PyDict::new(py);
            let mem: Vec<(i64, Bound<'py, PyBytes>)> = runs
                .iter()
                .map(|(a, b)| (*a, PyBytes::new(py, b)))
                .collect();
            d.set_item("mem", mem)?;
            d.set_item("symbols", img.symbols)?;
            Ok(d)
        }

        /// Assemble an object file; returns its contents, as read_object does.
        fn assemble_object(&mut self, name: &str) -> PyResult<PyObject> {
            Ok(to_py(self.a.assemble_object(name).map_err(asm_err)?))
        }

        /// The statements: (kind, name, label, addr, size, words, data,
        /// (file, line), text), with name None for a label and label None
        /// for the others.
        #[allow(clippy::type_complexity)]
        fn stmts<'py>(
            &self,
            py: Python<'py>,
        ) -> PyResult<
            Vec<(
                &'static str,
                Option<String>,
                Option<String>,
                i64,
                i64,
                Vec<u16>,
                Bound<'py, PyBytes>,
                (String, usize),
                String,
            )>,
        > {
            Ok(self
                .a
                .stmts()
                .iter()
                .map(|st| {
                    let label = st.kind == asm::Kind::Label;
                    (
                        st.kind.name(),
                        (!label).then(|| st.name.clone()),
                        label.then(|| st.label.clone()),
                        st.addr,
                        st.size,
                        st.words.clone(),
                        PyBytes::new(py, &st.data),
                        (st.at.0.to_string(), st.at.1),
                        st.text.clone(),
                    )
                })
                .collect())
        }

        /// The listing, as text.
        fn listing(&self) -> String {
            self.a.listing()
        }

        #[getter]
        fn warnings(&self) -> Vec<String> {
            self.a.warnings.clone()
        }

        /// The symbols, (name, value) in the order they were defined.
        #[getter]
        fn symbols(&self) -> Vec<(String, i64)> {
            self.a.symbols().to_vec()
        }
    }
}
