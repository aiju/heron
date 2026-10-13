# The Egret language

Egret is made up for this study: a small, friendly object language in the
space between Smalltalk, Ruby and Python. Everything is an object and every
operation is a message send; blocks are closures that can return from the
method that made them; integers grow into big integers when they need to.
The core library ([lib/prelude.eg](lib/prelude.eg)) is Egret, on top of
primitives in C ([vm/prims.c](vm/prims.c)).

```ruby
class Point
  def init(x, y)
    @x = x
    @y = y
  end
  attr x, y
  def +(other) = Point(@x + other.x, @y + other.y)
  def to_s = "({@x}, {@y})"
end

p = Point(1, 2) + Point(3, 4)
print(p, 2 ** 100)                    # (4, 6) 1267650600228229401496703205376
evens = (1..10).select { |n| n % 2 == 0 }
print(evens.map { |n| n * n })        # [4, 16, 36, 64, 100]
```

## Values

| Literal | Class | Notes |
|---|---|---|
| `42`, `-7`, `0xFFFF`, `1_000` | `Int` | 31-bit SmallInts, and big integers past that, transparently |
| `"text {expr}"` | `String` | byte strings; `{...}` interpolates (`\{` for a brace), `\n \t \" \\` |
| `:name` | `Symbol` | interned |
| `[1, 2, 3]` | `List` | growable |
| `["a": 1, "b": 2]`, `[:]` | `Map` | hash maps that keep insertion order |
| `1..10`, `1..<10` | `Range` | inclusive and exclusive |
| `{ |x| x + 1 }`, `do |x| ... end` | `Block` | closures |
| `nil`, `true`, `false` | `Nil`, `Bool` | `nil` and `false` are the only false values |

`Int` arithmetic: `+ - * / % **`, with `/` and `%` rounding towards minus
infinity; bitwise `& | ^ ~ << >>` on any size of integer (two's
complement); comparisons `< <= > >= == != <=>`.

## Statements

```ruby
if x > 0 then "positive" elif x < 0 then "negative" else "zero" end
while i < n do i += 1 end            # do is optional at the end of the line
for x in [1, 2, 3] ... end           # any Collection, or a Range
break, continue
try ... catch e ... end              # e is the error, an Error (e.message)
raise("message")                     # or raise(an_error)
return x
```

`if`, `while` and `try` are expressions: `y = if c then 1 else 2 end`.
Compound assignment: `+= -= *= /= %= &= |= ^= <<= >>=`. `and`, `or`,
`not` short-circuit; `==` on `nil`, `true` and `false` is identity.

## Methods and classes

```ruby
def gcd(a, b) = if b == 0 then a else gcd(b, a % b) end

def print_all(*items)               # the rest of the arguments, as a List
  items.each { |x| print(x) }
end

class Square < Shape
  def init(side)
    super("square")                 # Shape's init
    @side = side
  end
  attr side                         # def side = @side
  def area = @side * @side
end

s = Square(3)                       # Square.new(3): new makes the object and calls init
```

- A `def` at the top level is a method of `Object`, so it can be called
  anywhere without a receiver.
- Variables assigned at the top level are globals; variables in a method
  or a block are local to it.
- `@name` is an instance variable of `self`; `self.name` and a bare `name`
  are sends.
- Operators are methods: `def +(other)`, `def ==(other)`, and `[]` and
  `[]=` for indexing, with one argument and two.
- `super` with no arguments passes the current method's own; `super(...)`
  passes others.
- A class is an object: `Point.name`, `p.class`, `p.is_a?(Point)`,
  `p.respond_to?(:x)`. Classes can be reopened, and methods added to
  built-in classes (`class Int  def double = self * 2  end`).

## Blocks

A block is a closure. It sees and can assign the variables around it,
and `return` in a block returns from the method the block was made in
(non-local return), as in Smalltalk:

```ruby
def first_negative(xs)
  xs.each { |x| if x < 0 then return x end }
  nil
end
```

A block in a variable is called with `f(x)` or `f.call(x)`. A method taking
a block takes it as its last argument: `xs.each { |x| ... }` passes the
block to `each(body)`.

## The library

The prelude and the primitives give `Object` (`print`, `inspect`, `to_s`,
`assert`, `nil?`, `is_a?`, `respond_to?`, `send`, `raise`), `Int`
(`times`, `upto`, `downto`, `abs`, `gcd`, `sqrt`, `min`, `max`, `chr`),
`String` (`size`, `[]`, `byte_at`, `ord`, `chars`, `split`, `lines`,
`reverse`, `index`, `contains?`, `starts_with?`, `ends_with?`, `replace`,
`upper`, `lower`, `strip`, `ljust`, `rjust`, `zfill`, `to_i`, `to_sym`,
`+`, `*`), and, for `List`, `Map` and `Range` alike, `Collection`:
`each`, `each_with_index`, `map`, `select`, `reject`, `reduce`, `sum`,
`find`, `any?`, `all?`, `count`, `contains?`, `min`, `max`, `uniq`,
`sort`, `sort_by`, `sort_with`, `to_list`. Lists add `push` (or `<<`),
`pop`, `insert`, `delete_at`, `first`, `last`, `take`, `drop`, `index`,
`join`, `reverse`, `copy`; maps `keys`, `values`, `items`, `get(k,
default)`, `has?`, `delete`.

Input is what follows a line `__END__` on the console: `gets` reads a
line, `read_all` the rest.

## Running

The VM reads a program from the console, prelude first:

```sh
heron egret run studies/egret/programs/richards.eg            # on the simulated machine
heron egret run --host studies/egret/programs/richards.eg     # on the host build
heron egret run --variant jit studies/egret/programs/fib.eg   # with the JIT
```

A program whose first line is `#!repl` runs each statement as it's read
and prints its value; `#!check` only compiles the program.
