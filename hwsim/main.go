package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"math/rand"
	"os"
	"sort"
	"strings"
	"time"
)

var rng = rand.New(rand.NewSource(1))

func randBit() uint8 { return uint8(rng.Intn(2)) }

type Config struct {
	Netlist     string              `json:"netlist"`
	Roms        map[string]string   `json:"roms"`
	RamImage    string              `json:"ram_image"`
	RamLo       string              `json:"ram_lo"`
	RamHi       string              `json:"ram_hi"`
	RamDump     string              `json:"ram_dump"`
	ZeroRegs    bool                `json:"zero_regs"`
	PeriodPS    int64               `json:"period_ps"`
	WeStart     float64             `json:"we_start"`
	WeEnd       float64             `json:"we_end"`
	ResetCycles int64               `json:"reset_cycles"`
	MaxCycles   int64               `json:"max_cycles"`
	Input       string              `json:"input"`
	Seed        int64               `json:"seed"`
	FetchTrace  int                 `json:"fetch_trace"`
	TraceFrom   int64               `json:"trace_from"`
	TraceTo     int64               `json:"trace_to"`
	TraceFile   string              `json:"trace_file"`
	TraceBuses  map[string][]string `json:"trace_buses"`
	Out         string              `json:"out"`
}

type Result struct {
	Halted      bool                     `json:"halted"`
	Reason      string                   `json:"reason"`
	Cycles      int64                    `json:"cycles"`
	ResetCycles int64                    `json:"reset_cycles"`
	Output      []int                    `json:"output"`
	RegsA       []int                    `json:"regs_a"`
	RegsB       []int                    `json:"regs_b"`
	PC          int                      `json:"pc"`
	Flags       map[string]int           `json:"flags"`
	Fetches     [][3]int64               `json:"fetches"`
	FetchCount  int64                    `json:"fetch_count"`
	FetchHash   uint64                   `json:"fetch_hash"`
	Violations  []Violation              `json:"violations"`
	ViolSummary []map[string]interface{} `json:"violation_summary"`
	ViolTotal   int                      `json:"violation_total"`
	Contention  map[string]interface{}   `json:"contention"`
	Events      uint64                   `json:"events"`
	WallSeconds float64                  `json:"wall_seconds"`
	PeriodPS    int64                    `json:"period_ps"`
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "hwsim:", err)
		os.Exit(2)
	}
}

func main() {
	if len(os.Args) != 2 {
		fmt.Fprintln(os.Stderr, "usage: hwsim config.json")
		os.Exit(2)
	}
	var cfg Config
	data, err := os.ReadFile(os.Args[1])
	must(err)
	must(json.Unmarshal(data, &cfg))
	if cfg.WeStart == 0 {
		cfg.WeStart, cfg.WeEnd = 0.5, 0.875
	}
	if cfg.ResetCycles == 0 {
		cfg.ResetCycles = 4
	}
	rng = rand.New(rand.NewSource(cfg.Seed))

	var nl NetlistJSON
	data, err = os.ReadFile(cfg.Netlist)
	must(err)
	must(json.Unmarshal(data, &nl))

	s := NewSim()
	// Preload memories before Init so the first evaluation sees them.
	pre := map[string][]byte{}
	for ref, path := range cfg.Roms {
		b, err := os.ReadFile(path)
		must(err)
		pre[ref] = b
	}
	if cfg.RamImage != "" {
		img, err := os.ReadFile(cfg.RamImage)
		must(err)
		lo, hi := make([]byte, 32768), make([]byte, 32768)
		for i := 0; i+1 < len(img) && i < 65536; i += 2 {
			lo[i/2], hi[i/2] = img[i], img[i+1]
		}
		pre[cfg.RamLo], pre[cfg.RamHi] = lo, hi
	}
	if cfg.ZeroRegs {
		for _, ref := range []string{"U_RFAL", "U_RFAH", "U_RFBL", "U_RFBH"} {
			pre[ref] = make([]byte, 32768)
		}
	}
	s.Build(&nl, pre)
	io := s.ChipByRef("X_IO").M.(*IODev)
	io.Input = []byte(cfg.Input)

	clk := s.ChipByRef("X_CLK")
	oCLK, oWE, oRST := clk.Outs[clk.Pin("CLK")], clk.Outs[clk.Pin("WEWIN")], clk.Outs[clk.Pin("RESET")]
	net := func(name string) int32 {
		i := s.NetIndex(name)
		if i < 0 {
			must(fmt.Errorf("no net %s", name))
		}
		return i
	}
	val := func(n int32) int { return int(s.Nets[n].Val) }
	busVal := func(ns []int32) int {
		v := 0
		for i, n := range ns {
			v |= int(s.Nets[n].Val) << i
		}
		return v
	}
	busNets := func(prefix string, n int, start int) []int32 {
		out := make([]int32, n)
		for i := range out {
			out[i] = net(fmt.Sprintf("%s%d", prefix, i+start))
		}
		return out
	}
	nHALT, nEND, nLDIR := net("uHALT_n"), net("uEND_n"), net("uLDIR_n")
	nMRST, nMIRQ, nRST, nI := net("MODERST"), net("MODEIRQ"), net("RESET_n"), net("IFLAG")
	nADDR, nDBUS := busNets("ADDR", 16, 0), busNets("DBUS", 16, 0)
	nPC := busNets("PC", 15, 1)

	var trace *bufio.Writer
	traceBuses := map[string][]int32{}
	var traceNames []string
	if cfg.TraceFile != "" {
		f, err := os.Create(cfg.TraceFile)
		must(err)
		defer f.Close()
		trace = bufio.NewWriter(f)
		defer trace.Flush()
		for name, nets := range cfg.TraceBuses {
			ns := []int32{}
			for _, n := range nets {
				ns = append(ns, net(n))
			}
			traceBuses[name] = ns
			traceNames = append(traceNames, name)
		}
		sort.Strings(traceNames)
	}

	T := cfg.PeriodPS
	ws, we := int64(float64(T)*cfg.WeStart), int64(float64(T)*cfg.WeEnd)
	res := Result{PeriodPS: T, ResetCycles: cfg.ResetCycles}
	start := time.Now()
	progStart := int64(-1)
	var fetchHash uint64 = 1469598103934665603
	s.Outs[oRST].Val = 0
	s.Schedule(oRST, 0, 0, true)
	s.Run(1)
	for cyc := int64(0); ; cyc++ {
		t0 := cyc * T
		s.CycleStart = t0
		if progStart >= 0 {
			s.Cycle = cyc - progStart
		} else {
			s.Cycle = -1
		}
		s.Schedule(oCLK, t0, 1, true)
		s.Schedule(oCLK, t0+T/2, 0, true)
		s.Schedule(oWE, t0+ws, 1, true)
		s.Schedule(oWE, t0+we, 0, true)
		if cyc == cfg.ResetCycles {
			s.Schedule(oRST, t0+T/4, 1, true)
		}
		s.CheckOn = cyc > cfg.ResetCycles
		s.Run(t0 + T)

		// ---- end of cycle: observe ----
		if trace != nil && s.Cycle >= cfg.TraceFrom && s.Cycle <= cfg.TraceTo {
			var b strings.Builder
			fmt.Fprintf(&b, "%d", s.Cycle)
			for _, name := range traceNames {
				fmt.Fprintf(&b, " %s=%X", name, busVal(traceBuses[name]))
			}
			b.WriteString("\n")
			trace.WriteString(b.String())
		}
		if val(nLDIR) == 0 && progStart >= 0 {
			a, w := busVal(nADDR), busVal(nDBUS)
			res.FetchCount++
			fetchHash = (fetchHash ^ uint64(s.Cycle)<<32 ^ uint64(a)<<16 ^ uint64(w)) * 1099511628211
			if len(res.Fetches) < cfg.FetchTrace {
				res.Fetches = append(res.Fetches, [3]int64{s.Cycle, int64(a), int64(w)})
			}
		}
		if progStart < 0 && val(nRST) == 1 && val(nMRST) == 1 && val(nEND) == 0 {
			progStart = cyc + 1
			// the fetch in the reset sequence's last cycle belongs to cycle -1
			a, w := busVal(nADDR), busVal(nDBUS)
			res.FetchCount++
			fetchHash = (fetchHash ^ uint64(0xFFFFFFFF)<<32 ^ uint64(a)<<16 ^ uint64(w)) * 1099511628211
			if cfg.FetchTrace > 0 {
				res.Fetches = append(res.Fetches, [3]int64{-1, int64(a), int64(w)})
			}
		}
		if progStart >= 0 && val(nHALT) == 0 && val(nMRST) == 0 && val(nMIRQ) == 0 {
			if val(nI) == 0 || io.TimerPeriod == 0 {
				res.Halted, res.Reason = true, "HALT"
				res.Cycles = s.Cycle + 1
				break
			}
		}
		if progStart >= 0 && s.Cycle+1 >= cfg.MaxCycles {
			res.Reason = "cycle limit"
			res.Cycles = s.Cycle + 1
			break
		}
		if progStart < 0 && cyc > cfg.ResetCycles+50 {
			res.Reason = "reset sequence never finished"
			break
		}
	}
	res.WallSeconds = time.Since(start).Seconds()
	res.Output = make([]int, len(io.Output))
	for i, b := range io.Output {
		res.Output[i] = int(b)
	}
	res.FetchHash = fetchHash
	res.Events = s.Events
	readRegs := func(lo, hi string) []int {
		l, h := s.ChipByRef(lo).M.(*SRAM), s.ChipByRef(hi).M.(*SRAM)
		out := make([]int, 16)
		for i := range out {
			out[i] = int(l.Mem[i]) | int(h.Mem[i])<<8
		}
		return out
	}
	res.RegsA = readRegs("U_RFAL", "U_RFAH")
	res.RegsB = readRegs("U_RFBL", "U_RFBH")
	res.PC = busVal(nPC) << 1
	res.Flags = map[string]int{}
	for _, f := range []string{"NFLAG", "ZFLAG", "CFLAG", "VFLAG", "IFLAG"} {
		res.Flags[f] = val(net(f))
	}
	res.Violations = s.Viol
	res.ViolSummary = s.ViolationSummary()
	for _, n := range s.ViolCount {
		res.ViolTotal += n
	}
	type kv struct {
		K string
		V int64
	}
	worst := []kv{}
	for k, v := range s.ContNets {
		worst = append(worst, kv{k, v})
	}
	sort.Slice(worst, func(i, j int) bool { return worst[i].V > worst[j].V })
	if len(worst) > 12 {
		worst = worst[:12]
	}
	wl := []map[string]interface{}{}
	for _, w := range worst {
		wl = append(wl, map[string]interface{}{"net": w.K, "max_ps": w.V})
	}
	res.Contention = map[string]interface{}{
		"count": s.ContCount, "max_ps": s.ContMax, "total_ps": s.ContTotal,
		"histogram": map[string]int64{"<2ns": s.ContHist[0], "2-5ns": s.ContHist[1], "5-10ns": s.ContHist[2],
			"10-20ns": s.ContHist[3], "20-50ns": s.ContHist[4], ">=50ns": s.ContHist[5]},
		"worst_nets": wl,
	}
	if cfg.RamDump != "" {
		lo, hi := s.ChipByRef(cfg.RamLo).M.(*SRAM), s.ChipByRef(cfg.RamHi).M.(*SRAM)
		dump := make([]byte, 65536)
		for i := 0; i < 32768; i++ {
			dump[2*i], dump[2*i+1] = lo.Mem[i], hi.Mem[i]
		}
		must(os.WriteFile(cfg.RamDump, dump, 0o644))
	}
	out, err := json.MarshalIndent(res, "", " ")
	must(err)
	if cfg.Out != "" {
		must(os.WriteFile(cfg.Out, out, 0o644))
	} else {
		os.Stdout.Write(out)
	}
}

// buildWithMemories builds the simulator, handing preloaded contents to
// memory models before their Init runs.
func (s *Sim) Build(nl *NetlistJSON, pre map[string][]byte) {
	s.Nets = make([]Net, len(nl.Nets))
	for i, n := range nl.Nets {
		s.Nets[i] = Net{Name: n, ContSince: -1, Float: true}
	}
	for ci, cj := range nl.Chips {
		c := &Chip{Idx: int32(ci), Ref: cj.Ref, Type: cj.Type, ModelN: cj.Model, Part: cj.Part,
			PinNames: cj.Pins, Kinds: cj.Kinds, Pins: cj.Nets, Delays: cj.Delays}
		c.Outs = make([]int32, len(c.Pins))
		for p := range c.Pins {
			c.Outs[p] = -1
			k := c.Kinds[p]
			if c.Pins[p] >= 0 && (k == "out" || k == "tri" || k == "io") {
				o := int32(len(s.Outs))
				s.Outs = append(s.Outs, Out{Net: c.Pins[p], Val: 0, En: k == "out", Pend: -1, Chip: int32(ci), Pin: int32(p)})
				c.Outs[p] = o
				s.Nets[c.Pins[p]].Drivers = append(s.Nets[c.Pins[p]].Drivers, o)
			}
			if c.Pins[p] >= 0 && (k == "in" || k == "io") {
				s.Nets[c.Pins[p]].Fanout = append(s.Nets[c.Pins[p]].Fanout, PinRef{int32(ci), int32(p)})
			}
		}
		c.M = NewModel(c)
		if mem, ok := pre[c.Ref]; ok {
			switch m := c.M.(type) {
			case *ROM:
				m.Mem = make([]byte, 1<<17)
				copy(m.Mem, mem)
			case *SRAM:
				m.Mem = make([]byte, 1<<15)
				copy(m.Mem, mem)
			}
		}
		s.Chips = append(s.Chips, c)
	}
	for _, c := range s.Chips {
		c.M.Init(s, c)
	}
}
