package main

import "fmt"

func NewModel(c *Chip) Model {
	switch c.ModelN {
	case "nand", "nor", "and", "or", "xor":
		return &Gate{fn: c.ModelN}
	case "dff74":
		return &FF74{}
	case "dec138":
		return &Dec138{}
	case "mux151":
		return &Mux151{}
	case "mux153":
		return &Mux153{}
	case "mux157":
		return &Mux157{}
	case "cnt161":
		return &Counter{sync: false}
	case "cnt163":
		return &Counter{sync: true}
	case "dff175":
		return &FF175{}
	case "reg377":
		return &Reg377{}
	case "buf541":
		return &Buf541{}
	case "cmp688":
		return &Cmp688{}
	case "alu181":
		return &ALU181{}
	case "cla182":
		return &CLA182{}
	case "sram":
		return &SRAM{}
	case "rom":
		return &ROM{}
	case "const":
		return &Const{}
	case "clockgen":
		return &ClockGen{}
	case "iodev":
		return &IODev{}
	}
	panic("unknown model " + c.ModelN)
}

func b2u(b bool) uint8 {
	if b {
		return 1
	}
	return 0
}

// ---------------------------------------------------------------- gates

type Gate struct {
	fn    string
	secOf []int   // pin -> section
	ins   [][]int // section -> input pins
	out   []int   // section -> output pin
	d     int64
}

func (g *Gate) Init(s *Sim, c *Chip) {
	g.secOf = make([]int, len(c.PinNames))
	var cur []int
	for p, k := range c.Kinds {
		if k == "in" {
			cur = append(cur, p)
			g.secOf[p] = len(g.out)
		} else {
			g.ins = append(g.ins, cur)
			g.out = append(g.out, p)
			g.secOf[p] = len(g.out) - 1
			cur = nil
		}
	}
	g.d = c.D("A->Y")
	for sec := range g.out {
		g.eval(s, c, sec, 0)
	}
}

func (g *Gate) eval(s *Sim, c *Chip, sec int, d int64) {
	var v uint8
	switch g.fn {
	case "and", "nand":
		v = 1
		for _, p := range g.ins[sec] {
			v &= s.In(c, p)
		}
		if g.fn == "nand" {
			v ^= 1
		}
	case "or", "nor":
		for _, p := range g.ins[sec] {
			v |= s.In(c, p)
		}
		if g.fn == "nor" {
			v ^= 1
		}
	case "xor":
		for _, p := range g.ins[sec] {
			v ^= s.In(c, p)
		}
	}
	s.Drive(c, g.out[sec], v, true, d)
}

func (g *Gate) Eval(s *Sim, c *Chip, pin int) { g.eval(s, c, g.secOf[pin], g.d) }

// ---------------------------------------------------------------- 74: dual D flip-flop

type ff74sec struct {
	d, clk, pre, clr, q, qn int
	prev                    uint8
	state                   uint8
	lastEdge                int64
}

type FF74 struct {
	sec                    [2]ff74sec
	dClk, dPC, setup, hold int64
}

func (f *FF74) Init(s *Sim, c *Chip) {
	for i := 0; i < 2; i++ {
		p := fmt.Sprint(i + 1)
		f.sec[i] = ff74sec{d: c.Pin(p + "D"), clk: c.Pin(p + "CLK"), pre: c.Pin(p + "PRE"), clr: c.Pin(p + "CLR"),
			q: c.Pin(p + "Q"), qn: c.Pin(p + "QN"), lastEdge: -1, state: randBit()}
	}
	f.dClk, f.dPC = c.D("CLK->Q"), c.D("PRE/CLR->Q")
	f.setup, f.hold = c.D("setup D"), c.D("hold D")
	for i := range f.sec {
		f.out(s, c, &f.sec[i], 0)
	}
}

func (f *FF74) out(s *Sim, c *Chip, x *ff74sec, d int64) {
	pre, clr := s.In(c, x.pre), s.In(c, x.clr)
	q, qn := x.state, x.state^1
	if pre == 0 && clr == 0 {
		q, qn = 1, 1
	}
	s.Drive(c, x.q, q, true, d)
	s.Drive(c, x.qn, qn, true, d)
}

func (f *FF74) Eval(s *Sim, c *Chip, pin int) {
	for i := range f.sec {
		x := &f.sec[i]
		switch pin {
		case x.clk:
			v := s.In(c, x.clk)
			if v == 1 && x.prev == 0 && s.In(c, x.pre) == 1 && s.In(c, x.clr) == 1 {
				s.CheckSetup(c, x.d, f.setup, "D")
				x.state = s.In(c, x.d)
				x.lastEdge = s.Now
				f.out(s, c, x, f.dClk)
			}
			x.prev = v
		case x.pre, x.clr:
			if s.In(c, x.pre) == 0 {
				x.state = 1
			}
			if s.In(c, x.clr) == 0 {
				x.state = 0
			}
			f.out(s, c, x, f.dPC)
		case x.d:
			s.CheckHold(c, x.d, x.lastEdge, f.hold, "D")
		}
	}
}

// ---------------------------------------------------------------- 138 decoder

type Dec138 struct {
	sel          [3]int
	g1, g2a, g2b int
	y            [8]int
	dA, dG       int64
}

func (m *Dec138) Init(s *Sim, c *Chip) {
	m.sel = [3]int{c.Pin("A"), c.Pin("B"), c.Pin("C")}
	m.g1, m.g2a, m.g2b = c.Pin("G1"), c.Pin("G2A"), c.Pin("G2B")
	for i := range m.y {
		m.y[i] = c.Pin(fmt.Sprintf("Y%d", i))
	}
	m.dA, m.dG = c.D("A->Y"), c.D("G->Y")
	m.eval(s, c, 0)
}

func (m *Dec138) eval(s *Sim, c *Chip, d int64) {
	en := s.In(c, m.g1) == 1 && s.In(c, m.g2a) == 0 && s.In(c, m.g2b) == 0
	sel := int(s.In(c, m.sel[0])) | int(s.In(c, m.sel[1]))<<1 | int(s.In(c, m.sel[2]))<<2
	for i, p := range m.y {
		s.Drive(c, p, b2u(!(en && sel == i)), true, d)
	}
}

func (m *Dec138) Eval(s *Sim, c *Chip, pin int) {
	if pin == m.g1 || pin == m.g2a || pin == m.g2b {
		m.eval(s, c, m.dG)
	} else {
		m.eval(s, c, m.dA)
	}
}

// ---------------------------------------------------------------- 151 8:1 mux

type Mux151 struct {
	d                      [8]int
	sel                    [3]int
	g, y, w                int
	dDY, dDW, dSY, dSW, dG int64
}

func (m *Mux151) Init(s *Sim, c *Chip) {
	for i := range m.d {
		m.d[i] = c.Pin(fmt.Sprintf("D%d", i))
	}
	m.sel = [3]int{c.Pin("A"), c.Pin("B"), c.Pin("C")}
	m.g, m.y, m.w = c.Pin("G"), c.Pin("Y"), c.Pin("W")
	m.dDY, m.dDW, m.dSY, m.dSW, m.dG = c.D("D->Y"), c.D("D->W"), c.D("S->Y"), c.D("S->W"), c.D("G->Y")
	m.eval(s, c, 0, 0)
}

func (m *Mux151) eval(s *Sim, c *Chip, dy, dw int64) {
	var v uint8
	if s.In(c, m.g) == 0 {
		sel := int(s.In(c, m.sel[0])) | int(s.In(c, m.sel[1]))<<1 | int(s.In(c, m.sel[2]))<<2
		v = s.In(c, m.d[sel])
	}
	s.Drive(c, m.y, v, true, dy)
	s.Drive(c, m.w, v^1, true, dw)
}

func (m *Mux151) Eval(s *Sim, c *Chip, pin int) {
	switch pin {
	case m.sel[0], m.sel[1], m.sel[2]:
		m.eval(s, c, m.dSY, m.dSW)
	case m.g:
		m.eval(s, c, m.dG, m.dG)
	default:
		m.eval(s, c, m.dDY, m.dDW)
	}
}

// ---------------------------------------------------------------- 153 dual 4:1 mux

type Mux153 struct {
	cin        [2][4]int
	g, y       [2]int
	a, b       int
	secOf      []int
	dC, dS, dG int64
}

func (m *Mux153) Init(s *Sim, c *Chip) {
	m.secOf = make([]int, len(c.PinNames))
	for i := range m.secOf {
		m.secOf[i] = -1
	}
	for sec := 0; sec < 2; sec++ {
		for i := 0; i < 4; i++ {
			m.cin[sec][i] = c.Pin(fmt.Sprintf("%dC%d", sec+1, i))
			m.secOf[m.cin[sec][i]] = sec
		}
		m.g[sec] = c.Pin(fmt.Sprintf("%dG", sec+1))
		m.y[sec] = c.Pin(fmt.Sprintf("%dY", sec+1))
	}
	m.a, m.b = c.Pin("A"), c.Pin("B")
	m.dC, m.dS, m.dG = c.D("C->Y"), c.D("S->Y"), c.D("G->Y")
	m.eval(s, c, 0, 0)
	m.eval(s, c, 1, 0)
}

func (m *Mux153) eval(s *Sim, c *Chip, sec int, d int64) {
	var v uint8
	if s.In(c, m.g[sec]) == 0 {
		v = s.In(c, m.cin[sec][int(s.In(c, m.a))|int(s.In(c, m.b))<<1])
	}
	s.Drive(c, m.y[sec], v, true, d)
}

func (m *Mux153) Eval(s *Sim, c *Chip, pin int) {
	switch {
	case pin == m.a || pin == m.b:
		m.eval(s, c, 0, m.dS)
		m.eval(s, c, 1, m.dS)
	case pin == m.g[0]:
		m.eval(s, c, 0, m.dG)
	case pin == m.g[1]:
		m.eval(s, c, 1, m.dG)
	case m.secOf[pin] >= 0:
		m.eval(s, c, m.secOf[pin], m.dC)
	}
}

// ---------------------------------------------------------------- 157 quad 2:1 mux

type Mux157 struct {
	a, b, y    [4]int
	sec        []int
	sel, g     int
	dA, dS, dG int64
}

func (m *Mux157) Init(s *Sim, c *Chip) {
	m.sec = make([]int, len(c.PinNames))
	for i := range m.sec {
		m.sec[i] = -1
	}
	for i := 0; i < 4; i++ {
		m.a[i], m.b[i], m.y[i] = c.Pin(fmt.Sprintf("%dA", i+1)), c.Pin(fmt.Sprintf("%dB", i+1)), c.Pin(fmt.Sprintf("%dY", i+1))
		m.sec[m.a[i]], m.sec[m.b[i]] = i, i
	}
	m.sel, m.g = c.Pin("S"), c.Pin("G")
	m.dA, m.dS, m.dG = c.D("A->Y"), c.D("S->Y"), c.D("G->Y")
	for i := 0; i < 4; i++ {
		m.eval(s, c, i, 0)
	}
}

func (m *Mux157) eval(s *Sim, c *Chip, i int, d int64) {
	var v uint8
	if s.In(c, m.g) == 0 {
		if s.In(c, m.sel) == 1 {
			v = s.In(c, m.b[i])
		} else {
			v = s.In(c, m.a[i])
		}
	}
	s.Drive(c, m.y[i], v, true, d)
}

func (m *Mux157) Eval(s *Sim, c *Chip, pin int) {
	switch {
	case pin == m.sel || pin == m.g:
		d := m.dS
		if pin == m.g {
			d = m.dG
		}
		for i := 0; i < 4; i++ {
			m.eval(s, c, i, d)
		}
	case m.sec[pin] >= 0:
		m.eval(s, c, m.sec[pin], m.dA)
	}
}

// ---------------------------------------------------------------- 161/163 counters

type Counter struct {
	sync                                                 bool
	clk, clr, load, enp, ent, rco                        int
	d, q                                                 [4]int
	state, prev                                          uint8
	lastEdge                                             int64
	loadAtEdge                                           bool
	dClkQ, dClkRco, dEntRco, dClr                        int64
	suData, hData, suLoad, hLoad, suEn, hEn, suClr, hClr int64
}

func (m *Counter) Init(s *Sim, c *Chip) {
	m.clk, m.clr, m.load, m.enp, m.ent, m.rco = c.Pin("CLK"), c.Pin("CLR"), c.Pin("LOAD"), c.Pin("ENP"), c.Pin("ENT"), c.Pin("RCO")
	for i, n := range []string{"A", "B", "C", "D"} {
		m.d[i] = c.Pin(n)
	}
	for i, n := range []string{"QA", "QB", "QC", "QD"} {
		m.q[i] = c.Pin(n)
	}
	m.dClkQ, m.dClkRco, m.dEntRco = c.D("CLK->Q"), c.D("CLK->RCO"), c.D("ENT->RCO")
	if !m.sync {
		m.dClr = c.D("CLR->Q")
	}
	m.suData, m.hData = c.D("setup data"), c.D("hold data")
	m.suLoad, m.hLoad = c.D("setup LOAD"), c.D("hold LOAD")
	m.suEn, m.hEn = c.D("setup EN"), c.D("hold EN")
	if m.sync {
		m.suClr, m.hClr = c.D("setup CLR"), c.D("hold CLR")
	}
	m.state = randBit() | randBit()<<1 | randBit()<<2 | randBit()<<3
	m.lastEdge = -1
	m.out(s, c, 0, 0)
}

func (m *Counter) out(s *Sim, c *Chip, dq, drco int64) {
	for i := 0; i < 4; i++ {
		s.Drive(c, m.q[i], (m.state>>i)&1, true, dq)
	}
	s.Drive(c, m.rco, b2u(m.state == 15 && s.In(c, m.ent) == 1), true, drco)
}

func (m *Counter) Eval(s *Sim, c *Chip, pin int) {
	switch pin {
	case m.clk:
		v := s.In(c, m.clk)
		if v == 1 && m.prev == 0 {
			clr, load := s.In(c, m.clr), s.In(c, m.load)
			s.CheckSetup(c, m.load, m.suLoad, "LOAD")
			s.CheckSetup(c, m.enp, m.suEn, "ENP")
			s.CheckSetup(c, m.ent, m.suEn, "ENT")
			if m.sync {
				s.CheckSetup(c, m.clr, m.suClr, "CLR")
			}
			m.loadAtEdge = load == 0
			if load == 0 {
				for i := 0; i < 4; i++ {
					s.CheckSetup(c, m.d[i], m.suData, "data")
				}
			}
			m.lastEdge = s.Now
			switch {
			case clr == 0:
				m.state = 0
			case load == 0:
				m.state = 0
				for i := 0; i < 4; i++ {
					m.state |= s.In(c, m.d[i]) << i
				}
			case s.In(c, m.enp) == 1 && s.In(c, m.ent) == 1:
				m.state = (m.state + 1) & 15
			}
			m.out(s, c, m.dClkQ, m.dClkRco)
		}
		m.prev = v
	case m.clr:
		if m.sync {
			s.CheckHold(c, pin, m.lastEdge, m.hClr, "CLR")
		} else if s.In(c, m.clr) == 0 {
			m.state = 0
			m.out(s, c, m.dClr, m.dClr)
		}
	case m.ent:
		s.CheckHold(c, pin, m.lastEdge, m.hEn, "ENT")
		s.Drive(c, m.rco, b2u(m.state == 15 && s.In(c, m.ent) == 1), true, m.dEntRco)
	case m.enp:
		s.CheckHold(c, pin, m.lastEdge, m.hEn, "ENP")
	case m.load:
		s.CheckHold(c, pin, m.lastEdge, m.hLoad, "LOAD")
	default:
		if m.loadAtEdge {
			s.CheckHold(c, pin, m.lastEdge, m.hData, "data")
		}
	}
}

// ---------------------------------------------------------------- 175 quad D flip-flop

type FF175 struct {
	clk, clr          int
	d, q, qn          [4]int
	state             [4]uint8
	prev              uint8
	lastEdge          int64
	dClk, dClr, su, h int64
}

func (m *FF175) Init(s *Sim, c *Chip) {
	m.clk, m.clr = c.Pin("CLK"), c.Pin("CLR")
	for i := 0; i < 4; i++ {
		m.d[i], m.q[i], m.qn[i] = c.Pin(fmt.Sprintf("%dD", i+1)), c.Pin(fmt.Sprintf("%dQ", i+1)), c.Pin(fmt.Sprintf("%dQN", i+1))
		m.state[i] = randBit()
	}
	m.dClk, m.dClr, m.su, m.h = c.D("CLK->Q"), c.D("CLR->Q"), c.D("setup D"), c.D("hold D")
	m.lastEdge = -1
	m.out(s, c, 0)
}

func (m *FF175) out(s *Sim, c *Chip, d int64) {
	for i := 0; i < 4; i++ {
		s.Drive(c, m.q[i], m.state[i], true, d)
		s.Drive(c, m.qn[i], m.state[i]^1, true, d)
	}
}

func (m *FF175) Eval(s *Sim, c *Chip, pin int) {
	switch pin {
	case m.clk:
		v := s.In(c, m.clk)
		if v == 1 && m.prev == 0 && s.In(c, m.clr) == 1 {
			for i := 0; i < 4; i++ {
				s.CheckSetup(c, m.d[i], m.su, "D")
				m.state[i] = s.In(c, m.d[i])
			}
			m.lastEdge = s.Now
			m.out(s, c, m.dClk)
		}
		m.prev = v
	case m.clr:
		if s.In(c, m.clr) == 0 {
			m.state = [4]uint8{}
			m.out(s, c, m.dClr)
		}
	default:
		s.CheckHold(c, pin, m.lastEdge, m.h, "D")
	}
}

// ---------------------------------------------------------------- 377 octal register with enable

type Reg377 struct {
	clk, en                int
	d, q                   [8]int
	state                  [8]uint8
	prev                   uint8
	lastEdge               int64
	loaded                 bool
	dClk, suD, hD, suE, hE int64
}

func (m *Reg377) Init(s *Sim, c *Chip) {
	m.clk, m.en = c.Pin("CLK"), c.Pin("EN")
	for i := 0; i < 8; i++ {
		m.d[i], m.q[i] = c.Pin(fmt.Sprintf("D%d", i+1)), c.Pin(fmt.Sprintf("Q%d", i+1))
		m.state[i] = randBit()
	}
	m.dClk, m.suD, m.hD, m.suE, m.hE = c.D("CLK->Q"), c.D("setup D"), c.D("hold D"), c.D("setup EN"), c.D("hold EN")
	m.lastEdge = -1
	for i := 0; i < 8; i++ {
		s.Drive(c, m.q[i], m.state[i], true, 0)
	}
}

func (m *Reg377) Eval(s *Sim, c *Chip, pin int) {
	switch pin {
	case m.clk:
		v := s.In(c, m.clk)
		if v == 1 && m.prev == 0 {
			s.CheckSetup(c, m.en, m.suE, "EN")
			m.lastEdge = s.Now
			m.loaded = s.In(c, m.en) == 0
			if m.loaded {
				for i := 0; i < 8; i++ {
					s.CheckSetup(c, m.d[i], m.suD, "D")
					m.state[i] = s.In(c, m.d[i])
					s.Drive(c, m.q[i], m.state[i], true, m.dClk)
				}
			}
		}
		m.prev = v
	case m.en:
		s.CheckHold(c, pin, m.lastEdge, m.hE, "EN")
	default:
		if m.loaded {
			s.CheckHold(c, pin, m.lastEdge, m.hD, "D")
		}
	}
}

// ---------------------------------------------------------------- 541 octal buffer

type Buf541 struct {
	oe1, oe2      int
	a, y          [8]int
	idx           []int
	enabled       bool
	enAt          int64
	dA, dEn, dDis int64
}

func (m *Buf541) Init(s *Sim, c *Chip) {
	m.oe1, m.oe2 = c.Pin("OE1"), c.Pin("OE2")
	m.idx = make([]int, len(c.PinNames))
	for i := range m.idx {
		m.idx[i] = -1
	}
	for i := 0; i < 8; i++ {
		m.a[i], m.y[i] = c.Pin(fmt.Sprintf("A%d", i+1)), c.Pin(fmt.Sprintf("Y%d", i+1))
		m.idx[m.a[i]] = i
	}
	m.dA, m.dEn, m.dDis = c.D("A->Y"), c.D("OE->Y en"), c.D("OE->Y dis")
	m.enabled = s.In(c, m.oe1) == 0 && s.In(c, m.oe2) == 0
	for i := 0; i < 8; i++ {
		s.Drive(c, m.y[i], s.In(c, m.a[i]), m.enabled, 0)
	}
}

func (m *Buf541) Eval(s *Sim, c *Chip, pin int) {
	if pin == m.oe1 || pin == m.oe2 {
		en := s.In(c, m.oe1) == 0 && s.In(c, m.oe2) == 0
		if en == m.enabled {
			return
		}
		m.enabled = en
		d := m.dDis
		if en {
			d = m.dEn
		}
		m.enAt = s.Now + d
		for i := 0; i < 8; i++ {
			s.Drive(c, m.y[i], s.In(c, m.a[i]), en, d)
		}
		return
	}
	if i := m.idx[pin]; i >= 0 && m.enabled {
		t := s.Now + m.dA
		if t < m.enAt {
			t = m.enAt
		}
		s.DriveAt(c, m.y[i], s.In(c, m.a[i]), true, t)
	}
}

// ---------------------------------------------------------------- 688 comparator

type Cmp688 struct {
	p, q   [8]int
	g, peq int
	dP, dG int64
}

func (m *Cmp688) Init(s *Sim, c *Chip) {
	for i := 0; i < 8; i++ {
		m.p[i], m.q[i] = c.Pin(fmt.Sprintf("P%d", i)), c.Pin(fmt.Sprintf("Q%d", i))
	}
	m.g, m.peq = c.Pin("G"), c.Pin("PEQ")
	m.dP, m.dG = c.D("P->PEQ"), c.D("G->PEQ")
	m.eval(s, c, 0)
}

func (m *Cmp688) eval(s *Sim, c *Chip, d int64) {
	eq := s.In(c, m.g) == 0
	for i := 0; i < 8 && eq; i++ {
		eq = s.In(c, m.p[i]) == s.In(c, m.q[i])
	}
	s.Drive(c, m.peq, b2u(!eq), true, d)
}

func (m *Cmp688) Eval(s *Sim, c *Chip, pin int) {
	if pin == m.g {
		m.eval(s, c, m.dG)
	} else {
		m.eval(s, c, m.dP)
	}
}

// ---------------------------------------------------------------- 74181 ALU
//
// Active-high data. Per bit: u = A | B&S0 | ~B&S1, v = A&~B&S2 | A&B&S3,
// half-sum h = u & ~v. True carries c(i+1) = v | u&c(i), c0 = !CN.
// F = h ^ c in arithmetic mode (M=0) and F = !h in logic mode (M=1).
// Pins P and G are the active-low group propagate/generate; CN4 is the
// active-low carry out.

type ALU181 struct {
	a, b, sel, f                                             [4]int
	m, cn, aeqb, p, g, cn4                                   int
	kind                                                     []byte // pin -> 'a' (A/B), 'c' (CN), 's' (S/M)
	dABF, dABFl, dABP, dABG, dABC, dEQ, dCNF, dCNC, dSF, dMF int64
}

func (x *ALU181) Init(s *Sim, c *Chip) {
	x.kind = make([]byte, len(c.PinNames))
	for i := 0; i < 4; i++ {
		x.a[i], x.b[i], x.sel[i], x.f[i] = c.Pin(fmt.Sprintf("A%d", i)), c.Pin(fmt.Sprintf("B%d", i)), c.Pin(fmt.Sprintf("S%d", i)), c.Pin(fmt.Sprintf("F%d", i))
		x.kind[x.a[i]], x.kind[x.b[i]], x.kind[x.sel[i]] = 'a', 'a', 's'
	}
	x.m, x.cn, x.aeqb, x.p, x.g, x.cn4 = c.Pin("M"), c.Pin("CN"), c.Pin("AEQB"), c.Pin("P"), c.Pin("G"), c.Pin("CN4")
	x.kind[x.m], x.kind[x.cn] = 'm', 'c'
	x.dABF, x.dABFl, x.dABP, x.dABG, x.dABC = c.D("AB->F"), c.D("AB->F logic"), c.D("AB->P"), c.D("AB->G"), c.D("AB->CN4")
	x.dEQ, x.dCNF, x.dCNC, x.dSF, x.dMF = c.D("AB->AEQB"), c.D("CN->F"), c.D("CN->CN4"), c.D("S->F"), c.D("M->F")
	x.eval(s, c, 0, 0, 0, 0, 0)
}

func ALU181Compute(a, b, sel, m, cn uint8) (f, aeqb, p, g, cn4 uint8) {
	s0, s1, s2, s3 := sel&1, (sel>>1)&1, (sel>>2)&1, (sel>>3)&1
	var u, v [4]uint8
	for i := 0; i < 4; i++ {
		ai, bi := (a>>i)&1, (b>>i)&1
		u[i] = ai | (bi & s0) | ((bi ^ 1) & s1)
		v[i] = (ai & (bi ^ 1) & s2) | (ai & bi & s3)
	}
	carry := cn ^ 1
	for i := 0; i < 4; i++ {
		h := u[i] & (v[i] ^ 1)
		var fi uint8
		if m == 1 {
			fi = h ^ 1
		} else {
			fi = h ^ carry
		}
		f |= fi << i
		carry = v[i] | (u[i] & carry)
	}
	cn4 = carry ^ 1
	gg := v[3] | (u[3] & v[2]) | (u[3] & u[2] & v[1]) | (u[3] & u[2] & u[1] & v[0])
	pp := u[0] & u[1] & u[2] & u[3]
	g, p = gg^1, pp^1
	aeqb = b2u(f == 15)
	return
}

func (x *ALU181) eval(s *Sim, c *Chip, dF, dP, dG, dC, dE int64) {
	var a, b, sel uint8
	for i := 0; i < 4; i++ {
		a |= s.In(c, x.a[i]) << i
		b |= s.In(c, x.b[i]) << i
		sel |= s.In(c, x.sel[i]) << i
	}
	f, aeqb, p, g, cn4 := ALU181Compute(a, b, sel, s.In(c, x.m), s.In(c, x.cn))
	if dF >= 0 {
		for i := 0; i < 4; i++ {
			s.Drive(c, x.f[i], (f>>i)&1, true, dF)
		}
	}
	if dP >= 0 {
		s.Drive(c, x.p, p, true, dP)
	}
	if dG >= 0 {
		s.Drive(c, x.g, g, true, dG)
	}
	if dC >= 0 {
		s.Drive(c, x.cn4, cn4, true, dC)
	}
	if dE >= 0 {
		s.Drive(c, x.aeqb, aeqb, true, dE)
	}
}

func (x *ALU181) Eval(s *Sim, c *Chip, pin int) {
	switch x.kind[pin] {
	case 'a':
		dF := x.dABF
		if s.In(c, x.m) == 1 {
			dF = x.dABFl
		}
		x.eval(s, c, dF, x.dABP, x.dABG, x.dABC, x.dEQ)
	case 'c':
		x.eval(s, c, x.dCNF, -1, -1, x.dCNC, x.dCNF)
	case 's':
		x.eval(s, c, x.dSF, x.dSF, x.dSF, x.dSF, x.dSF)
	case 'm':
		x.eval(s, c, x.dMF, -1, -1, -1, x.dMF)
	}
}

// ---------------------------------------------------------------- 74182 carry lookahead
//
// Pins carry the same polarities as the 74181 they connect to: CN and the
// carry outputs are active-low carries, P and G inputs active-low.

type CLA182 struct {
	cn, cnx, cny, cnz, pOut, gOut int
	p, g                          [4]int
	isP, isG                      []bool
	dPG, dCN, dPP, dPGG           int64
}

func (x *CLA182) Init(s *Sim, c *Chip) {
	x.isP, x.isG = make([]bool, len(c.PinNames)), make([]bool, len(c.PinNames))
	for i := 0; i < 4; i++ {
		x.p[i], x.g[i] = c.Pin(fmt.Sprintf("P%d", i)), c.Pin(fmt.Sprintf("G%d", i))
		x.isP[x.p[i]], x.isG[x.g[i]] = true, true
	}
	x.cn, x.cnx, x.cny, x.cnz, x.pOut, x.gOut = c.Pin("CN"), c.Pin("CNX"), c.Pin("CNY"), c.Pin("CNZ"), c.Pin("P"), c.Pin("G")
	x.dPG, x.dCN, x.dPP, x.dPGG = c.D("PG->CN"), c.D("CN->CN"), c.D("P->P"), c.D("PG->G")
	x.eval(s, c, 0, 0, 0)
}

func (x *CLA182) eval(s *Sim, c *Chip, dC, dP, dG int64) {
	var p, g [4]uint8
	for i := 0; i < 4; i++ {
		p[i], g[i] = s.In(c, x.p[i])^1, s.In(c, x.g[i])^1
	}
	c0 := s.In(c, x.cn) ^ 1
	c1 := g[0] | (p[0] & c0)
	c2 := g[1] | (p[1] & c1)
	c3 := g[2] | (p[2] & c2)
	if dC >= 0 {
		s.Drive(c, x.cnx, c1^1, true, dC)
		s.Drive(c, x.cny, c2^1, true, dC)
		s.Drive(c, x.cnz, c3^1, true, dC)
	}
	if dP >= 0 {
		s.Drive(c, x.pOut, (p[0]&p[1]&p[2]&p[3])^1, true, dP)
	}
	if dG >= 0 {
		gg := g[3] | (p[3] & g[2]) | (p[3] & p[2] & g[1]) | (p[3] & p[2] & p[1] & g[0])
		s.Drive(c, x.gOut, gg^1, true, dG)
	}
}

func (x *CLA182) Eval(s *Sim, c *Chip, pin int) {
	if pin == x.cn {
		x.eval(s, c, x.dCN, -1, -1)
	} else {
		x.eval(s, c, x.dPG, x.dPP, x.dPGG)
	}
}

// ---------------------------------------------------------------- static RAM

type SRAM struct {
	a                                []int
	io                               [8]int
	ce, oe, we                       int
	kind                             []byte
	Mem                              []byte
	reading                          bool
	weLow                            bool
	weFall, weRise                   int64
	tAA, tACE, tOE, tOHZ, tCHZ, tWHZ int64
	tAS, tAW, tWP, tDW, tDH, tWR     int64
}

func (m *SRAM) Init(s *Sim, c *Chip) {
	m.kind = make([]byte, len(c.PinNames))
	for i := 0; ; i++ {
		name := fmt.Sprintf("A%d", i)
		found := false
		for _, p := range c.PinNames {
			if p == name {
				found = true
			}
		}
		if !found {
			break
		}
		p := c.Pin(name)
		m.a = append(m.a, p)
		m.kind[p] = 'a'
	}
	for i := 0; i < 8; i++ {
		m.io[i] = c.Pin(fmt.Sprintf("IO%d", i))
		m.kind[m.io[i]] = 'd'
	}
	m.ce, m.oe, m.we = c.Pin("CE"), c.Pin("OE"), c.Pin("WE")
	m.kind[m.ce], m.kind[m.oe], m.kind[m.we] = 'c', 'o', 'w'
	if m.Mem == nil {
		m.Mem = make([]byte, 1<<len(m.a))
		for i := range m.Mem {
			m.Mem[i] = byte(rng.Uint32())
		}
	}
	m.tAA, m.tACE, m.tOE, m.tOHZ, m.tCHZ = c.D("tAA"), c.D("tACE"), c.D("tOE"), c.D("tOHZ"), c.D("tCHZ")
	m.tWHZ = c.DOr("tWHZ", m.tOHZ)
	m.tAS, m.tAW, m.tWP, m.tDW = c.D("tAS"), c.D("tAW"), c.D("tWP"), c.D("tDW")
	m.tDH, m.tWR = c.DOr("tDH", 0), c.DOr("tWR", 0)
	m.weRise = -1 << 40
	m.update(s, c, 0)
}

func (m *SRAM) addr(s *Sim, c *Chip) int {
	a := 0
	for i, p := range m.a {
		a |= int(s.In(c, p)) << i
	}
	return a
}

func (m *SRAM) lastAddrChange(s *Sim, c *Chip) int64 {
	var t int64 = -1 << 40
	for _, p := range m.a {
		if l := s.LastChange(c, p); l > t {
			t = l
		}
	}
	return t
}

func (m *SRAM) update(s *Sim, c *Chip, d int64) {
	read := s.In(c, m.ce) == 0 && s.In(c, m.oe) == 0 && s.In(c, m.we) == 1
	if read {
		v := m.Mem[m.addr(s, c)]
		for i := 0; i < 8; i++ {
			s.Drive(c, m.io[i], (v>>i)&1, true, d)
		}
	} else if m.reading {
		for i := 0; i < 8; i++ {
			s.Drive(c, m.io[i], s.Outs[c.Outs[m.io[i]]].Val, false, d)
		}
	}
	m.reading = read
}

func (m *SRAM) Eval(s *Sim, c *Chip, pin int) {
	switch m.kind[pin] {
	case 'a':
		if m.weLow && s.In(c, m.ce) == 0 {
			s.Violate(c, pin, "address changed during write", 0)
		}
		s.CheckHold(c, pin, m.weRise, m.tWR, "address after write")
		if m.reading {
			m.update(s, c, m.tAA)
		}
	case 'd':
		if !m.reading {
			s.CheckHold(c, pin, m.weRise, m.tDH, "data after write")
		}
	case 'w', 'c':
		we, ce := s.In(c, m.we), s.In(c, m.ce)
		active := we == 0 && ce == 0
		if active && !m.weLow {
			m.weLow = true
			m.weFall = s.Now
			if slack := s.Now - m.lastAddrChange(s, c) - m.tAS; slack < 0 {
				s.Violate(c, pin, "tAS address setup to write", slack)
			}
		} else if !active && m.weLow {
			m.weLow = false
			m.weRise = s.Now
			if slack := s.Now - m.weFall - m.tWP; slack < 0 {
				s.Violate(c, pin, "tWP write pulse width", slack)
			}
			if slack := s.Now - m.lastAddrChange(s, c) - m.tAW; slack < 0 {
				s.Violate(c, pin, "tAW address valid to end of write", slack)
			}
			var v byte
			var last int64 = -1 << 40
			for i := 0; i < 8; i++ {
				v |= s.In(c, m.io[i]) << i
				if l := s.LastChange(c, m.io[i]); l > last {
					last = l
				}
				if n := c.Pins[m.io[i]]; n >= 0 && s.Nets[n].ContSince >= 0 {
					s.Violate(c, m.io[i], "data under contention at end of write", 0)
				}
			}
			if slack := s.Now - last - m.tDW; slack < 0 {
				s.Violate(c, pin, "tDW data setup to end of write", slack)
			}
			m.Mem[m.addr(s, c)] = v
		}
		d := m.tACE
		if m.kind[pin] == 'w' {
			d = m.tOE
			if we == 0 {
				d = m.tWHZ
			}
		} else if ce == 1 {
			d = m.tCHZ
		}
		m.update(s, c, d)
	case 'o':
		d := m.tOE
		if s.In(c, m.oe) == 1 {
			d = m.tOHZ
		}
		m.update(s, c, d)
	}
}

// ---------------------------------------------------------------- flash ROM (read only)

type ROM struct {
	a                   []int
	dq                  [8]int
	ce, oe              int
	isA                 []bool
	Mem                 []byte
	tACC, tCE, tOE, tDF int64
}

func (m *ROM) Init(s *Sim, c *Chip) {
	m.isA = make([]bool, len(c.PinNames))
	for i := 0; i < 17; i++ {
		p := c.Pin(fmt.Sprintf("A%d", i))
		m.a = append(m.a, p)
		m.isA[p] = true
	}
	for i := 0; i < 8; i++ {
		m.dq[i] = c.Pin(fmt.Sprintf("D%d", i))
	}
	m.ce, m.oe = c.Pin("CE"), c.Pin("OE")
	m.tACC, m.tCE, m.tOE, m.tDF = c.D("tACC"), c.D("tCE"), c.D("tOE"), c.D("tDF")
	if m.Mem == nil {
		m.Mem = make([]byte, 1<<17)
	}
	m.update(s, c, 0)
}

func (m *ROM) update(s *Sim, c *Chip, d int64) {
	if s.In(c, m.ce) == 0 && s.In(c, m.oe) == 0 {
		a := 0
		for i, p := range m.a {
			a |= int(s.In(c, p)) << i
		}
		v := m.Mem[a]
		for i := 0; i < 8; i++ {
			s.Drive(c, m.dq[i], (v>>i)&1, true, d)
		}
	} else {
		for i := 0; i < 8; i++ {
			s.Drive(c, m.dq[i], s.Outs[c.Outs[m.dq[i]]].Val, false, m.tDF)
		}
	}
}

func (m *ROM) Eval(s *Sim, c *Chip, pin int) {
	switch {
	case m.isA[pin]:
		m.update(s, c, m.tACC)
	case pin == m.ce:
		m.update(s, c, m.tCE)
	default:
		m.update(s, c, m.tOE)
	}
}

// ---------------------------------------------------------------- fixtures

type Const struct{}

func (Const) Init(s *Sim, c *Chip) {
	s.Drive(c, c.Pin("LO"), 0, true, 0)
	s.Drive(c, c.Pin("HI"), 1, true, 0)
}
func (Const) Eval(s *Sim, c *Chip, pin int) {}

// ClockGen's outputs are driven directly by the main loop.
type ClockGen struct{}

func (ClockGen) Init(s *Sim, c *Chip)          {}
func (ClockGen) Eval(s *Sim, c *Chip, pin int) {}

// IODev implements the I/O page (console, timer, cycle counter) with the
// same register semantics as tmc/sim.py. Read side effects and the timer
// happen at clock edges; writes take effect at the end of the write strobe.
type IODev struct {
	clk, iosel, rd, wel, weh, irq int
	a                             [8]int
	d                             [16]int
	prev                          uint8
	writing                       bool
	driving                       bool
	Input                         []byte
	Output                        []byte
	TimerPeriod, TimerCount       int64
	TimerFlag                     uint8
	cycleHi                       uint16
	dAcc                          int64
}

func (x *IODev) Init(s *Sim, c *Chip) {
	x.clk, x.iosel, x.rd, x.wel, x.weh, x.irq = c.Pin("CLK"), c.Pin("IOSEL"), c.Pin("RD"), c.Pin("WEL"), c.Pin("WEH"), c.Pin("IRQ")
	for i := 0; i < 8; i++ {
		x.a[i] = c.Pin(fmt.Sprintf("A%d", i))
	}
	for i := 0; i < 16; i++ {
		x.d[i] = c.Pin(fmt.Sprintf("D%d", i))
	}
	x.dAcc = 20000
	s.Drive(c, x.irq, 0, true, 0)
}

func (x *IODev) addr(s *Sim, c *Chip) int {
	a := 0
	for i := 0; i < 8; i++ {
		a |= int(s.In(c, x.a[i])) << i
	}
	return a &^ 1
}

func (x *IODev) value(s *Sim, a int) uint16 {
	switch a {
	case 0x00:
		if len(x.Input) > 0 {
			return uint16(x.Input[0])
		}
		return 0xFFFF
	case 0x02:
		if len(x.Input) > 0 {
			return 1
		}
		return 2 // end of input: all input is supplied up front
	case 0x06:
		return uint16(x.TimerFlag)
	case 0x08:
		return uint16(s.Cycle)
	case 0x0A:
		return x.cycleHi
	}
	return 0
}

func b2u16(b bool) uint16 {
	if b {
		return 1
	}
	return 0
}

func (x *IODev) Eval(s *Sim, c *Chip, pin int) {
	if !s.CheckOn {
		return // power-up and reset: the bus isn't meaningful yet
	}
	sel := s.In(c, x.iosel) == 0
	if pin == x.clk {
		v := s.In(c, x.clk)
		if v == 1 && x.prev == 0 {
			if sel && s.In(c, x.rd) == 0 {
				switch x.addr(s, c) {
				case 0x00:
					if len(x.Input) > 0 {
						x.Input = x.Input[1:]
					}
				case 0x08:
					x.cycleHi = uint16(s.Cycle >> 16)
				}
			}
			if x.TimerPeriod > 0 && s.Cycle >= 0 {
				x.TimerCount++
				if x.TimerCount >= x.TimerPeriod {
					x.TimerFlag = 1
					x.TimerCount = 0
				}
			}
			s.Drive(c, x.irq, x.TimerFlag, true, 5000)
		}
		x.prev = v
	}
	wr := sel && (s.In(c, x.wel) == 0 || s.In(c, x.weh) == 0)
	if x.writing && !wr {
		var v uint16
		for i := 0; i < 16; i++ {
			v |= uint16(s.In(c, x.d[i])) << i
		}
		switch x.addr(s, c) {
		case 0x00:
			x.Output = append(x.Output, byte(v))
		case 0x04:
			x.TimerPeriod, x.TimerCount = int64(v), 0
			if v == 0 {
				x.TimerFlag = 0
			}
		case 0x06:
			x.TimerFlag = 0
		}
		s.Drive(c, x.irq, x.TimerFlag, true, 5000)
	}
	x.writing = wr
	if sel && s.In(c, x.rd) == 0 {
		v := x.value(s, x.addr(s, c))
		for i := 0; i < 16; i++ {
			s.Drive(c, x.d[i], uint8(v>>i)&1, true, x.dAcc)
		}
		x.driving = true
	} else if x.driving {
		for i := 0; i < 16; i++ {
			s.Drive(c, x.d[i], s.Outs[c.Outs[x.d[i]]].Val, false, 10000)
		}
		x.driving = false
	}
}
