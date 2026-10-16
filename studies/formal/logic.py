"""Bits and words that are either known or symbolic.

A bit is a Python bool when it is known and a z3 Boolean term when it
isn't. The operations fold constants as they build terms, so a design run
with mostly known values (the control store, the opcode) builds terms only
for the data. A word is a z3 bit-vector term, or a Python int when known
(`known`); `bits()` and `word()` convert between the two.
"""

import z3

BV1, BV0 = z3.BitVecVal(1, 1), z3.BitVecVal(0, 1)


def is_known(x):
    return x is True or x is False


def NOT(x):
    if x is True:
        return False
    if x is False:
        return True
    if z3.is_not(x):
        return x.arg(0)
    return z3.Not(x)


def _gather(xs, unit, zero):
    """The terms of an AND (unit True, zero False) or OR (the reverse):
    None if a term or a complementary pair makes it `zero`."""
    out, seen = [], {}
    for x in xs:
        if x is zero:
            return None
        if x is unit:
            continue
        neg = z3.is_not(x)
        key = (x.arg(0) if neg else x).get_id()
        pol = seen.get(key)
        if pol is None:
            seen[key] = neg
            out.append(x)
        elif pol != neg:
            return None
    return out


def AND(*xs):
    out = _gather(xs, True, False)
    if out is None:
        return False
    if not out:
        return True
    if len(out) == 1:
        return out[0]
    return z3.And(*out)


def OR(*xs):
    out = _gather(xs, False, True)
    if out is None:
        return True
    if not out:
        return False
    if len(out) == 1:
        return out[0]
    return z3.Or(*out)


def XOR(a, b):
    if is_known(a):
        return NOT(b) if a else b
    if is_known(b):
        return NOT(a) if b else a
    if a.eq(b):
        return False
    return z3.Xor(a, b)


def EQ(a, b):
    return NOT(XOR(a, b))


def ITE(c, a, b):
    if c is True:
        return a
    if c is False:
        return b
    if a is b or (not is_known(a) and not is_known(b) and a.eq(b)):
        return a
    if a is True and b is False:
        return c
    if a is False and b is True:
        return NOT(c)
    if a is True:
        return OR(c, b)
    if a is False:
        return AND(NOT(c), b)
    if b is True:
        return OR(NOT(c), a)
    if b is False:
        return AND(c, a)
    return z3.If(c, a, b)


_solver = None
_consts = {}


def const_value(x):
    """True or False if bit x is the same whatever its variables are (the
    simplifier, else the solver, decides), else None."""
    if is_known(x):
        return x
    key = x.get_id()
    if key in _consts:
        return _consts[key][1]
    y = z3.simplify(x)
    if z3.is_true(y) or z3.is_false(y):
        v = z3.is_true(y)
    else:
        global _solver
        if _solver is None:
            _solver = z3.Solver()
        _solver.push()
        _solver.add(x)
        can1 = _solver.check() == z3.sat
        _solver.pop()
        _solver.push()
        _solver.add(z3.Not(x))
        can0 = _solver.check() == z3.sat
        _solver.pop()
        v = None if can1 and can0 else can1
    _consts[key] = (x, v)
    return v


def boolterm(x):
    """A bit as a z3 Boolean term."""
    if x is True:
        return z3.BoolVal(True)
    if x is False:
        return z3.BoolVal(False)
    return x


# ---- words -------------------------------------------------------------

_from_bits = {}      # id of a word term built by word() -> its bits


def known(x):
    """A word's value if it is known (an int or a bit-vector numeral)."""
    if isinstance(x, int):
        return x
    if z3.is_bv_value(x):
        return x.as_long()
    return None


def word(bits):
    """Bits (least significant first) as a bit-vector term."""
    v = 0
    for i, b in enumerate(bits):
        if b is True:
            v |= 1 << i
        elif b is not False:
            break
    else:
        return z3.BitVecVal(v, len(bits))
    parts = [BV1 if b is True else BV0 if b is False else z3.If(b, BV1, BV0)
             for b in reversed(bits)]
    w = parts[0] if len(parts) == 1 else z3.Concat(*parts)
    _from_bits[w.get_id()] = (w, list(bits))
    return w


def bits(x, width=None):
    """A word (term or int) as bits, least significant first."""
    if isinstance(x, int):
        return [bool((x >> i) & 1) for i in range(width)]
    width = x.size()
    hit = _from_bits.get(x.get_id())
    if hit is not None:
        return list(hit[1])
    if not z3.is_bv_value(x):
        x = z3.simplify(x)
        hit = _from_bits.get(x.get_id())
        if hit is not None:
            return list(hit[1])
    if z3.is_bv_value(x):
        v = x.as_long()
        return [bool((v >> i) & 1) for i in range(width)]
    return [z3.Extract(i, i, x) == BV1 for i in range(width)]


def bits_value(bs):
    """The int a list of known bits spells, or None."""
    v = 0
    for i, b in enumerate(bs):
        if b is True:
            v |= 1 << i
        elif b is not False:
            return None
    return v
