package main

import (
	"math/rand"
	"testing"
)

// Logic-mode functions (M=1) from the 74181 datasheet, active-high data.
var logicTable = [16]func(a, b uint8) uint8{
	func(a, b uint8) uint8 { return ^a },       // 0000
	func(a, b uint8) uint8 { return ^(a | b) }, // 0001
	func(a, b uint8) uint8 { return ^a & b },   // 0010
	func(a, b uint8) uint8 { return 0 },        // 0011
	func(a, b uint8) uint8 { return ^(a & b) }, // 0100
	func(a, b uint8) uint8 { return ^b },       // 0101
	func(a, b uint8) uint8 { return a ^ b },    // 0110
	func(a, b uint8) uint8 { return a & ^b },   // 0111
	func(a, b uint8) uint8 { return ^a | b },   // 1000
	func(a, b uint8) uint8 { return ^(a ^ b) }, // 1001
	func(a, b uint8) uint8 { return b },        // 1010
	func(a, b uint8) uint8 { return a & b },    // 1011
	func(a, b uint8) uint8 { return 15 },       // 1100
	func(a, b uint8) uint8 { return a | ^b },   // 1101
	func(a, b uint8) uint8 { return a | b },    // 1110
	func(a, b uint8) uint8 { return a },        // 1111
}

func TestALU181Logic(t *testing.T) {
	for s := uint8(0); s < 16; s++ {
		for a := uint8(0); a < 16; a++ {
			for b := uint8(0); b < 16; b++ {
				for cn := uint8(0); cn < 2; cn++ {
					f, _, _, _, _ := ALU181Compute(a, b, s, 1, cn)
					if want := logicTable[s](a, b) & 15; f != want {
						t.Fatalf("logic S=%04b a=%X b=%X: got %X want %X", s, a, b, f, want)
					}
				}
			}
		}
	}
}

func TestALU181Arith(t *testing.T) {
	for a := 0; a < 16; a++ {
		for b := 0; b < 16; b++ {
			for carry := 0; carry < 2; carry++ {
				cn := uint8(carry ^ 1) // CN pin is an active-low carry
				f, _, _, _, cn4 := ALU181Compute(uint8(a), uint8(b), 0b1001, 0, cn)
				sum := a + b + carry
				if int(f) != sum&15 || int(cn4^1) != sum>>4 {
					t.Fatalf("add %X+%X+%d: got f=%X c=%d", a, b, carry, f, cn4^1)
				}
				f, _, _, _, cn4 = ALU181Compute(uint8(a), uint8(b), 0b0110, 0, cn)
				diff := a + (^b & 15) + carry // A minus B minus 1, plus carry
				if int(f) != diff&15 || int(cn4^1) != diff>>4 {
					t.Fatalf("sub %X-%X carry %d: got f=%X c=%d", a, b, carry, f, cn4^1)
				}
				// datasheet arithmetic entries with no carry: S=0000 F=A, S=1111 F=A-1, S=1100 F=A+A
				if carry == 0 {
					if f, _, _, _, _ := ALU181Compute(uint8(a), uint8(b), 0b0000, 0, 1); int(f) != a {
						t.Fatalf("S=0000: %X", f)
					}
					if f, _, _, _, _ := ALU181Compute(uint8(a), uint8(b), 0b1111, 0, 1); int(f) != (a-1)&15 {
						t.Fatalf("S=1111: %X", f)
					}
					if f, _, _, _, _ := ALU181Compute(uint8(a), uint8(b), 0b1100, 0, 1); int(f) != (2*a)&15 {
						t.Fatalf("S=1100: %X", f)
					}
				}
			}
		}
	}
}

// 16-bit ALU: four 181s with a 182 computing the inter-group carries,
// exactly as wired in cpu_v0.py.
func alu16(a, b uint16, s, m uint8, carryIn int) (uint16, int) {
	cn := uint8(carryIn ^ 1)
	var p, g [4]uint8
	for k := 0; k < 4; k++ {
		_, _, p[k], g[k], _ = ALU181Compute(uint8(a>>(4*k))&15, uint8(b>>(4*k))&15, s, m, 1)
	}
	c := [4]uint8{cn}
	c0 := cn ^ 1
	for k := 0; k < 3; k++ {
		gk, pk := g[k]^1, p[k]^1
		c0 = gk | (pk & c0)
		c[k+1] = c0 ^ 1
	}
	var f uint16
	var cout uint8
	for k := 0; k < 4; k++ {
		fk, _, _, _, cn4 := ALU181Compute(uint8(a>>(4*k))&15, uint8(b>>(4*k))&15, s, m, c[k])
		f |= uint16(fk) << (4 * k)
		cout = cn4
	}
	return f, int(cout ^ 1)
}

func TestALU16WithLookahead(t *testing.T) {
	r := rand.New(rand.NewSource(7))
	for i := 0; i < 200000; i++ {
		a, b := uint16(r.Intn(65536)), uint16(r.Intn(65536))
		ci := r.Intn(2)
		f, c := alu16(a, b, 0b1001, 0, ci)
		sum := int(a) + int(b) + ci
		if f != uint16(sum) || c != sum>>16 {
			t.Fatalf("%04X+%04X+%d = %04X c%d", a, b, ci, f, c)
		}
		f, c = alu16(a, b, 0b0110, 0, ci)
		d := int(a) + int(^b) + ci
		if f != uint16(d) || c != d>>16 {
			t.Fatalf("%04X-%04X (c%d) = %04X c%d", a, b, ci, f, c)
		}
	}
}
