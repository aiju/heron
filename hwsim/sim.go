// Event-driven, chip-level timing simulator.
//
// Every net is one bit. Chips are behavioural models with datasheet
// pin-to-pin delays. When an input changes, the chip re-evaluates and
// schedules each output change after the delay of the arc that caused it.
// If an output already has a later change pending, the new value replaces
// the pending one at the later time ("latest arrival wins"), so outputs
// settle no earlier than their slowest input path, as static timing
// analysis assumes.
package main

import (
	"fmt"
	"sort"
)

type PinRef struct {
	Chip int32
	Pin  int32
}

type Net struct {
	Name      string
	Val       uint8
	Last      int64 // time of the last value change (ps)
	Drivers   []int32
	Fanout    []PinRef
	Float     bool
	ContSince int64 // start of current contention, -1 if none
}

type Out struct {
	Net  int32
	Val  uint8
	En   bool
	Pend int32 // index of the latest pending event, -1 if none
	Chip int32
	Pin  int32
}

type Event struct {
	T   int64
	Seq uint64
	Out int32
	Val uint8
	En  bool
}

type Chip struct {
	Idx      int32
	Ref      string
	Type     string
	ModelN   string
	Part     string
	PinNames []string
	Kinds    []string
	Pins     []int32 // net per pin, -1 if not connected
	Outs     []int32 // output slot per pin, -1 if the pin can't drive
	Delays   map[string]int64
	M        Model
}

type Model interface {
	Init(s *Sim, c *Chip)
	Eval(s *Sim, c *Chip, pin int)
}

type Violation struct {
	Cycle int64  `json:"cycle"`
	At    int64  `json:"at_ps"`
	Chip  string `json:"chip"`
	Pin   string `json:"pin"`
	Net   string `json:"net"`
	Kind  string `json:"kind"`
	Slack int64  `json:"slack_ps"`
}

type Sim struct {
	Now    int64
	Nets   []Net
	Outs   []Out
	Chips  []*Chip
	evs    []Event
	free   []int32
	hp     []int32
	seq    uint64
	Events uint64

	Cycle      int64 // program-relative cycle number (negative during reset)
	CycleStart int64 // time of the current cycle's rising edge
	CheckOn    bool  // timing checks enabled (off while reset is held)

	Viol       []Violation
	ViolCount  map[string]int
	WorstSlack map[string]int64

	ContCount int64
	ContMax   int64
	ContTotal int64
	ContNets  map[string]int64 // net -> longest contention
	ContHist  [6]int64         // <2ns, <5ns, <10ns, <20ns, <50ns, >=50ns
}

func NewSim() *Sim {
	return &Sim{ViolCount: map[string]int{}, WorstSlack: map[string]int64{}, ContNets: map[string]int64{}}
}

// ---- event heap ordered by (T, Seq) ----

func (s *Sim) less(i, j int32) bool {
	a, b := &s.evs[i], &s.evs[j]
	if a.T != b.T {
		return a.T < b.T
	}
	return a.Seq < b.Seq
}

func (s *Sim) push(idx int32) {
	s.hp = append(s.hp, idx)
	i := len(s.hp) - 1
	for i > 0 {
		p := (i - 1) / 2
		if !s.less(s.hp[i], s.hp[p]) {
			break
		}
		s.hp[i], s.hp[p] = s.hp[p], s.hp[i]
		i = p
	}
}

func (s *Sim) pop() int32 {
	top := s.hp[0]
	n := len(s.hp) - 1
	s.hp[0] = s.hp[n]
	s.hp = s.hp[:n]
	i := 0
	for {
		l, r := 2*i+1, 2*i+2
		m := i
		if l < n && s.less(s.hp[l], s.hp[m]) {
			m = l
		}
		if r < n && s.less(s.hp[r], s.hp[m]) {
			m = r
		}
		if m == i {
			break
		}
		s.hp[i], s.hp[m] = s.hp[m], s.hp[i]
		i = m
	}
	return top
}

func (s *Sim) alloc() int32 {
	if n := len(s.free); n > 0 {
		idx := s.free[n-1]
		s.free = s.free[:n-1]
		return idx
	}
	s.evs = append(s.evs, Event{})
	return int32(len(s.evs) - 1)
}

// Schedule output slot o to take (v, en) at time t.
func (s *Sim) Schedule(o int32, t int64, v uint8, en bool) {
	out := &s.Outs[o]
	if out.Pend >= 0 {
		ev := &s.evs[out.Pend]
		if ev.T >= t {
			ev.Val, ev.En = v, en // a later change is pending: it carries the newest value
			return
		}
		if ev.Val == v && ev.En == en {
			return
		}
	} else if out.Val == v && out.En == en {
		return
	}
	idx := s.alloc()
	s.seq++
	s.evs[idx] = Event{T: t, Seq: s.seq, Out: o, Val: v, En: en}
	s.push(idx)
	out.Pend = idx
}

// Run processes all events strictly before `until`.
func (s *Sim) Run(until int64) {
	for len(s.hp) > 0 {
		idx := s.hp[0]
		ev := s.evs[idx]
		if ev.T >= until {
			return
		}
		s.pop()
		s.free = append(s.free, idx)
		s.Now = ev.T
		out := &s.Outs[ev.Out]
		if out.Pend == idx {
			out.Pend = -1
		}
		if out.Val == ev.Val && out.En == ev.En {
			continue
		}
		out.Val, out.En = ev.Val, ev.En
		s.Events++
		s.resolve(out.Net)
	}
}

func (s *Sim) resolve(n int32) {
	net := &s.Nets[n]
	var v uint8
	if len(net.Drivers) == 1 {
		o := &s.Outs[net.Drivers[0]]
		if !o.En {
			net.Float = true
			return
		}
		net.Float = false
		v = o.Val
	} else {
		cnt, conflict := 0, false
		for _, d := range net.Drivers {
			o := &s.Outs[d]
			if o.En {
				if cnt == 0 {
					v = o.Val
				} else if o.Val != v {
					conflict = true
				}
				cnt++
			}
		}
		if conflict {
			if net.ContSince < 0 {
				net.ContSince = s.Now
			}
			return // value is undefined; keep the old one
		}
		if net.ContSince >= 0 {
			s.recordContention(net, s.Now-net.ContSince)
			net.ContSince = -1
		}
		if cnt == 0 {
			net.Float = true
			return
		}
		net.Float = false
	}
	if v == net.Val {
		return
	}
	net.Val = v
	net.Last = s.Now
	for _, f := range net.Fanout {
		c := s.Chips[f.Chip]
		c.M.Eval(s, c, int(f.Pin))
	}
}

func (s *Sim) recordContention(net *Net, d int64) {
	if !s.CheckOn {
		return
	}
	s.ContCount++
	s.ContTotal += d
	if d > s.ContMax {
		s.ContMax = d
	}
	if d > s.ContNets[net.Name] {
		s.ContNets[net.Name] = d
	}
	switch {
	case d < 2000:
		s.ContHist[0]++
	case d < 5000:
		s.ContHist[1]++
	case d < 10000:
		s.ContHist[2]++
	case d < 20000:
		s.ContHist[3]++
	case d < 50000:
		s.ContHist[4]++
	default:
		s.ContHist[5]++
	}
}

// ---- helpers used by models ----

func (s *Sim) In(c *Chip, pin int) uint8 {
	n := c.Pins[pin]
	if n < 0 {
		return 0
	}
	return s.Nets[n].Val
}

func (s *Sim) Drive(c *Chip, pin int, v uint8, en bool, d int64) {
	o := c.Outs[pin]
	if o < 0 || c.Pins[pin] < 0 {
		return
	}
	s.Schedule(o, s.Now+d, v, en)
}

func (s *Sim) DriveAt(c *Chip, pin int, v uint8, en bool, t int64) {
	o := c.Outs[pin]
	if o < 0 || c.Pins[pin] < 0 {
		return
	}
	s.Schedule(o, t, v, en)
}

func (s *Sim) LastChange(c *Chip, pin int) int64 {
	n := c.Pins[pin]
	if n < 0 {
		return -1 << 40
	}
	return s.Nets[n].Last
}

func (c *Chip) Pin(name string) int {
	for i, p := range c.PinNames {
		if p == name {
			return i
		}
	}
	panic(fmt.Sprintf("%s (%s): no pin %s", c.Ref, c.Type, name))
}

func (c *Chip) D(name string) int64 {
	v, ok := c.Delays[name]
	if !ok {
		panic(fmt.Sprintf("%s (%s): no timing value %q", c.Ref, c.Part, name))
	}
	return v
}

func (c *Chip) DOr(name string, def int64) int64 {
	if v, ok := c.Delays[name]; ok {
		return v
	}
	return def
}

func (s *Sim) Violate(c *Chip, pin int, kind string, slack int64) {
	if !s.CheckOn {
		return
	}
	key := c.Ref + "." + c.PinNames[pin] + " " + kind
	s.ViolCount[key]++
	if w, ok := s.WorstSlack[key]; !ok || slack < w {
		s.WorstSlack[key] = slack
	}
	if len(s.Viol) < 200 {
		net := ""
		if c.Pins[pin] >= 0 {
			net = s.Nets[c.Pins[pin]].Name
		}
		s.Viol = append(s.Viol, Violation{s.Cycle, s.Now - s.CycleStart, c.Ref, c.PinNames[pin], net, kind, slack})
	}
}

// CheckSetup: the input on pin must have been stable for `setup` ps at a clock edge.
func (s *Sim) CheckSetup(c *Chip, pin int, setup int64, what string) {
	n := c.Pins[pin]
	if n < 0 {
		return
	}
	net := &s.Nets[n]
	if slack := s.Now - net.Last - setup; slack < 0 {
		s.Violate(c, pin, "setup "+what, slack)
	}
	if net.ContSince >= 0 {
		s.Violate(c, pin, "sampled during bus contention", 0)
	}
}

func (s *Sim) CheckHold(c *Chip, pin int, lastEdge int64, hold int64, what string) {
	if lastEdge < 0 {
		return
	}
	if slack := s.Now - lastEdge - hold; slack < 0 {
		s.Violate(c, pin, "hold "+what, slack)
	}
}

// ---- construction ----

type NetlistJSON struct {
	Nets  []string `json:"nets"`
	Chips []struct {
		Ref    string           `json:"ref"`
		Type   string           `json:"type"`
		Model  string           `json:"model"`
		Part   string           `json:"part"`
		Pins   []string         `json:"pins"`
		Kinds  []string         `json:"kinds"`
		Nets   []int32          `json:"nets"`
		Delays map[string]int64 `json:"delays"`
	} `json:"chips"`
}

func (s *Sim) NetIndex(name string) int32 {
	for i := range s.Nets {
		if s.Nets[i].Name == name {
			return int32(i)
		}
	}
	return -1
}

func (s *Sim) ChipByRef(ref string) *Chip {
	for _, c := range s.Chips {
		if c.Ref == ref {
			return c
		}
	}
	return nil
}

func (s *Sim) ViolationSummary() []map[string]interface{} {
	keys := make([]string, 0, len(s.ViolCount))
	for k := range s.ViolCount {
		keys = append(keys, k)
	}
	sort.Slice(keys, func(i, j int) bool { return s.WorstSlack[keys[i]] < s.WorstSlack[keys[j]] })
	out := []map[string]interface{}{}
	for _, k := range keys {
		out = append(out, map[string]interface{}{"what": k, "count": s.ViolCount[k], "worst_slack_ps": s.WorstSlack[k]})
	}
	return out
}
