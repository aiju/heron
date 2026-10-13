//! Python's posixpath functions, as far as the assembler uses them: file
//! names in messages are relative to the working directory, as they were
//! when the assembler was Python.

fn cwd() -> String {
    std::env::current_dir()
        .map(|p| p.to_string_lossy().into_owned())
        .unwrap_or_else(|_| "/".to_string())
}

pub fn normpath(path: &str) -> String {
    if path.is_empty() {
        return ".".to_string();
    }
    let mut initial = usize::from(path.starts_with('/'));
    if path.starts_with("//") && !path.starts_with("///") {
        initial = 2;
    }
    let mut comps: Vec<&str> = Vec::new();
    for comp in path.split('/') {
        if comp.is_empty() || comp == "." {
            continue;
        }
        if comp != ".." || (initial == 0 && comps.is_empty()) || comps.last() == Some(&"..") {
            comps.push(comp);
        } else if !comps.is_empty() {
            comps.pop();
        }
    }
    let out = "/".repeat(initial) + &comps.join("/");
    if out.is_empty() { ".".to_string() } else { out }
}

pub fn abspath(path: &str) -> String {
    if path.starts_with('/') {
        normpath(path)
    } else {
        normpath(&join(&cwd(), path))
    }
}

/// `path` relative to the working directory.
pub fn relpath(path: &str) -> String {
    let start = abspath(".");
    let path = abspath(path);
    let s: Vec<&str> = start.split('/').filter(|x| !x.is_empty()).collect();
    let p: Vec<&str> = path.split('/').filter(|x| !x.is_empty()).collect();
    let common = s.iter().zip(&p).take_while(|(a, b)| a == b).count();
    let mut rel: Vec<&str> = vec![".."; s.len() - common];
    rel.extend(&p[common..]);
    if rel.is_empty() {
        ".".to_string()
    } else {
        rel.join("/")
    }
}

pub fn dirname(path: &str) -> String {
    let i = path.rfind('/').map_or(0, |i| i + 1);
    let head = &path[..i];
    if !head.is_empty() && !head.chars().all(|c| c == '/') {
        head.trim_end_matches('/').to_string()
    } else {
        head.to_string()
    }
}

pub fn join(a: &str, b: &str) -> String {
    if b.starts_with('/') {
        b.to_string()
    } else if a.is_empty() || a.ends_with('/') {
        format!("{a}{b}")
    } else {
        format!("{a}/{b}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paths() {
        assert_eq!(normpath("/a/./b/../c//d/"), "/a/c/d");
        assert_eq!(normpath("../x"), "../x");
        assert_eq!(normpath("//a"), "//a");
        assert_eq!(dirname("/a/b/c.s"), "/a/b");
        assert_eq!(dirname("/c.s"), "/");
        assert_eq!(join("/a", "b.s"), "/a/b.s");
        assert_eq!(join("/a", "/b.s"), "/b.s");
        let here = abspath("x/y.s");
        assert_eq!(relpath(&here), "x/y.s");
        assert!(relpath("/").starts_with(".."));
    }
}
