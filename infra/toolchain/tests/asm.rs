//! The assembler core, with a toy instruction set: a branch with a short
//! and a long form, a 16-bit load immediate and a 32-bit jump.

use std::io::Write;

use toolchain::asm::{AsmError, Assembler, Ctx, Encoder, Error, Kind, Operand};
use toolchain::obj;

struct Toy;

static TOY: Toy = Toy;

impl Encoder for Toy {
    fn name(&self) -> &'static str {
        "toy"
    }

    fn register(&self, name: &str) -> Option<u32> {
        ["r0", "r1", "r2", "r3"]
            .iter()
            .position(|&r| r == name)
            .map(|n| n as u32)
    }

    fn assemble(&self, m: &str, ops: &[Operand], ctx: &mut Ctx) -> Result<Vec<u16>, AsmError> {
        let expr = |i: usize| {
            ops.get(i)
                .and_then(Operand::expr)
                .ok_or_else(|| AsmError::new(format!("{m}: operand?")))
        };
        match m {
            "nop" => Ok(vec![0]),
            "br" => {
                let e = expr(0)?;
                let (t, known) = ctx.target(e)?;
                let off = t - (ctx.pc + 2);
                if ctx.min_words() <= 1 && (!known || (-256..=254).contains(&off)) {
                    return Ok(vec![0x1000 | ((off >> 1) & 0xFF) as u16]);
                }
                let next = ctx.pc + 4;
                ctx.fix(1, obj::PC16, Some(e), next)?;
                Ok(vec![0x2000, ((t - next) & 0xFFFF) as u16])
            }
            "li" => {
                let r = ops[0].reg().map_or(0, |r| r.n as u16);
                let e = expr(1)?;
                let (v, _) = ctx.value(e)?;
                if !(-32768..=65535).contains(&v) {
                    return Err(AsmError::new("value out of range"));
                }
                ctx.fix(1, obj::ABS16, Some(e), 0)?;
                Ok(vec![0x3000 | r << 8, (v & 0xFFFF) as u16])
            }
            "jmp" => {
                let e = expr(0)?;
                let (v, _) = ctx.value(e)?;
                ctx.fix(1, obj::ABS32, Some(e), 0)?;
                Ok(vec![
                    0x4000,
                    (v & 0xFFFF) as u16,
                    ((v >> 16) & 0xFFFF) as u16,
                ])
            }
            _ => Err(AsmError::new(format!("unknown instruction {m}"))),
        }
    }
}

fn assembler(relocatable: bool, src: &str) -> Assembler {
    let mut a = Assembler::new(&TOY, relocatable);
    a.load("t.s", Some(src)).unwrap();
    a
}

fn image(src: &str) -> (Assembler, Vec<u8>) {
    let mut a = assembler(false, src);
    let img = a.assemble().unwrap_or_else(|e| panic!("{e}"));
    let end = img.mem.keys().last().map_or(0, |&k| k + 1);
    let bytes = (0..end)
        .map(|a| img.mem.get(&a).copied().unwrap_or(0))
        .collect();
    (a, bytes)
}

fn error(src: &str) -> String {
    let mut a = Assembler::new(&TOY, false);
    match a.load("t.s", Some(src)) {
        Err(e) => e.to_string(),
        Ok(()) => a.assemble().err().expect("an error").to_string(),
    }
}

fn symbol(a: &Assembler, name: &str) -> i64 {
    a.symbols().iter().find(|(n, _)| n == name).unwrap().1
}

#[test]
fn relaxation() {
    // the forward branch only learns it's far in the second pass
    let (a, mem) =
        image("start:  br end\n        br start\n        .space 300\nend:    br start\n");
    let words: Vec<_> = a
        .stmts()
        .iter()
        .filter(|s| s.kind == Kind::Insn)
        .map(|s| s.words.clone())
        .collect();
    assert_eq!(words[0], [0x2000, 300 + 2]);
    assert_eq!(words[1], [0x10FD]);
    assert_eq!(words[2], [0x2000, (-(306 + 4) as i64 & 0xFFFF) as u16]);
    assert_eq!(symbol(&a, "end"), 4 + 2 + 300);
    assert_eq!(&mem[..2], &[0x00, 0x20]);
}

#[test]
fn labels_and_data() {
    let src = "\
f:      nop
.x:     br .x
g:      .byte 1, -1, \"ab\", 'c'
.x:     .align 4
        .half 0x1234
        .word 0x5678
        .long 0x9ABCDEF0
        .asciz \"hi\\n\"
        .fill 3, 0xAA
K = .x + 1
        .equ L, K * 2
        .align 2
        li r1, #L
";
    let (a, mem) = image(src);
    assert_eq!(symbol(&a, "f.x"), 2);
    assert_eq!(symbol(&a, "g.x"), 9);
    assert_eq!(symbol(&a, "K"), 10);
    assert_eq!(symbol(&a, "L"), 20);
    let names: Vec<&str> = a.symbols().iter().map(|(n, _)| n.as_str()).collect();
    assert_eq!(names, ["f", "f.x", "g", "g.x", "K", "L"]);
    assert_eq!(
        mem,
        [
            0x00, 0x00, 0xFF, 0x10, 1, 0xFF, b'a', b'b', b'c', 0, 0, 0, 0x34, 0x12, 0x78, 0x56,
            0xF0, 0xDE, 0xBC, 0x9A, b'h', b'i', b'\n', 0, 0xAA, 0xAA, 0xAA, 0, 0x00, 0x31, 20, 0
        ]
    );
}

#[test]
fn listing() {
    let (a, _) = image(
        "        .org 0x10\n; a comment\nx:      li r2, #0x1234 ; load\n        .ascii \"hello\"\n",
    );
    assert_eq!(
        a.listing(),
        "                     \x20       .org 0x10\n\
         0010  3200 1234      x:      li r2, #0x1234 ; load\n\
         0014  68 65 6C 6C …          .ascii \"hello\"\n"
    );
}

#[test]
fn errors() {
    assert_eq!(error("  nop\n  li r1, #x\n"), "t.s:2: undefined symbol x");
    assert_eq!(
        error("x: nop\nx: nop\n"),
        "t.s:2: x is already defined at t.s:1"
    );
    assert_eq!(error("  .frob 1\n"), "t.s:1: unknown directive .frob");
    assert_eq!(error("  li r1, #1 2\n"), "t.s:1: junk after expression: 2");
    assert_eq!(error("  li r1, #1 / 0\n"), "t.s:1: division by zero");
    assert_eq!(
        error("  .byte 1\n  nop\n"),
        "t.s:2: instruction at odd address (missing .align 2?)"
    );
    assert_eq!(
        error("  .org 0xFFFF\n  .byte 1, 2\n"),
        "t.s:2: program runs past the end of memory"
    );
    assert_eq!(
        error("  .byte 300\n"),
        "t.s:1: .byte value 300 out of range"
    );
    assert_eq!(error("  li r1, @\n"), "t.s:1: unexpected character '@'");
    assert_eq!(
        error("  li r1, [r2 - r3]\n"),
        "t.s:1: a register can't be subtracted"
    );
    assert_eq!(
        error("  li r1, r2-\n"),
        "t.s:1: unexpected register in expression: r2"
    );
    assert_eq!(error("  li r1, #2 -\n"), "t.s:1: expression expected");
    let mut a = Assembler::new(&TOY, false);
    a.load("t.s", Some("  .org 8\n  .org 4\n  nop\n")).unwrap();
    a.assemble().unwrap();
    assert_eq!(a.warnings, ["t.s:2: .org moves backwards"]);
}

#[test]
fn includes() {
    let dir = std::env::temp_dir().join(format!("heron-asm-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let file = |name: &str, text: &str| {
        let p = dir.join(name);
        std::fs::File::create(&p)
            .unwrap()
            .write_all(text.as_bytes())
            .unwrap();
        p.to_string_lossy().into_owned()
    };
    let main = file(
        "main.s",
        "f:      nop\n        .include \"inc.s\"\n.y:     br .x\n",
    );
    file("inc.s", ".x:     nop\n");
    let rec = file("rec.s", "        .include \"rec.s\"\n");
    let missing = file("missing.s", "        .include \"nowhere.s\"\n");

    let mut a = Assembler::new(&TOY, false);
    a.load(&main, None).unwrap();
    a.assemble().unwrap();
    // the included label belongs to the scope it's included in
    assert_eq!(symbol(&a, "f.x"), 2);
    assert_eq!(symbol(&a, "f.y"), 4);

    let mut a = Assembler::new(&TOY, false);
    let e = a.load(&rec, None).unwrap_err().to_string();
    assert!(e.ends_with(&format!(": recursive include of {rec}")), "{e}");
    assert!(e.starts_with(&format!("{rec}:1:")), "{e}");

    let mut a = Assembler::new(&TOY, false);
    match a.load(&missing, None) {
        Err(Error::Io { path, err }) => {
            assert!(path.ends_with("/nowhere.s"));
            assert_eq!(err.kind(), std::io::ErrorKind::NotFound);
        }
        r => panic!("{r:?}"),
    }
    std::fs::remove_dir_all(&dir).unwrap();
}

#[test]
fn object() {
    let src = "\
        .global start, K
        .far big
        .section .vectors
        .org 0
        jmp start
        .text
start:  li r1, #counter
        jmp big
        br start
        br ext_end
        .data
counter: .long start + 4
        .bss
        .space 16
K = 7
";
    let mut a = assembler(true, src);
    let o = a.assemble_object("t.o").unwrap();
    let secs: Vec<(&str, u32, u32, u32)> = o
        .sections
        .iter()
        .map(|s| (s.name.as_str(), s.flags, s.addr, s.size))
        .collect();
    assert_eq!(
        secs,
        [
            (".text", 0, 0, 4 + 6 + 2 + 4),
            (".data", 0, 0, 4),
            (".bss", obj::SEC_NOBITS, 0, 16),
            (".vectors", obj::SEC_ABS, 0, 6)
        ]
    );
    let syms: Vec<(&str, u32, u32, u32)> = o
        .symbols
        .iter()
        .map(|s| (s.name.as_str(), s.section, s.value, s.flags))
        .collect();
    assert_eq!(
        syms,
        [
            (".text", 1, 0, obj::SYM_SECTION),
            (".data", 2, 0, obj::SYM_SECTION),
            (".bss", 3, 0, obj::SYM_SECTION),
            ("start", 1, 0, obj::SYM_GLOBAL),
            ("counter", 2, 0, 0),
            ("K", obj::ABS, 7, obj::SYM_GLOBAL),
            ("big", obj::UNDEF, 0, obj::SYM_GLOBAL | obj::SYM_FAR),
            ("ext_end", obj::UNDEF, 0, obj::SYM_GLOBAL),
        ]
    );
    let relocs: Vec<(u32, u32, u32, u32, i32)> = o
        .relocs
        .iter()
        .map(|r| (r.section, r.offset, r.kind, r.symbol, r.addend))
        .collect();
    assert_eq!(
        relocs,
        [
            (4, 2, obj::ABS32, 3, 0),
            (1, 2, obj::ABS16, 4, 0),
            (1, 6, obj::ABS32, 6, 0),
            (1, 14, obj::PC16, 7, -2),
            (2, 0, obj::ABS32, 3, 4),
        ]
    );
    // fields the linker fills in hold zeros
    assert_eq!(o.sections[1].data, [0, 0, 0, 0]);
    let back = obj::ObjectFile::from_bytes(&o.to_bytes(), "t.o").unwrap();
    assert_eq!(back.sections, o.sections);

    let mut a = assembler(true, "        .bss\n        nop\n");
    assert_eq!(
        a.assemble_object("t.o").unwrap_err().to_string(),
        "t.s:2: instruction in .bss, which holds only zeros"
    );
    let mut a = assembler(true, "        .global nothere\n");
    assert!(
        a.assemble_object("t.o")
            .unwrap_err()
            .msg
            .starts_with(".global nothere, but nothere isn't defined")
    );
}
