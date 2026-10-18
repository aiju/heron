/* The sprite compiler (sprite.h): a phase's pre-shifted rows as draft 2
   machine code, made at start-up. The code is called with r1 at the
   sprite's first word and steps r1 through the words it draws:

     a transparent word     nothing (r1 moves on with the next word's ADD)
     an opaque word         MOV [r1]+, rK          (CLR [r1]+ for 0)
     a masked word          MOV r0, [r1]
                            AND r0, rK             (~mask)
                            OR  r0, rJ             (the image; none for 0)
                            MOV [r1]+, r0
     to the next row        ADD r1, #delta

   The constants used most (at least twice) are loaded into registers
   first: r2-r6 and r8-r12, ten of them; the rest are in the
   instructions (16 or 32 bits). It clobbers r0-r6 and r8-r12 and returns
   through r7; draw_compiled (draw.s) saves what C expects.

   Constants come in the instruction stream, which costs the same memory
   cycles as loading them as data; what the code saves is the loop, the
   mask's load for opaque words, everything for transparent ones, and
   both loads where a constant is in a register.

   With bytes_ok (8 bits a pixel, linear: L0's M1 and M2), a pixel is a
   byte, so a masked word whose mask is whole bytes is written with byte
   and half stores and not read at all:

     a word with pixel 3 opaque     MOV byte [r1 + 3], rK
     pixels 0 and 1                 MOV half [r1], rK

   jit_restore makes the matching erase: the words the sprite draws
   copied back from the background, with r2 at the background's word. */

#include <stdlib.h>
#include <string.h>
#include "sprite.h"

#define NREG 10
static const unsigned char regs[NREG] = {2, 3, 4, 5, 6, 8, 9, 10, 11, 12};

static unsigned short *cp;          /* the next parcel */

static void half(unsigned v)
{
    *cp++ = (unsigned short)v;
}

/* an instruction's first parcel: its opcode byte, then its register byte */
static void op(unsigned opc, unsigned rb)
{
    half(opc | (rb & 255) << 8);
}

/* the special mode's constants (RFC 0028, 3.1): 16 bits sign- or
   zero-extended, shifted left 16, or all 32 */
static void special(unsigned opc, int rd, unsigned c)
{
    int sc = (int)c;
    if (sc >= -32768 && sc <= 32767) {
        op(opc, rd << 4 | 0);
        half(c);
    } else if (c <= 0xFFFF) {
        op(opc, rd << 4 | 1);
        half(c);
    } else if (!(c & 0xFFFF)) {
        op(opc, rd << 4 | 2);
        half(c >> 16);
    } else {
        op(opc, rd << 4 | 3);
        half(c);
        half(c >> 16);
    }
}

/* MOV rd, #c: the quick constants, the 7-bit form, the special mode */
static void mov_imm(int rd, unsigned c)
{
    int sc = (int)c;
    if (c <= 15)
        op(0x11, rd << 4 | c);
    else if (sc < 0 && sc >= -16)
        op(0x1D, rd << 4 | (unsigned)(-sc - 1));
    else if (c <= 127)
        op(0x70 | (c & 7), rd << 4 | c >> 3);
    else
        special(0x1F, rd, c);
}

/* rd <- rd op c, for ADD (row 4), AND (8) and OR (9) */
static void alu_imm(unsigned row, int rd, unsigned c)
{
    int sc = (int)c;
    if (c <= 15)
        op(row | 1, rd << 4 | c);
    else if (sc < 0 && sc >= -16)
        op(row | 0xD, rd << 4 | (unsigned)(-sc - 1));
    else
        special(row | 0xF, rd, c);
}

/* the constants and how often each is used: a small hash table */
#define HSIZE 1024
static unsigned hval[HSIZE];
static int hcnt[HSIZE];
static short used[HSIZE];           /* the slots in use */
static int nused;

static void count(unsigned v)
{
    unsigned i = (v ^ v >> 10 ^ v >> 20) & (HSIZE - 1);
    while (hcnt[i] && hval[i] != v)
        i = (i + 1) & (HSIZE - 1);
    if (!hcnt[i])
        used[nused++] = i;
    hval[i] = v;
    hcnt[i]++;
}

static unsigned rval[NREG];
static int nreg;

/* the register holding v (in the bits of mask), or -1 */
static int reg_of(unsigned v, unsigned mask)
{
    int k;
    for (k = 0; k < nreg; k++)
        if ((rval[k] & mask) == v)
            return regs[k];
    return -1;
}

/* rd <- rd op v: from a register if v is in one */
static void alu(unsigned row, int rd, unsigned v)
{
    int r = reg_of(v, ~0u);
    if (r >= 0)
        op(row, rd << 4 | r);
    else
        alu_imm(row, rd, v);
}

/* a masked word whose pixels are whole bytes, opaque or not (8 bits a
   pixel, linear): its opaque bytes as byte and half stores, at the word
   `at` bytes past r1, with no read. Returns 0 if the word isn't one. */
static int narrow_bytes(unsigned nm)
{
    int j;
    for (j = 0; j < 32; j += 8) {
        unsigned b = (~nm >> j) & 255;
        if (b && b != 255)
            return 0;
    }
    return 1;
}

static void narrow(unsigned nm, unsigned im, int disp, int counting)
{
    int j = 0, r;
    while (j < 4) {
        int two = j % 2 == 0 && (~nm >> (8 * j) & 0xFFFF) == 0xFFFF;
        unsigned mask = two ? 0xFFFF : 0xFF, v = (im >> (8 * j)) & mask;
        if (!(~nm >> (8 * j) & 255)) {
            j++;
            continue;
        }
        if (counting)
            count(v);
        else {
            if ((r = reg_of(v, mask)) < 0) {
                mov_imm(0, v);
                r = 0;
            }
            /* MOV byte/half [r1 + disp], rK */
            if (disp + j == 0)
                op(two ? 0x2B : 0x28, r << 4 | 1);
            else {
                op(two ? 0x2C : 0x29, r << 4 | 1);
                half(disp + j);
            }
        }
        j += two ? 2 : 1;
    }
}

static unsigned short scratch[8192];

static void *finish(int *bytes)
{
    void *code;
    op(0xF0, 0x07);                             /* RET */
    *bytes = (cp - scratch) * 2;
    code = malloc(*bytes);
    memcpy(code, scratch, *bytes);
    return code;
}

void *jit_sprite(const unsigned *rows, int ww, int h, int pitch, int bytes_ok, int *bytes)
{
    int r, k, i, best, cur;
    /* count the constants: images to store or OR in, masks to AND with,
       bytes and halves to store */
    for (i = 0; i < nused; i++)
        hcnt[used[i]] = 0;
    nused = 0;
    for (i = 0; i < ww * h; i++) {
        unsigned nm = rows[2 * i], im = rows[2 * i + 1];
        if (nm == ~0u)
            continue;
        if (nm && bytes_ok && narrow_bytes(nm)) {
            narrow(nm, im, 0, 1);
            continue;
        }
        if (nm)
            count(nm);
        if (im)
            count(im);
    }
    /* the ten used most, if at least twice */
    for (nreg = 0; nreg < NREG; nreg++) {
        best = -1;
        for (k = 0; k < nused; k++) {
            i = used[k];
            if (hcnt[i] >= 2 && (best < 0 || hcnt[i] > hcnt[best]))
                best = i;
        }
        if (best < 0)
            break;
        rval[nreg] = hval[best];
        hcnt[best] = 0;
    }
    cp = scratch;
    for (k = 0; k < nreg; k++)
        mov_imm(regs[k], rval[k]);
    cur = 0;                    /* r1's offset in bytes from the first word */
    for (r = 0; r < h; r++)
        for (k = 0; k < ww; k++) {
            unsigned nm = rows[2 * (r * ww + k)], im = rows[2 * (r * ww + k) + 1];
            int at = (r * pitch + k) * 4, rk;
            if (nm == ~0u)
                continue;       /* transparent */
            if (nm && bytes_ok && narrow_bytes(nm)) {
                narrow(nm, im, at - cur, 0);    /* r1 stays */
                continue;
            }
            if (at != cur)
                alu_imm(0x40, 1, at - cur);     /* ADD r1, #delta */
            if (!nm) {
                /* opaque: a store */
                if (!im)
                    op(0x20, 0x61);             /* CLR [r1]+ */
                else if ((rk = reg_of(im, ~0u)) >= 0)
                    op(0x26, rk << 4 | 1);      /* MOV [r1]+, rK */
                else {
                    mov_imm(0, im);
                    op(0x26, 0x01);             /* MOV [r1]+, r0 */
                }
            } else {
                op(0x12, 0x01);                 /* MOV r0, [r1] */
                alu(0x80, 0, nm);               /* AND r0, ~mask */
                if (im)
                    alu(0x90, 0, im);           /* OR r0, image */
                op(0x26, 0x01);                 /* MOV [r1]+, r0 */
            }
            cur = at + 4;
        }
    return finish(bytes);
}

/* the restore: the words the sprite draws (none of its transparent
   ones) copied from r2 to r1, both stepping through the rows */
void *jit_restore(const unsigned *rows, int ww, int h, int pitch, int *bytes)
{
    int r, k, cur = 0;
    cp = scratch;
    for (r = 0; r < h; r++)
        for (k = 0; k < ww; k++) {
            int at = (r * pitch + k) * 4;
            if (rows[2 * (r * ww + k)] == ~0u)
                continue;
            if (at != cur) {
                alu_imm(0x40, 1, at - cur);     /* ADD r1, #delta */
                alu_imm(0x40, 2, at - cur);     /* ADD r2, #delta */
            }
            op(0x16, 0x02);                     /* MOV r0, [r2]+ */
            op(0x26, 0x01);                     /* MOV [r1]+, r0 */
            cur = at + 4;
        }
    return finish(bytes);
}
