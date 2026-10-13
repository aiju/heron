//! Expressions: parsed into small trees, evaluated once symbols are known.

use std::collections::BTreeSet;

use super::AsmError;
use super::lex::Tok;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Func {
    /// The low byte.
    Lo,
    /// The high byte (of 16 bits).
    Hi,
    /// The low half of a 32-bit constant.
    Lo16,
    /// The high half of a 32-bit constant.
    Hi16,
}

impl Func {
    fn named(name: &str) -> Option<Func> {
        Some(match name {
            "lo" => Func::Lo,
            "hi" => Func::Hi,
            "lo16" => Func::Lo16,
            "hi16" => Func::Hi16,
            _ => return None,
        })
    }

    pub fn name(self) -> &'static str {
        match self {
            Func::Lo => "lo",
            Func::Hi => "hi",
            Func::Lo16 => "lo16",
            Func::Hi16 => "hi16",
        }
    }

    pub fn apply(self, x: i64) -> i64 {
        match self {
            Func::Lo => x & 0xFF,
            Func::Hi => (x >> 8) & 0xFF,
            Func::Lo16 => x & 0xFFFF,
            Func::Hi16 => (x >> 16) & 0xFFFF,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Expr {
    Num(i64),
    /// A symbol, local labels already qualified with their scope.
    Sym(String),
    /// `$`, the address of the statement.
    Pc,
    /// `-`, `~`, `+` or `!`.
    Un(&'static str, Box<Expr>),
    Bin(&'static str, Box<Expr>, Box<Expr>),
    Call(Func, Box<Expr>),
}

const PREC: [&[&str]; 6] = [
    &["|"],
    &["^"],
    &["&"],
    &["<<", ">>"],
    &["+", "-"],
    &["*", "/", "%"],
];

/// Deeper nesting, or longer expressions, are refused rather than risking
/// the stack.
const MAX_DEPTH: usize = 100;
const MAX_TOKENS: usize = 4000;

/// A local label (`.name`) belongs to the last global label before it.
pub fn mangle(name: &str, scope: Option<&str>) -> String {
    if name.starts_with('.') && name.len() > 1 {
        format!("{}{name}", scope.unwrap_or(""))
    } else {
        name.to_string()
    }
}

struct Parser<'a> {
    toks: &'a [Tok],
    i: usize,
    scope: Option<&'a str>,
    depth: usize,
}

impl Parser<'_> {
    fn peek(&self) -> Option<&Tok> {
        self.toks.get(self.i)
    }

    fn peek_op(&self, ops: &[&str]) -> Option<&'static str> {
        match self.peek() {
            Some(Tok::Op(o)) if ops.contains(o) => Some(o),
            _ => None,
        }
    }

    fn take(&mut self) -> Option<&Tok> {
        let t = self.toks.get(self.i);
        self.i += 1;
        t
    }

    fn nest(&mut self) -> Result<(), AsmError> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(AsmError::new("expression nested too deeply"));
        }
        Ok(())
    }

    fn binary(&mut self, level: usize) -> Result<Expr, AsmError> {
        if level == PREC.len() {
            return self.unary();
        }
        let mut left = self.binary(level + 1)?;
        while let Some(op) = self.peek_op(PREC[level]) {
            self.i += 1;
            let right = self.binary(level + 1)?;
            left = Expr::Bin(op, Box::new(left), Box::new(right));
        }
        Ok(left)
    }

    fn unary(&mut self) -> Result<Expr, AsmError> {
        if let Some(op) = self.peek_op(&["-", "~", "+", "!"]) {
            self.i += 1;
            self.nest()?;
            let e = self.unary()?;
            self.depth -= 1;
            return Ok(Expr::Un(op, Box::new(e)));
        }
        self.atom()
    }

    fn close(&mut self) -> Result<(), AsmError> {
        match self.take() {
            Some(t) if t.is_op(")") => Ok(()),
            _ => Err(AsmError::new("missing ')'")),
        }
    }

    fn atom(&mut self) -> Result<Expr, AsmError> {
        let scope = self.scope;
        let Some(t) = self.take().cloned() else {
            return Err(AsmError::new("expression expected"));
        };
        match t {
            Tok::Num(v) => Ok(Expr::Num(v)),
            Tok::Op("$") => Ok(Expr::Pc),
            Tok::Op("(") => {
                self.nest()?;
                let e = self.binary(0)?;
                self.close()?;
                self.depth -= 1;
                Ok(e)
            }
            Tok::Id(name) => {
                let low = name.to_ascii_lowercase();
                if let Some(f) = Func::named(&low)
                    && self.peek().is_some_and(|t| t.is_op("("))
                {
                    self.i += 1;
                    self.nest()?;
                    let e = self.binary(0)?;
                    self.close()?;
                    self.depth -= 1;
                    return Ok(Expr::Call(f, Box::new(e)));
                }
                Ok(Expr::Sym(mangle(&name, scope)))
            }
            t => Err(AsmError::new(format!("unexpected '{t}' in expression"))),
        }
    }
}

/// Parse a whole operand as an expression.
pub fn parse(toks: &[Tok], scope: Option<&str>) -> Result<Expr, AsmError> {
    if toks.len() > MAX_TOKENS {
        return Err(AsmError::new("expression too long"));
    }
    let mut p = Parser {
        toks,
        i: 0,
        scope,
        depth: 0,
    };
    let e = p.binary(0)?;
    if p.i != toks.len() {
        return Err(AsmError::new(format!(
            "junk after expression: '{}'",
            toks[p.i]
        )));
    }
    Ok(e)
}

/// Why an expression has no value.
#[derive(Debug)]
pub enum EvalError {
    /// A symbol that isn't defined (yet).
    Unresolved(String),
    Asm(AsmError),
}

impl From<AsmError> for EvalError {
    fn from(e: AsmError) -> Self {
        EvalError::Asm(e)
    }
}

fn overflow() -> AsmError {
    AsmError::new("arithmetic overflow")
}

pub fn unary(op: &str, x: i64) -> Result<i64, AsmError> {
    Ok(match op {
        "-" => x.checked_neg().ok_or_else(overflow)?,
        "~" => !x,
        "!" => (x == 0) as i64,
        _ => x,
    })
}

/// A binary operator on two numbers: `/` and `%` truncate towards zero,
/// `>>` is arithmetic, and a result that doesn't fit in 64 bits is an
/// error.
pub fn binary(op: &str, a: i64, b: i64) -> Result<i64, AsmError> {
    let shift = || u32::try_from(b).ok().filter(|&b| b < 64);
    let r = match op {
        "+" => a.checked_add(b),
        "-" => a.checked_sub(b),
        "*" => a.checked_mul(b),
        "/" | "%" if b == 0 => return Err(AsmError::new("division by zero")),
        "/" => a.checked_div(b),
        "%" => a.checked_rem(b),
        "<<" | ">>" if shift().is_none() => {
            return Err(AsmError::new(format!("shift count {b} out of range")));
        }
        "<<" => shift().map(|b| a << b).filter(|r| r >> b == a),
        ">>" => shift().map(|b| a >> b),
        "&" => Some(a & b),
        "|" => Some(a | b),
        "^" => Some(a ^ b),
        _ => return Err(AsmError::new(format!("bad operator {op}"))),
    };
    r.ok_or_else(overflow)
}

/// Evaluate with `lookup` giving the symbols' values and `pc` the value of `$`.
pub fn eval(e: &Expr, lookup: &dyn Fn(&str) -> Option<i64>, pc: i64) -> Result<i64, EvalError> {
    Ok(match e {
        Expr::Num(v) => *v,
        Expr::Pc => pc,
        Expr::Sym(name) => lookup(name).ok_or_else(|| EvalError::Unresolved(name.clone()))?,
        Expr::Un(op, x) => unary(op, eval(x, lookup, pc)?)?,
        Expr::Call(f, x) => f.apply(eval(x, lookup, pc)?),
        Expr::Bin(op, a, b) => {
            let a = eval(a, lookup, pc)?;
            let b = eval(b, lookup, pc)?;
            binary(op, a, b)?
        }
    })
}

/// The symbols an expression uses, sorted.
pub fn symbols_in(e: &Expr) -> BTreeSet<String> {
    let mut out = BTreeSet::new();
    fn walk(e: &Expr, out: &mut BTreeSet<String>) {
        match e {
            Expr::Sym(s) => {
                out.insert(s.clone());
            }
            Expr::Un(_, x) | Expr::Call(_, x) => walk(x, out),
            Expr::Bin(_, a, b) => {
                walk(a, out);
                walk(b, out);
            }
            Expr::Num(_) | Expr::Pc => {}
        }
    }
    walk(e, &mut out);
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::asm::lex::tokenize;

    fn ev(s: &str) -> i64 {
        let e = parse(&tokenize(s).unwrap(), Some("f")).unwrap();
        eval(&e, &|n| (n == "f.x").then_some(10), 0x100).unwrap()
    }

    #[test]
    fn values() {
        assert_eq!(ev("1 + 2 * 3"), 7);
        assert_eq!(ev("(1 + 2) * 3"), 9);
        assert_eq!(ev("-7 / 2"), -3);
        assert_eq!(ev("-7 % 2"), -1);
        assert_eq!(ev("7 % -2"), 1);
        assert_eq!(ev("1 << 4 | 1"), 17);
        assert_eq!(ev("-8 >> 2"), -2);
        assert_eq!(ev("hi(0x1234) + lo(0x1234)"), 0x46);
        assert_eq!(ev("hi16(0x12345678)"), 0x1234);
        assert_eq!(ev(".x + $"), 0x10A);
        assert_eq!(ev("!0 + ~0"), 0);
        let hi = parse(&tokenize("hi").unwrap(), None).unwrap();
        assert_eq!(hi, Expr::Sym("hi".into()));
    }

    #[test]
    fn errors() {
        let err = |s: &str| parse(&tokenize(s).unwrap(), None).unwrap_err().msg;
        assert_eq!(err("1 2"), "junk after expression: '2'");
        assert_eq!(err("(1"), "missing ')'");
        assert_eq!(err(""), "expression expected");
        assert_eq!(err("1 + ,"), "unexpected ',' in expression");
        assert_eq!(err("\"ab\""), "unexpected '\"ab\"' in expression");
        let deep = "(".repeat(1000) + "1" + &")".repeat(1000);
        assert_eq!(err(&deep), "expression nested too deeply");
    }

    #[test]
    fn overflow() {
        let err = |s: &str| {
            let e = parse(&tokenize(s).unwrap(), None).unwrap();
            match eval(&e, &|_| None, 0) {
                Err(EvalError::Asm(e)) => e.msg,
                r => panic!("{r:?}"),
            }
        };
        assert_eq!(err("1 << 64"), "shift count 64 out of range");
        assert_eq!(err("1 >> -1"), "shift count -1 out of range");
        assert_eq!(err("3 << 62"), "arithmetic overflow");
        assert_eq!(err("1 / 0"), "division by zero");
    }
}
