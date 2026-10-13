//! Lines and tokens: comments, the lexer and operand splitting.

use std::fmt;

use super::AsmError;

/// A token. A string is its bytes: UTF-8 for the characters as written,
/// and the byte itself for an escape.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Tok {
    Num(i64),
    Id(String),
    Str(Vec<u8>),
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
}

/// A token as it would be written.
impl fmt::Display for Tok {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            Tok::Num(v) => write!(f, "{v}"),
            Tok::Id(s) => write!(f, "{s}"),
            Tok::Op(s) => write!(f, "{s}"),
            Tok::Str(b) => write!(f, "\"{}\"", b.escape_ascii()),
        }
    }
}

const OPS: [&str; 19] = [
    "-", "+", "*", "/", "%", "&", "|", "^", "~", "!", "(", ")", "[", "]", ",", "#", ":", "=", "$",
];

fn escape(c: char) -> Option<u8> {
    Some(match c {
        'n' => b'\n',
        'r' => b'\r',
        't' => b'\t',
        '0' => 0,
        '\\' => b'\\',
        '\'' => b'\'',
        '"' => b'"',
        'e' => 0x1B,
        _ => return None,
    })
}

/// The escape whose backslash is at `s[i]` (`\n`, `\x41`, ...): the byte,
/// and where the escape ends.
fn escape_at(s: &[char], i: usize) -> Result<(u8, usize), AsmError> {
    match s.get(i + 1) {
        Some('x') => {
            let n = s[i + 2..]
                .iter()
                .take(2)
                .take_while(|c| c.is_ascii_hexdigit())
                .count();
            let hex: String = s[i + 2..i + 2 + n].iter().collect();
            let v =
                u8::from_str_radix(&hex, 16).map_err(|_| AsmError::new("\\x needs hex digits"))?;
            Ok((v, i + 2 + n))
        }
        Some(&c) => escape(c)
            .map(|v| (v, i + 2))
            .ok_or_else(|| AsmError::new(format!("unknown escape \\{c}"))),
        None => Err(AsmError::new("unterminated escape")),
    }
}

/// A string literal starting at `s[pos]`: its bytes, and where it ends.
fn string(s: &[char], pos: usize) -> Result<(Vec<u8>, usize), AsmError> {
    let mut out = Vec::new();
    let mut i = pos + 1;
    loop {
        match s.get(i) {
            None => return Err(AsmError::new("unterminated string")),
            Some('"') => return Ok((out, i + 1)),
            Some('\\') => {
                let (b, next) = escape_at(s, i)?;
                out.push(b);
                i = next;
            }
            Some(c) => {
                out.extend_from_slice(c.encode_utf8(&mut [0; 4]).as_bytes());
                i += 1;
            }
        }
    }
}

/// A character literal starting at `s[pos]`: its value (the code point, or
/// the escape's byte), and where it ends.
fn character(s: &[char], pos: usize) -> Result<(i64, usize), AsmError> {
    let (v, end) = match s.get(pos + 1) {
        Some('\\') => escape_at(s, pos + 1).map(|(b, end)| (b as i64, end))?,
        Some(&c) if c != '\'' => (c as i64, pos + 2),
        _ => return Err(AsmError::new("empty character literal")),
    };
    if s.get(end) != Some(&'\'') {
        return Err(AsmError::new("a character literal holds one character"));
    }
    Ok((v, end + 1))
}

fn number(text: &str) -> Result<i64, AsmError> {
    let v = text.replace('_', "").to_ascii_lowercase();
    let (digits, radix) = if let Some(d) = v.strip_prefix("0x") {
        (d, 16)
    } else if let Some(d) = v.strip_prefix("0b") {
        (d, 2)
    } else {
        (v.as_str(), 10)
    };
    if digits.is_empty() || !digits.chars().all(|c| c.is_digit(radix)) {
        return Err(AsmError::new(format!("bad number {text}")));
    }
    i64::from_str_radix(digits, radix)
        .map_err(|_| AsmError::new(format!("number {text} is too large")))
}

/// One line (comment stripped) as tokens.
pub fn tokenize(text: &str) -> Result<Vec<Tok>, AsmError> {
    let s: Vec<char> = text.chars().collect();
    let word = |c: char| c.is_ascii_alphanumeric() || c == '_' || c == '.';
    let mut toks = Vec::new();
    let mut pos = 0;
    while pos < s.len() {
        let c = s[pos];
        let start = pos;
        if c.is_whitespace() {
            pos += 1;
        } else if c == '"' {
            let (b, end) = string(&s, pos)?;
            toks.push(Tok::Str(b));
            pos = end;
        } else if c == '\'' {
            let (v, end) = character(&s, pos)?;
            toks.push(Tok::Num(v));
            pos = end;
        } else if c.is_ascii_digit() {
            while pos < s.len() && word(s[pos]) {
                pos += 1;
            }
            toks.push(Tok::Num(number(&s[start..pos].iter().collect::<String>())?));
        } else if word(c) {
            while pos < s.len() && word(s[pos]) {
                pos += 1;
            }
            toks.push(Tok::Id(s[start..pos].iter().collect()));
        } else if (c == '<' || c == '>') && s.get(pos + 1) == Some(&c) {
            toks.push(Tok::Op(if c == '<' { "<<" } else { ">>" }));
            pos += 2;
        } else if let Some(op) = OPS.iter().find(|o| o.starts_with(c)) {
            toks.push(Tok::Op(op));
            pos += 1;
        } else {
            return Err(AsmError::new(format!("unexpected character {c:?}")));
        }
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

    fn err(s: &str) -> String {
        tokenize(s).unwrap_err().msg
    }

    #[test]
    fn tokens() {
        let t = tokenize(r#"ld r1, [x + 0x1_0] 'a' "s\n" 0b101 1_000 << >>"#).unwrap();
        assert_eq!(t[0], Tok::Id("ld".into()));
        assert_eq!(t[5], Tok::Op("+"));
        assert_eq!(t[6], Tok::Num(16));
        assert_eq!(t[8], Tok::Num(97));
        assert_eq!(t[9], Tok::Str(b"s\n".to_vec()));
        assert_eq!(t[10..12], [Tok::Num(5), Tok::Num(1000)]);
        assert_eq!(
            tokenize(r"'\n' '\x41' 'é'").unwrap(),
            [Tok::Num(10), Tok::Num(0x41), Tok::Num(0xE9)]
        );
        assert_eq!(
            tokenize(r#""\x41é""#).unwrap(),
            [Tok::Str(vec![0x41, 0xC3, 0xA9])]
        );
        assert_eq!(tokenize(r#""a\"b""#).unwrap()[0].to_string(), r#""a\"b""#);
    }

    #[test]
    fn errors() {
        assert_eq!(err("a < b"), "unexpected character '<'");
        assert_eq!(err("@"), "unexpected character '@'");
        assert_eq!(err("0x"), "bad number 0x");
        assert_eq!(err("12ab"), "bad number 12ab");
        assert_eq!(
            err("0x1_0000_0000_0000_0000"),
            "number 0x1_0000_0000_0000_0000 is too large"
        );
        assert_eq!(err(r#""abc"#), "unterminated string");
        assert_eq!(err("'ab'"), "a character literal holds one character");
        assert_eq!(err("''"), "empty character literal");
        assert_eq!(err(r#""\q""#), r"unknown escape \q");
        assert_eq!(err(r#""\xg""#), r"\x needs hex digits");
    }

    #[test]
    fn lines() {
        assert_eq!(strip_comment("ld r1 ; x"), "ld r1 ");
        assert_eq!(strip_comment(r#".ascii ";" ; x"#), r#".ascii ";" "#);
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
