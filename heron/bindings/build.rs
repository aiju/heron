fn main() {
    // macOS: leave the Python symbols to be found when the module is loaded.
    pyo3_build_config::add_extension_module_link_args();
}
