# Object files and linking

The assembler can write object files, the C compiler makes them, and a
linker puts them together, so C and hand-written assembly can be mixed in
one program. This is for the draft 1 machines (1a and 1b).

**Short version.**

- `heron v1_isa asm -c` assembles a file into an **object file**: sections that the
  linker places, a symbol table and relocations. A file that uses `.org`
  (all the existing programs, through `lib/start.s`) still assembles to
  fixed addresses, so nothing changes for it.
- `heron v1_isa ld` **links** object files and libraries into an executable,
  leaving out every section nothing refers to. `heron v1_isa run` runs executables,
  and links object files on the way.
- The C compiler compiles each `.c` file into an object file (one section
  per function and per variable) and links it with the start code and the
  C library. `heron c_compiler cc` takes `.s`, `.o` and `.a` files as well as `.c`.
- **Addresses the linker fills in are 16 bits by default** ("near"): data
  has to end up below 32 KB. A symbol declared `.far` gets 32-bit fields
  instead. The compiler marks objects bigger than 1 KB far, and the linker
  puts near data first, so this only bites programs with more than about
  32 KB of small variables. The linker checks every field and says when
  one doesn't fit.
- **C names get a `_`** in front (`main` is `_main`), and
  `__asm__("name")` on a declaration gives the exact name, so C can call
  the hand-written routines: `extern void print_u32(unsigned) __asm__("print_u32");`.
- Compared with compiling a whole program at once (what the compiler did
  before), the benchmarks take between 0.3% fewer and 0.9% more cycles,
  and the programs' own code is 2–30 bytes bigger: calls between functions
  always take the two-parcel form, and arrays over 1 KB need 32-bit
  addresses.

## Using it

```sh
heron v1_isa --isa v1b asm -c util.s                  # -> util.o
heron c_compiler cc --isa v1b -c prog.c                   # -> prog.o
heron c_compiler cc --isa v1b prog.o util.o -o prog.out   # link with the start code and the C library
heron c_compiler cc --isa v1b prog.c util.s --run         # all in one go
heron v1_isa run prog.out --stats                     # run an executable (the ISA comes from the file)

heron v1_isa ld start.o prog.o util.o -o prog.out --map   # link by hand, and show the layout
heron v1_isa ld prog.o ... --bin prog.bin             # also write a raw memory image
heron v1_isa ar -o mylib.a a.o b.o                    # a library
heron v1_isa objdump -d prog.o                        # sections, symbols, relocations, disassembly
```

`heron c_compiler cc` without `-c`, `-S` or `--run` writes an executable, `FIRST.out`
or `-o`. Other options: `--map` (the linker's layout), `--no-lib`,
`--no-start` (the program brings its own vectors). `heron v1_isa ld` options:
`--base ADDR` (where the relocatable sections start), `--entry SYMBOL`
(keep this and what it uses, besides the vectors), `--no-gc`.

`heron v1_isa run FILE.s` and `heron v1_isa asm FILE.s` work as before: one file, assembled
straight to a memory image, with every short form the final addresses
allow.

## Assembly

In an object file each section has its own location counter, starting at
0, and the linker decides where it goes.

| Directive | |
|---|---|
| `.text`, `.data`, `.bss` | switch to that section (`.text` at the start) |
| `.section NAME` | switch to any section, e.g. `.section .text.main` |
| `.global a, b` | export these symbols (`.globl` too) |
| `.local a` | don't export this one |
| `.far a, b` | the symbol may lie anywhere: use 32-bit fields for it |
| `.extern a` | allowed, but not needed: a symbol the file doesn't define is external |

- **Exports:** if a file has no `.global` at all, every label that doesn't
  start with `.` is exported, so the existing library files
  (`studies/v1_isa/programs/v1b/lib/print.s` and so on) can be linked as they are. Once a
  file names its exports with `.global`, only those are exported.
- **`.org`** makes its section absolute: everything in it keeps the address
  it has, as in a whole-program assembly. That's how vectors at address 0
  are written. The linker checks that absolute sections don't overlap.
- **`.bss`** (and any `.bss.*` or `.farbss.*` section) only holds zeros
  (`.space`, `.align`), and takes no room in the object file.
- **Section names decide the order** in which the linker places sections:
  `.data` and `.rodata`, `.bss`, `.text`, everything else, then `.fardata`
  and `.farbss`. A name with a suffix (`.text.main`) belongs to its prefix.

What the linker fills in: an address in an instruction or in `.word` /
`.half` (draft 1's `.word` is 32 bits), as `symbol + constant`. The
assembler works out everything else itself: a branch to a label in the same
section, the difference of two labels in one section, a constant.
Anything it can't express as a relocation is an error: `MVI r1, label`
(8 bits), `label * 2`, `.byte label`, a label in the indexed mode's 8-bit
displacement.

**Instruction forms.** Both drafts have short and long encodings, and the
assembler picks them before the linker knows any address. For an address
the linker fills in it picks:

| Operand | 1a | 1b |
|---|---|---|
| `#label`, `[label]`, `[label + r]`, `[r + label]` | 16-bit immediate / `d16` | `#imm16`, `[abs16]`, `[r + d16]` |
| the same for a `.far` symbol | 32-bit immediate / `d32` | `#imm32`, `[abs32]` (no `[r + d32]`: error) |
| `LEA rd, label` (1a), `[pc + label]` (1b) | PC-relative, ±32 KB | PC-relative, ±32 KB |
| `BRA`, `Bcc`, `BSR`, `JMP`, `CALL` to another section | 16-bit PC-relative `Jcc`, ±64 KB | the same |

A branch within a section is still relaxed as usual (to the one-parcel
form when it reaches).

## Object files

The format is in [obj.py](obj.py)'s docstring (the code that reads and
writes it is Rust, [obj.rs](toolchain/src/obj.rs)): a header, section headers,
symbols, relocations, a string table and the section contents, all
little-endian. A library is a list of object files with their names. An
executable is the same format with every section placed and no
relocations; `heron v1_isa run` loads it, symbols and all, so `--stats` can still
profile by routine.

Relocations (S is the symbol's address, A the constant, P the address of
the field):

| Kind | Field | Value | Fits if |
|---|---|---|---|
| `abs32` | 32 bits (two parcels, or a `.word`) | S + A | always |
| `abs16s` | 16 bits the CPU sign-extends | S + A | below 0x8000 (or in the top 32 KB, the I/O page) |
| `abs16` | 16 bits of data (`.half`) | S + A | -32768..65535 |
| `pc16` | 16 bits, PC-relative | S + A - P | ±32 KB |
| `pc16h` | 16 bits, PC-relative in parcels (`Jcc`) | (S + A - P) / 2 | ±64 KB, even |

PC-relative fields count from the end of the instruction; the assembler
folds that distance into A. The assembler leaves relocated fields zero.

`objdump -d` shows each field with its relocation:

```
.text._main:
_main:
  000000  A200 0000       LD r2, [0x0]  ; abs16s _count+0
  000004  C101            MOV r1, #1
  000006  A12D 0000 0000  STB r1, [r2 + 0]  ; abs32 _big+0
  ...
  000018  9F00 0000       CALL 0x1C  ; pc16h print_u32-2
```

## The linker

[link.rs](toolchain/src/link.rs), in Rust, about 600 lines;
[link.py](link.py) is its Python interface.

1. **Symbols.** Every global symbol must be defined once. Libraries are
   searched for symbols still undefined, and a member is loaded whole
   when it defines one (in library order, then member order, as often as
   new references appear). A definition in a library gives way to one in
   the program's own objects, so a program can replace `strlen` or
   `putchar` without a clash.
2. **Garbage collection.** Starting from the absolute sections (the
   vectors) and `--entry`, it follows relocations and keeps only the
   sections they reach. Without vectors or an entry symbol, every section
   of the program's own objects is a root. The C compiler gives every
   function and variable its own section, so this removes whatever `main`
   can't reach, which the compiler used to do itself.
3. **Layout.** Absolute sections where they say; the rest from the end of
   the last absolute section (or `--base`), in the class order above, each
   aligned as its contents need. `__end` is the first free address after
   everything (the C library's heap starts there). Zero-filled sections are
   written into the image as zeros, so a loader doesn't have to clear them.
4. **Relocation,** with a range check for every field. The error says
   where and why:

```
error: a.o(.text+0x2): abs16s reference to x: 0x9000 is out of reach of 16-bit
addresses (0-0x7FFF); declare it .far to use 32-bit addresses
```

`--map` prints the result:

```
000000-000005       6  .text                    start_v1a.o
000008-000039      50  .text                    start_v1a.o
00003C-00003F       4  .bss._count              demo.o
000040-00005F      32  .text._main              demo.o
000060-0000D9     122  .text                    print.s
0000DA-0010D9    4096  .farbss._big             demo.o
end 0010DC
```

## C and assembly together

The C compiler's [calling convention](../studies/c_compiler/compiler.md#calling-convention):
arguments in `r1`–`r4` (a variadic function gets all of them on the
stack), the result in `r1`, `r1`–`r7` and `HI` caller-saved, `r8`–`r14`
callee-saved. The hand-written library routines fit it: `print_u32` and
friends only change `r1`–`r6` and `HI`.

C names get a leading `_` in the assembly, so they can't clash with the
assembly library's labels or with register names. Assembly calls C as
`CALL _name`; C reaches an assembly routine either through an underscored
label, or through an assembler name on its declaration:

```c
extern void print_u32(unsigned n) __asm__("print_u32");    /* programs/v1b/lib/print.s */
extern int asm_sum(int *p, int n) __asm__("asm_sum");

int twice(int x) __asm__("twice");          /* an assembler name for a C function */
int twice(int x) { return 2 * x; }
```

```
; sum.s: int asm_sum(int *p, int n), the sum of twice(p[i])
        .global asm_sum
asm_sum:
        SAVE r8-r10
        MOV  r8, r1
        MOV  r9, r2
        MOV  r10, #0
.loop:  MOV  r1, [r8]+
        CALL twice
        ADD  r10, r1
        DEC  r9, r9
        BNE  .loop
        MOV  r1, r10
        RESTORE r8-r10
        RET
```

```sh
heron c_compiler cc --isa v1b main.c sum.s studies/v1_isa/programs/v1b/lib/print.s --run
```

How the compiler uses all this:

- **One section per function and per variable** (`.text._main`,
  `.data._table`, `.bss._count`, `.fardata._big`), `.global` for
  everything that isn't `static`, `.local` for the rest.
- **Near or far:** a variable of at most 1 KB is near (16-bit addresses);
  bigger ones, and `extern` arrays of unknown size, are far, in
  `.fardata`/`.farbss`. Functions are far too, for the rare
  `MOV r1, #_f` (calls are PC-relative and don't care). Two files can't
  disagree in a dangerous way: a far reference to a near variable works,
  and a near reference to a far one fails to link.
- **The C library** (`studies/c_compiler/cc/lib/*.c`) is compiled once per process into
  a library of four object files; `lib/start_v1a.s` and `start_v1b.s`
  (vectors, stack, `CALL _main`, `_exit`) are an absolute object file.

## What it costs

`heron c_compiler bench` before and after (D16-overlap cycles):

- Most programs run 0–0.5% more cycles; wordfreq 0.9% (its three big
  arrays went from near to far), sha256 and strings slightly fewer.
- The programs' own code grows by 2–30 bytes: two bytes for each call to a
  function in another section (a one-parcel `BSR` before, when it
  reached), and two for each access to an array over 1 KB.

## Testing

`studies/v1_isa/tests/test_link.py`:

- the object format and library format round-trip, and every relocation
  kind's range check;
- the relocations the assembler makes for each kind of operand on both
  drafts, and its errors;
- linking: references across files, undefined and duplicate symbols,
  overlapping absolute sections, near data out of range and `.far`,
  libraries, programs replacing library functions, garbage collection,
  executables written and read back;
- **every hand-written draft 1 program** (both drafts, except
  `interrupts`, which has its own vectors) assembled as a relocatable
  object file, with its start code linked in separately, against its
  expected output (up to 65 relocations per program);
- C and assembly calling each other, through the API and through the
  command line.

The C compiler's tests and the random tester now go through the object
files and the linker too.

## Limitations

- **No linker relaxation.** The assembler picks every instruction's size;
  the linker only fills in fields. So a call to a function in another
  section always takes two parcels, and near or far is decided at compile
  time. Relaxation would mean the linker re-encoding instructions, which
  the format could support later with a "may shrink" flag on relocations.
- **Draft 0** gets object files only for code that needs no relocations:
  its encoder doesn't report its fields yet.
- No weak or common symbols, no debugging information beyond the symbol
  table (which keeps local labels, for profiles).
- The 32 KB near limit counts from address 0, and the start code and the
  near data come first, so it's about the data, not the size of the code.
