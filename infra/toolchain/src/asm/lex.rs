//! Lines and tokens: comments, the lexer, operand splitting, and the bits
//! of Python's string handling the assembler's behaviour is defined by
//! (`str.splitlines`, `str.isspace`, `repr`).

use super::AsmError;

/// A token. Strings are code points, as written (escapes resolved).
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Tok {
    Num(i64),
    Id(String),
    Str(Vec<u32>),
    Op(&'static str),
}

impl Tok {
    pub fn is_op(&self, op: &str) -> bool {
        matches!(self, Tok::Op(o) if *o == op)
    }

    pub fn id(&self) -> Option<&str> {
        match self {
            Tok::Id(s) => Some(s),
            _ => None,
        }
    }

    /// The token's value as Python's repr shows it, for messages.
    pub fn repr(&self) -> String {
        match self {
            Tok::Num(v) => v.to_string(),
            Tok::Id(s) => py_repr(s),
            Tok::Op(s) => py_repr(s),
            Tok::Str(cs) => {
                let items: Vec<String> = cs.iter().map(|c| c.to_string()).collect();
                format!("[{}]", items.join(", "))
            }
        }
    }
}

const OPS: [&str; 21] = [
    "-", "+", "*", "/", "%", "&", "|", "^", "~", "!", "(", ")", "[", "]", ",", "#", ":", "=", "$",
    "<<", ">>",
];

/// Python's str.isspace().
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\x1c'..='\x1f').contains(&c)
}

/// Python's str.splitlines().
pub fn split_lines(text: &str) -> Vec<&str> {
    let mut out = Vec::new();
    let mut start = 0;
    let mut it = text.char_indices().peekable();
    while let Some((i, c)) = it.next() {
        let brk = matches!(
            c,
            '\n' | '\r'
                | '\x0b'
                | '\x0c'
                | '\x1c'
                | '\x1d'
                | '\x1e'
                | '\u{85}'
                | '\u{2028}'
                | '\u{2029}'
        );
        if brk {
            out.push(&text[start..i]);
            let mut end = i + c.len_utf8();
            if c == '\r'
                && let Some(&(_, '\n')) = it.peek()
            {
                it.next();
                end += 1;
            }
            start = end;
        }
    }
    if start < text.len() {
        out.push(&text[start..]);
    }
    out
}

/// The format characters (category Cf), which Python doesn't print.
const FORMAT: [(u32, u32); 21] = [
    (0xAD, 0xAD),
    (0x600, 0x605),
    (0x61C, 0x61C),
    (0x6DD, 0x6DD),
    (0x70F, 0x70F),
    (0x890, 0x891),
    (0x8E2, 0x8E2),
    (0x180E, 0x180E),
    (0x200B, 0x200F),
    (0x202A, 0x202E),
    (0x2060, 0x2064),
    (0x2066, 0x206F),
    (0xFEFF, 0xFEFF),
    (0xFFF9, 0xFFFB),
    (0x110BD, 0x110BD),
    (0x110CD, 0x110CD),
    (0x13430, 0x1343F),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0001, 0xE0001),
    (0xE0020, 0xE007F),
];

/// Python's str.isprintable() for one character (unassigned code points
/// aside, which this counts as printable).
fn is_printable(c: char) -> bool {
    let u = c as u32;
    if c == ' ' {
        return true;
    }
    if c.is_control() || is_space(c) {
        return false;
    }
    let private = (0xE000..=0xF8FF).contains(&u) || u >= 0xF0000;
    !private && !FORMAT.iter().any(|&(a, b)| (a..=b).contains(&u))
}

/// Python's repr() of a string.
pub fn py_repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::new();
    out.push(quote);
    for c in s.chars() {
        let u = c as u32;
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if is_printable(c) => out.push(c),
            _ if u < 0x100 => out.push_str(&format!("\\x{u:02x}")),
            _ if u < 0x10000 => out.push_str(&format!("\\u{u:04x}")),
            _ => out.push_str(&format!("\\U{u:08x}")),
        }
    }
    out.push(quote);
    out
}

fn escape(c: char) -> Option<u32> {
    Some(match c {
        'n' => 10,
        'r' => 13,
        't' => 9,
        '0' => 0,
        '\\' => 92,
        '\'' => 39,
        '"' => 34,
        'e' => 27,
        _ => return None,
    })
}

/// The code points of a string or character literal's body.
fn unescape(body: &[char]) -> Result<Vec<u32>, AsmError> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < body.len() {
        let c = body[i];
        if c == '\\' && i + 1 < body.len() {
            let next = body[i + 1];
            if next == 'x' {
                let hex: String = body[(i + 2).min(body.len())..(i + 4).min(body.len())]
                    .iter()
                    .collect();
                match u32::from_str_radix(&hex, 16) {
                    Ok(v) if !hex.is_empty() && hex.chars().all(|c| c.is_ascii_hexdigit()) => {
                        out.push(v)
                    }
                    _ => return Err(AsmError::new(format!("bad escape \\x{hex}"))),
                }
                i += 4;
                continue;
            }
            match escape(next) {
                Some(v) => out.push(v),
                None => return Err(AsmError::new(format!("unknown escape \\{next}"))),
            }
            i += 2;
        } else {
            out.push(c as u32);
            i += 1;
        }
    }
    Ok(out)
}

/// The length of a quoted literal at `pos` (`"..."`, or `'c'` with exactly
/// one character or escape), or None.
fn literal_len(s: &[char], pos: usize) -> Option<usize> {
    let q = s[pos];
    let mut i = pos + 1;
    if q == '"' {
        while i < s.len() {
            match s[i] {
                '"' => return Some(i + 1 - pos),
                '\\' if i + 1 < s.len() => i += 2,
                '\\' => return None,
                _ => i += 1,
            }
        }
        return None;
    }
    // 'c' or '\c'
    match s.get(i) {
        Some('\'') | None => return None,
        Some('\\') => {
            s.get(i + 1)?;
            i += 2;
        }
        Some(_) => i += 1,
    }
    (s.get(i) == Some(&'\'')).then_some(i + 1 - pos)
}

fn number(text: &str) -> Result<i64, AsmError> {
    let v: String = text.chars().filter(|&c| c != '_').collect();
    let low = v.to_ascii_lowercase();
    let (digits, radix) = if let Some(d) = low.strip_prefix("0x") {
        (d, 16)
    } else if let Some(d) = low.strip_prefix("0b") {
        (d, 2)
    } else {
        (low.as_str(), 10)
    };
    if digits.is_empty() {
        return Err(AsmError::new(format!("bad number {text}")));
    }
    i64::from_str_radix(digits, radix)
        .map_err(|_| AsmError::new(format!("number {text} is too large")))
}

/// One line (comment stripped) as tokens.
pub fn tokenize(text: &str) -> Result<Vec<Tok>, AsmError> {
    let s: Vec<char> = text.chars().collect();
    let mut toks = Vec::new();
    let mut pos = 0;
    while pos < s.len() {
        let c = s[pos];
        if is_space(c) {
            while pos < s.len() && is_space(s[pos]) {
                pos += 1;
            }
            continue;
        }
        if c == '"' || c == '\'' {
            if let Some(n) = literal_len(&s, pos) {
                let body = unescape(&s[pos + 1..pos + n - 1])?;
                toks.push(if c == '"' {
                    Tok::Str(body)
                } else {
                    Tok::Num(body[0] as i64)
                });
                pos += n;
                continue;
            }
        } else if c.is_ascii_digit() {
            let start = pos;
            let radix = match s.get(pos + 1) {
                Some('x' | 'X') if c == '0' => 16,
                Some('b' | 'B') if c == '0' => 2,
                _ => 10,
            };
            let ok = |ch: char| match radix {
                16 => ch.is_ascii_hexdigit() || ch == '_',
                2 => ch == '0' || ch == '1' || ch == '_',
                _ => ch.is_ascii_digit() || ch == '_',
            };
            if radix != 10 && s.get(pos + 2).is_some_and(|&ch| ok(ch)) {
                pos += 2;
            } else if radix != 10 {
                // "0x" without digits: the number is the 0
                toks.push(Tok::Num(0));
                pos += 1;
                continue;
            }
            while pos < s.len() && ok(s[pos]) {
                pos += 1;
            }
            let text: String = s[start..pos].iter().collect();
            toks.push(Tok::Num(number(&text)?));
            continue;
        } else if c.is_ascii_alphabetic() || c == '_' || c == '.' {
            let start = pos;
            while pos < s.len()
                && (s[pos].is_ascii_alphanumeric() || s[pos] == '_' || s[pos] == '.')
            {
                pos += 1;
            }
            toks.push(Tok::Id(s[start..pos].iter().collect()));
            continue;
        } else if (c == '<' || c == '>') && s.get(pos + 1) == Some(&c) {
            toks.push(Tok::Op(if c == '<' { "<<" } else { ">>" }));
            pos += 2;
            continue;
        } else if let Some(op) = OPS.iter().find(|o| o.len() == 1 && o.starts_with(c)) {
            toks.push(Tok::Op(op));
            pos += 1;
            continue;
        }
        return Err(AsmError::new(format!(
            "unexpected character {}",
            py_repr(&c.to_string())
        )));
    }
    Ok(toks)
}

/// A line without its ';' comment (one inside a literal doesn't count).
pub fn strip_comment(line: &str) -> &str {
    let mut quote = None;
    let mut it = line.char_indices();
    while let Some((i, c)) = it.next() {
        if let Some(q) = quote {
            if c == '\\' {
                it.next();
                continue;
            }
            if c == q {
                quote = None;
            }
        } else if c == '"' || c == '\'' {
            quote = Some(c);
        } else if c == ';' {
            return &line[..i];
        }
    }
    line
}

/// Split tokens on the commas outside () and [].
pub fn split_operands(toks: &[Tok]) -> Vec<Vec<Tok>> {
    let mut out = Vec::new();
    let mut cur = Vec::new();
    let mut depth = 0i32;
    for t in toks {
        if t.is_op("(") || t.is_op("[") {
            depth += 1;
        } else if t.is_op(")") || t.is_op("]") {
            depth -= 1;
        }
        if t.is_op(",") && depth == 0 {
            out.push(std::mem::take(&mut cur));
        } else {
            cur.push(t.clone());
        }
    }
    if !cur.is_empty() || !out.is_empty() {
        out.push(cur);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens() {
        let t = tokenize("ld r1, [x + 0x1_0] 'a' \"s\\n\" 0b101 1_000 << >>").unwrap();
        assert_eq!(t[0], Tok::Id("ld".into()));
        assert_eq!(t[5], Tok::Op("+"));
        assert_eq!(t[6], Tok::Num(16));
        assert!(tokenize("a < b").is_err());
        assert_eq!(
            tokenize("'a' '\\n'").unwrap(),
            vec![Tok::Num(97), Tok::Num(10)]
        );
        assert_eq!(
            tokenize("0x").unwrap(),
            vec![Tok::Num(0), Tok::Id("x".into())]
        );
        assert_eq!(tokenize("\"\\x41\"").unwrap(), vec![Tok::Str(vec![0x41])]);
        assert_eq!(tokenize("@").unwrap_err().msg, "unexpected character '@'");
        assert_eq!(tokenize("'").unwrap_err().msg, "unexpected character \"'\"");
        assert_eq!(py_repr("\u{200b}\u{e9}\x7f\\"), "'\\u200b\u{e9}\\x7f\\\\'");
    }

    #[test]
    fn lines() {
        assert_eq!(
            split_lines("a\r\nb\rc\n\nd\n"),
            vec!["a", "b", "c", "", "d"]
        );
        assert_eq!(strip_comment("ld r1 ; x"), "ld r1 ");
        assert_eq!(strip_comment(".ascii \";\" ; x"), ".ascii \";\" ");
        assert_eq!(strip_comment(".byte ';'"), ".byte ';'");
    }

    #[test]
    fn operands() {
        let t = tokenize("r1, [r2 + f(1, 2)], 3,").unwrap();
        let ops = split_operands(&t);
        assert_eq!(ops.len(), 4);
        assert!(ops[3].is_empty());
        assert!(split_operands(&[]).is_empty());
    }
}
