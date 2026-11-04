"""The program the compiler compiles: C in the compiler's subset, made
here, the same every time.

It is a header of shared structs and globals, then modules: each the
same ten kinds of code a real program has (string functions, arithmetic,
a binary tree, an output buffer, a tokenizer, a hash table, sorting,
rectangles, bit twiddling, and a test driver), with its own names, its
own constants and its own choices among a few ways of writing each
function, and the arithmetic made up at random. Each function uses only
what comes before it, so the program can be cut after any function; a
module's driver calls the one before it.

The random numbers are an LCG of our own, so the text doesn't depend on
Python's random module.
"""


class Rng:
    def __init__(self, seed):
        self.s = seed & 0xFFFFFFFF

    def next(self):
        self.s = (self.s * 1103515245 + 12345) & 0xFFFFFFFF
        return self.s >> 8

    def below(self, n):
        return self.next() % n

    def pick(self, xs):
        return xs[self.below(len(xs))]

    def chance(self, percent):
        return self.below(100) < percent


HEADER = """\
/* A program for the benchmark's compiler: shared declarations. */

struct node {
    int key;
    int value;
    struct node *left;
    struct node *right;
};

struct buf {
    char *data;
    int len;
    int cap;
};

struct entry {
    char *name;
    int hash;
    int value;
    struct entry *next;
};

struct point {
    int x;
    int y;
};

struct rect {
    struct point min;
    struct point max;
    int color;
};

enum { TOK_END, TOK_NUM, TOK_ID, TOK_OP, TOK_STR };

struct node node_pool[256];
int nodes_used;
struct entry entry_pool[128];
int entries_used;
struct entry *buckets[64];
char out_space[2048];
struct buf out;
int scratch[64];
char *names[8] = { "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta" };
int primes[10] = { 2, 3, 5, 7, 11, 13, 17, 19, 23, 29 };
int checksum;
"""

WORDS = ["apple", "bridge", "candle", "dragon", "engine", "falcon", "garden",
         "harbor", "island", "jungle", "kettle", "lantern", "meadow", "needle",
         "orchard", "pepper", "quarry", "river", "saddle", "timber", "valley",
         "willow", "yonder", "zephyr"]

VARS = ["a", "b", "c", "n"]


def expression(r, depth, names):
    """Random integer arithmetic over names, depth levels deep."""
    if depth == 0 or r.chance(25):
        if r.chance(30):
            return str(r.pick([1, 2, 3, 5, 7, 8, 10, 15, 16, 31, 100, 255, 1000]))
        return r.pick(names)
    op = r.pick(["+", "-", "*", "+", "-", "&", "|", "^", "<<", ">>", "/", "%"])
    a = expression(r, depth - 1, names)
    if op in ("<<", ">>"):
        b = str(r.below(5) + 1)
    elif op in ("/", "%"):
        b = "(%s | 1)" % expression(r, depth - 1, names) if r.chance(50) else str(r.below(9) + 2)
    else:
        b = expression(r, depth - 1, names)
    if r.chance(15):
        return "%s(%s %s %s)" % (r.pick(["-", "~", "!"]), a, op, b)
    return "(%s %s %s)" % (a, op, b)


def condition(r, names):
    a = expression(r, 1, names)
    b = expression(r, 1, names)
    c = "%s %s %s" % (a, r.pick(["<", ">", "<=", ">=", "==", "!="]), b)
    if r.chance(30):
        c = "%s %s %s %s %s" % (c, r.pick(["&&", "||"]), r.pick(names),
                                r.pick(["<", ">", "!="]), r.below(50))
    return c


def strings_module(k, r):
    mul = r.pick([31, 33, 37, 65599, 131])
    s = f"""
int str_len_{k}(char *s)
{{
    int n = 0;
    while (s[n] != 0)
        n++;
    return n;
}}

int str_cmp_{k}(char *a, char *b)
{{
    while (*a && *a == *b) {{
        a++;
        b++;
    }}
    return *a - *b;
}}

void str_copy_{k}(char *d, char *s)
{{
    while ((*d++ = *s++) != 0)
        ;
}}

int str_hash_{k}(char *s)
{{
    int h = {r.below(5000) + 1};
    while (*s) {{
        h = h * {mul} + *s;
        s++;
    }}
    return h & 0x7fffffff;
}}
"""
    if r.chance(50):
        s += f"""
int str_find_{k}(char *s, int c)
{{
    int i;
    for (i = 0; s[i]; i++)
        if (s[i] == c)
            return i;
    return -1;
}}
"""
    else:
        s += f"""
int str_find_{k}(char *s, int c)
{{
    char *p = s;
    while (*p != 0 && *p != c)
        p++;
    if (*p == 0)
        return -1;
    return p - s;
}}
"""
    return s


def buffer_module(k, r):
    return f"""
void put_char_{k}(struct buf *b, int c)
{{
    if (b->data == 0) {{
        b->data = out_space;
        b->cap = 2048;
    }}
    if (b->len < b->cap - 1) {{
        b->data[b->len] = c;
        b->len++;
    }}
    checksum = checksum * {r.pick([3, 5, 7, 9])} + c;
}}

void put_str_{k}(struct buf *b, char *s)
{{
    while (*s)
        put_char_{k}(b, *s++);
}}

void put_num_{k}(struct buf *b, int n)
{{
    char digits[12];
    int i = 0;
    if (n < 0) {{
        put_char_{k}(b, '-');
        n = -n;
    }}
    do {{
        digits[i++] = '0' + n % {r.pick([10, 10, 16, 8])};
        n = n / 10;
    }} while (n > 0 && i < 11);
    while (i > 0)
        put_char_{k}(b, digits[--i]);
}}
"""


def tree_module(k, r):
    s = f"""
struct node *new_node_{k}(int key, int value)
{{
    struct node *n;
    if (nodes_used >= 256)
        nodes_used = 0;
    n = &node_pool[nodes_used];
    nodes_used++;
    n->key = key;
    n->value = value;
    n->left = 0;
    n->right = 0;
    return n;
}}

struct node *tree_insert_{k}(struct node *t, int key, int value)
{{
    if (t == 0)
        return new_node_{k}(key, value);
    if (key < t->key)
        t->left = tree_insert_{k}(t->left, key, value);
    else if (key > t->key)
        t->right = tree_insert_{k}(t->right, key, value);
    else
        t->value = t->value + value;
    return t;
}}
"""
    if r.chance(50):
        s += f"""
int tree_find_{k}(struct node *t, int key)
{{
    while (t != 0) {{
        if (key == t->key)
            return t->value;
        t = key < t->key ? t->left : t->right;
    }}
    return -1;
}}
"""
    else:
        s += f"""
int tree_find_{k}(struct node *t, int key)
{{
    if (t == 0)
        return -1;
    if (key < t->key)
        return tree_find_{k}(t->left, key);
    if (key > t->key)
        return tree_find_{k}(t->right, key);
    return t->value;
}}
"""
    s += f"""
int tree_depth_{k}(struct node *t)
{{
    int l, r;
    if (!t)
        return 0;
    l = tree_depth_{k}(t->left);
    r = tree_depth_{k}(t->right);
    return 1 + (l > r ? l : r);
}}

int tree_sum_{k}(struct node *t, int depth)
{{
    if (t == 0 || depth > 20)
        return 0;
    return t->value * {r.below(7) + 1} + tree_sum_{k}(t->left, depth + 1)
        + tree_sum_{k}(t->right, depth + 1);
}}
"""
    return s


def hash_module(k, r):
    return f"""
struct entry *lookup_{k}(char *name, int create)
{{
    int h = str_hash_{k}(name);
    struct entry *e = buckets[h & 63];
    while (e != 0) {{
        if (e->hash == h && str_cmp_{k}(e->name, name) == 0)
            return e;
        e = e->next;
    }}
    if (!create || entries_used >= 128)
        return 0;
    e = &entry_pool[entries_used++];
    e->name = name;
    e->hash = h;
    e->value = {r.below(100)};
    e->next = buckets[h & 63];
    buckets[h & 63] = e;
    return e;
}}

int count_entries_{k}(void)
{{
    int i, n = 0;
    struct entry *e;
    for (i = 0; i < 64; i++)
        for (e = buckets[i]; e; e = e->next)
            n += e->value > {r.below(50)};
    return n;
}}
"""


def sort_module(k, r):
    if r.chance(50):
        sort = f"""
void sort_{k}(int *a, int n)
{{
    int i, j, t;
    for (i = 1; i < n; i++) {{
        t = a[i];
        j = i - 1;
        while (j >= 0 && a[j] > t) {{
            a[j + 1] = a[j];
            j--;
        }}
        a[j + 1] = t;
    }}
}}
"""
    else:
        sort = f"""
void sort_{k}(int *a, int n)
{{
    int gap, i, j, t;
    for (gap = n / 2; gap > 0; gap = gap / 2)
        for (i = gap; i < n; i++)
            for (j = i - gap; j >= 0 && a[j] > a[j + gap]; j = j - gap) {{
                t = a[j];
                a[j] = a[j + gap];
                a[j + gap] = t;
            }}
}}
"""
    return sort + f"""
int bsearch_{k}(int *a, int n, int key)
{{
    int lo = 0, hi = n - 1;
    while (lo <= hi) {{
        int mid = (lo + hi) >> 1;
        if (a[mid] == key)
            return mid;
        if (a[mid] < key)
            lo = mid + 1;
        else
            hi = mid - 1;
    }}
    return -(lo + 1);
}}

void fill_{k}(int *a, int n, int seed)
{{
    int i;
    for (i = 0; i < n; i++) {{
        seed = seed * {r.pick([1103515245, 69069, 1664525, 22695477])} + {r.below(100000) | 1};
        a[i] = (seed >> {r.below(8) + 8}) & {r.pick([255, 1023, 4095])};
    }}
}}
"""


def rect_module(k, r):
    return f"""
int clamp_{k}(int v, int lo, int hi)
{{
    if (v < lo)
        return lo;
    if (v > hi)
        return hi;
    return v;
}}

int rect_area_{k}(struct rect *r)
{{
    int w = r->max.x - r->min.x, h = r->max.y - r->min.y;
    if (w <= 0 || h <= 0)
        return 0;
    return w * h;
}}

int rect_intersect_{k}(struct rect *d, struct rect *a, struct rect *b)
{{
    d->min.x = a->min.x > b->min.x ? a->min.x : b->min.x;
    d->min.y = a->min.y > b->min.y ? a->min.y : b->min.y;
    d->max.x = a->max.x < b->max.x ? a->max.x : b->max.x;
    d->max.y = a->max.y < b->max.y ? a->max.y : b->max.y;
    d->color = (a->color + b->color) & {r.pick([15, 255, 65535])};
    return rect_area_{k}(d) > 0;
}}

void rect_move_{k}(struct rect *r, int dx, int dy)
{{
    r->min.x += dx;
    r->max.x += dx;
    r->min.y = clamp_{k}(r->min.y + dy, {-r.below(100)}, {r.below(1000) + 100});
    r->max.y = clamp_{k}(r->max.y + dy, {-r.below(100)}, {r.below(1000) + 200});
}}
"""


def token_module(k, r):
    ops = r.pick(["+-*/", "+-*/%", "<>=!", "&|^~"])
    return f"""
int is_space_{k}(int c)
{{
    return c == ' ' || c == '\\t' || c == '\\n' || c == '\\r';
}}

int is_digit_{k}(int c)
{{
    return c >= '0' && c <= '9';
}}

int is_alpha_{k}(int c)
{{
    return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_';
}}

int next_token_{k}(char *s, int *pos, int *value)
{{
    int p = *pos, c, v;
    char *ops = "{ops}";
    while (is_space_{k}(s[p]))
        p++;
    c = s[p];
    if (c == 0) {{
        *pos = p;
        return TOK_END;
    }}
    if (is_digit_{k}(c)) {{
        v = 0;
        while (is_digit_{k}(s[p])) {{
            v = v * 10 + s[p] - '0';
            p++;
        }}
        *value = v;
        *pos = p;
        return TOK_NUM;
    }}
    if (is_alpha_{k}(c)) {{
        v = 0;
        while (is_alpha_{k}(s[p]) || is_digit_{k}(s[p]))
            v = v * 31 + s[p++];
        *value = v;
        *pos = p;
        return TOK_ID;
    }}
    if (c == '"') {{
        p++;
        while (s[p] && s[p] != '"')
            p++;
        *pos = p + 1;
        return TOK_STR;
    }}
    for (v = 0; ops[v]; v++)
        if (ops[v] == c) {{
            *value = v;
            *pos = p + 1;
            return TOK_OP;
        }}
    *pos = p + 1;
    *value = c;
    return TOK_OP;
}}

int count_tokens_{k}(char *s)
{{
    int pos = 0, value = 0, kind, n = 0, sum = 0;
    while ((kind = next_token_{k}(s, &pos, &value)) != TOK_END) {{
        n++;
        sum = sum + kind * value;
    }}
    return n * {r.below(1000) + 1} + (sum & 1023);
}}
"""


def bits_module(k, r):
    poly = r.pick(["0xedb88320", "0x82f63b78", "0xeb31d82e", "0xa001"])
    return f"""
int popcount_{k}(int x)
{{
    int n = 0;
    while (x != 0) {{
        x = x & (x - 1);
        n++;
    }}
    return n;
}}

int crc_byte_{k}(int crc, int byte)
{{
    int i;
    crc = crc ^ byte;
    for (i = 0; i < 8; i++)
        if (crc & 1)
            crc = ((crc >> 1) & 0x7fffffff) ^ {poly};
        else
            crc = (crc >> 1) & 0x7fffffff;
    return crc;
}}

int crc_string_{k}(char *s)
{{
    int crc = -1;
    while (*s)
        crc = crc_byte_{k}(crc, *s++);
    return ~crc;
}}

int rotate_{k}(int x, int n)
{{
    n = n & 31;
    if (n == 0)
        return x;
    return (x << n) | ((x >> (32 - n)) & ((1 << n) - 1));
}}
"""


def arith_module(k, r):
    out = []
    for j in range(r.below(3) + 2):
        names = ["a", "b", "c"]
        body = [f"int calc_{k}_{j}(int a, int b, int c)", "{", "    int x, y, i;"]
        body.append(f"    x = {expression(r, 3, names)};")
        body.append(f"    y = {expression(r, 2, names + ['x'])};")
        if r.chance(60):
            body.append(f"    if ({condition(r, names + ['x', 'y'])})")
            body.append(f"        x = {expression(r, 2, names + ['x', 'y'])};")
            body.append("    else")
            body.append(f"        y = {expression(r, 2, names + ['x', 'y'])};")
        n = r.below(6) + 2
        if r.chance(50):
            body.append(f"    for (i = 0; i < {n}; i++) {{")
        else:
            body.append(f"    i = {n};")
            body.append("    while (i-- > 0) {")
        body.append(f"        x = x + {expression(r, 2, ['x', 'y', 'i', 'a'])};")
        body.append(f"        if ({condition(r, ['x', 'y', 'i'])})")
        body.append(f"            y = y {r.pick(['+', '^', '-'])} {expression(r, 1, ['x', 'i', 'c'])};")
        body.append("    }")
        body.append(f"    return x {r.pick(['+', '^', '-'])} y;")
        body.append("}")
        out.append("\n" + "\n".join(body) + "\n")
    return "".join(out), j + 1


def driver(k, r, ncalc):
    w = [r.pick(WORDS) for _ in range(6)]
    calls = "\n".join(
        f"    total += calc_{k}_{j}({r.below(100)}, {r.below(100) - 50}, total & {r.pick([7, 15, 63])});"
        for j in range(ncalc))
    prev = f"    total += test_{k - 1}(depth - 1);\n" if k > 0 else ""
    return f"""
int test_{k}(int depth)
{{
    struct node *root = 0;
    struct rect r1, r3;
    struct entry *e;
    int a[32], i, total = 0;
    char word[16];
    if (depth <= 0)
        return 0;
    put_str_{k}(&out, "{w[0]} {w[1]}: ");
    fill_{k}(a, 32, {r.below(1000)});
    sort_{k}(a, 32);
    for (i = 0; i < 32; i++)
        root = tree_insert_{k}(root, a[i], i);
    total += tree_find_{k}(root, a[{r.below(32)}]) + tree_depth_{k}(root);
    total += tree_sum_{k}(root, 0) + bsearch_{k}(a, 32, a[{r.below(32)}]);
    for (i = 0; i < 8; i++) {{
        e = lookup_{k}(names[i], 1);
        if (e)
            e->value += i;
    }}
    total += count_entries_{k}();
    str_copy_{k}(word, "{w[2]}");
    total += str_len_{k}(word) * str_find_{k}(word, '{w[2][r.below(len(w[2]))]}');
    total += count_tokens_{k}("x{k} = {r.below(1000)} + y * (z - \\"{w[3]}\\") / {r.below(9) + 1};");
    total += crc_string_{k}("{w[4]}") ^ popcount_{k}(total) ^ rotate_{k}(total, {r.below(31) + 1});
    r1.min.x = {r.below(50)};
    r1.min.y = {r.below(50)};
    r1.max.x = {r.below(100) + 50};
    r1.max.y = {r.below(100) + 50};
    r1.color = {r.below(16)};
    rect_move_{k}(&r1, {r.below(40) - 20}, {r.below(40) - 20});
    if (rect_intersect_{k}(&r3, &r1, &r1))
        total += rect_area_{k}(&r3);
{calls}
{prev}    put_num_{k}(&out, total);
    put_char_{k}(&out, '\\n');
    return total;
}}
"""


def functions(text):
    """A module's text as its functions, each ending with a brace in
    column 0 (and the comments before them)."""
    return [f + "\n}\n" for f in text.split("\n}\n") if f.strip()]


def module(k, r):
    """The functions of module k: those that need no declarations first,
    then the rest."""
    arith, ncalc = arith_module(k, r)
    first = f"\n/* ---- module {k} ---- */\n" + strings_module(k, r)
    rest = [arith, tree_module(k, r), buffer_module(k, r), token_module(k, r),
            hash_module(k, r), sort_module(k, r), rect_module(k, r),
            bits_module(k, r), driver(k, r, ncalc)]
    return functions(first), functions("".join(rest))


def generate(lines, seed=2026):
    """The program cut after as many whole functions as fit in this many
    lines, as bytes. The first module's string functions come before the
    header, which they don't need, so that a small size still compiles
    whole functions."""
    r = Rng(seed)
    text = ""
    k = 0
    while True:
        first, rest = module(k, r)
        chunks = first + ([HEADER] if k == 0 else []) + rest
        for f in chunks:
            if (text + f).count("\n") > lines:
                return text.encode()
            text += f
        k += 1
