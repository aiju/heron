/* The sheet (sch.h): parts, wires and net labels in units, the junction
   dots where three or more things meet, the nets (for highlighting), hit
   tests, and the example circuit. Everything is a plain array, searched
   from end to end: a sheet of a few hundred things is small, and the
   searches are measured (bench.c). */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "sch.h"

Sheet sh;

Part *part_add(int type, int x, int y, int rot, const char *ref, const char *val)
{
    Part *p;
    if (sh.nparts == MAXPARTS)
        return 0;
    p = &sh.parts[sh.nparts++];
    memset(p, 0, sizeof *p);
    p->type = type;
    p->x = x;
    p->y = y;
    p->rot = rot & 3;
    strncpy(p->ref, ref, sizeof p->ref - 1);
    strncpy(p->val, val ? val : symbols[type].val, sizeof p->val - 1);
    return p;
}

void part_delete(int i)
{
    Part *p = &sh.parts[i];
    free(p->lbits[0]);
    free(p->lbits[1]);
    memmove(p, p + 1, (sh.nparts - i - 1) * sizeof *p);
    sh.nparts--;
}

Wire *wire_add(int x0, int y0, int x1, int y1)
{
    Wire *w;
    if (sh.nwires == MAXWIRES || (x0 == x1 && y0 == y1))
        return 0;
    w = &sh.wires[sh.nwires++];
    memset(w, 0, sizeof *w);
    w->x0 = x0 < x1 ? x0 : x1;
    w->x1 = x0 < x1 ? x1 : x0;
    w->y0 = y0 < y1 ? y0 : y1;
    w->y1 = y0 < y1 ? y1 : y0;
    return w;
}

void wire_delete(int i)
{
    memmove(&sh.wires[i], &sh.wires[i + 1], (sh.nwires - i - 1) * sizeof(Wire));
    sh.nwires--;
}

NetLabel *label_add(int x, int y, const char *text)
{
    NetLabel *l;
    if (sh.nlabels == MAXLABELS)
        return 0;
    l = &sh.labels[sh.nlabels++];
    memset(l, 0, sizeof *l);
    l->x = x;
    l->y = y;
    strncpy(l->text, text, sizeof l->text - 1);
    return l;
}

void sheet_clear(void)
{
    while (sh.nparts)
        part_delete(sh.nparts - 1);
    sh.nwires = 0;
    sh.nlabels = 0;
    sh.njunc = 0;
}

/* ---- pins ---- */

int part_pins(const Part *p)
{
    const Prim *q;
    int n = 0;
    for (q = symbols[p->type].prims; q->op != P_END; q++)
        n += q->op == P_PIN;
    return n;
}

void part_pin(const Part *p, int k, int *x, int *y)
{
    const Prim *q;
    for (q = symbols[p->type].prims; q->op != P_END; q++)
        if (q->op == P_PIN && k-- == 0) {
            rot_pt(p->rot, q->a, q->b, x, y);
            *x += p->x;
            *y += p->y;
            return;
        }
    *x = p->x;
    *y = p->y;
}

const char *pin_name(const Part *p, int k)
{
    static char buf[8];
    const char *s = symbols[p->type].pins;
    int n = 0;
    if (!s) {
        /* the package: the pins in the symbol's order are 1-7, then 14-8 */
        sprintf(buf, "%d", k < 7 ? k + 1 : 21 - k);
        return buf;
    }
    while (k > 0 && *s)
        if (*s++ == '|')
            k--;
    while (*s && *s != '|' && n < 7)
        buf[n++] = *s++;
    buf[n] = 0;
    return buf;
}

void part_box(const Part *p, int *x0, int *y0, int *x1, int *y1)
{
    const signed char *b = sym_box[p->type];
    int ax, ay, bx, by;
    rot_pt(p->rot, b[0], b[1], &ax, &ay);
    rot_pt(p->rot, b[2], b[3], &bx, &by);
    *x0 = p->x + (ax < bx ? ax : bx);
    *x1 = p->x + (ax < bx ? bx : ax);
    *y0 = p->y + (ay < by ? ay : by);
    *y1 = p->y + (ay < by ? by : ay);
}

/* every pin of the sheet, collected once for the searches below */
#define MAXPINS 1200
static short pin_x[MAXPINS], pin_y[MAXPINS], pin_part[MAXPINS];
static unsigned char pin_k[MAXPINS];
static int npins;

static void pins_collect(void)
{
    int i, k, n, x, y;
    npins = 0;
    for (i = 0; i < sh.nparts; i++) {
        n = part_pins(&sh.parts[i]);
        for (k = 0; k < n && npins < MAXPINS; k++) {
            part_pin(&sh.parts[i], k, &x, &y);
            pin_x[npins] = x;
            pin_y[npins] = y;
            pin_part[npins] = i;
            pin_k[npins] = k;
            npins++;
        }
    }
}

/* ---- junctions ---- */

/* the point on the wire, ends included */
int on_wire(const Wire *w, int x, int y)
{
    return x >= w->x0 && x <= w->x1 && y >= w->y0 && y <= w->y1;
}

/* how many things meet at a wire's end: wire ends 1, wires through it 2,
   pins 1 */
static int meeting(int x, int y)
{
    int j, n = 0;
    const Wire *w;
    for (j = 0, w = sh.wires; j < sh.nwires; j++, w++) {
        if (!on_wire(w, x, y))
            continue;
        if ((w->x0 == x && w->y0 == y) || (w->x1 == x && w->y1 == y))
            n++;
        else
            n += 2;
    }
    for (j = 0; j < npins; j++)
        if (pin_x[j] == x && pin_y[j] == y)
            n++;
    return n;
}

static void junction_try(int x, int y)
{
    int k;
    for (k = 0; k < sh.njunc; k++)
        if (sh.jx[k] == x && sh.jy[k] == y)
            return;
    if (sh.njunc < MAXJUNC && meeting(x, y) >= 3) {
        sh.jx[sh.njunc] = x;
        sh.jy[sh.njunc] = y;
        sh.njunc++;
    }
}

void junctions(void)
{
    int i;
    pins_collect();
    sh.njunc = 0;
    for (i = 0; i < sh.nwires; i++) {
        junction_try(sh.wires[i].x0, sh.wires[i].y0);
        junction_try(sh.wires[i].x1, sh.wires[i].y1);
    }
}

/* ---- nets: union-find over the wires (0 ..) and the pins (nwires ..) ---- */

static short uf[MAXWIRES + MAXPINS];

static int find(int a)
{
    while (uf[a] != a) {
        uf[a] = uf[uf[a]];
        a = uf[a];
    }
    return a;
}

static void unite(int a, int b)
{
    a = find(a);
    b = find(b);
    if (a != b)
        uf[a] = b;
}

static void nets(void)
{
    int i, j, nw = sh.nwires;
    pins_collect();
    for (i = 0; i < nw + npins; i++)
        uf[i] = i;
    for (i = 0; i < nw; i++) {
        const Wire *a = &sh.wires[i];
        for (j = i + 1; j < nw; j++) {
            const Wire *b = &sh.wires[j];
            if (on_wire(b, a->x0, a->y0) || on_wire(b, a->x1, a->y1) ||
                on_wire(a, b->x0, b->y0) || on_wire(a, b->x1, b->y1))
                unite(i, j);
        }
        for (j = 0; j < npins; j++)
            if (on_wire(a, pin_x[j], pin_y[j]))
                unite(i, nw + j);
    }
    for (i = 0; i < npins; i++) {
        const Part *p = &sh.parts[pin_part[i]];
        for (j = i + 1; j < npins; j++) {
            const Part *q = &sh.parts[pin_part[j]];
            /* pins on each other, and the supplies by their value: global */
            if ((pin_x[i] == pin_x[j] && pin_y[i] == pin_y[j]) ||
                ((p->type == T_GND || p->type == T_VCC) && q->type == p->type &&
                 !strcmp(p->val, q->val)))
                unite(nw + i, nw + j);
        }
    }
    /* net labels of the same name are one net */
    for (i = 0; i < sh.nlabels; i++)
        for (j = 0; j < nw; j++)
            if (on_wire(&sh.wires[j], sh.labels[i].x, sh.labels[i].y)) {
                int k, m;
                for (k = i + 1; k < sh.nlabels; k++)
                    if (!strcmp(sh.labels[i].text, sh.labels[k].text))
                        for (m = 0; m < nw; m++)
                            if (on_wire(&sh.wires[m], sh.labels[k].x, sh.labels[k].y))
                                unite(j, m);
                break;
            }
}

void net_clear(void)
{
    int i;
    for (i = 0; i < sh.nparts; i++)
        sh.parts[i].hl = 0;
    for (i = 0; i < sh.nwires; i++)
        sh.wires[i].hl = 0;
    for (i = 0; i < sh.nlabels; i++)
        sh.labels[i].hl = 0;
}

int net_highlight(int x, int y, char *buf, int n)
{
    int i, root = -1, nw = sh.nwires, count = 0, len;
    const char *name = 0;
    net_clear();
    nets();
    i = hit_wire(x, y, 1);
    if (i >= 0)
        root = find(i);
    else
        for (i = 0; i < npins; i++)
            if (pin_x[i] == x && pin_y[i] == y) {
                root = find(nw + i);
                break;
            }
    if (root < 0) {
        buf[0] = 0;
        return 0;
    }
    for (i = 0; i < nw; i++)
        if (find(i) == root) {
            sh.wires[i].hl = 1;
            count++;
        }
    for (i = 0; i < sh.nlabels; i++) {
        int j;
        for (j = 0; j < nw; j++)
            if (sh.wires[j].hl && on_wire(&sh.wires[j], sh.labels[i].x, sh.labels[i].y)) {
                sh.labels[i].hl = 1;
                name = sh.labels[i].text;
                break;
            }
    }
    /* its pins, by reference and pin name; the supplies light up */
    len = 0;
    for (i = 0; i < npins; i++)
        if (find(nw + i) == root) {
            Part *p = &sh.parts[pin_part[i]];
            if (p->type == T_GND || p->type == T_VCC) {
                p->hl = 1;
                if (!name)
                    name = p->val;
                continue;
            }
            if (len < n - 56)
                len += sprintf(buf + len, "%s%s.%s", len ? " " : "", p->ref,
                               pin_name(p, pin_k[i]));
        }
    {
        char head[40];
        int h = sprintf(head, "net %s, %d wires: ", name ? name : "?", count);
        if (h + len >= n)
            len = n - h - 1;
        memmove(buf + h, buf, len);
        memcpy(buf, head, h);
        buf[h + len] = 0;
    }
    return count;
}

/* ---- hit tests ---- */

int hit_part(int x, int y)
{
    int i, x0, y0, x1, y1;
    for (i = sh.nparts - 1; i >= 0; i--) {
        part_box(&sh.parts[i], &x0, &y0, &x1, &y1);
        if (x >= x0 - 1 && x <= x1 + 1 && y >= y0 - 1 && y <= y1 + 1)
            return i;
    }
    return -1;
}

int hit_wire(int x, int y, int tol)
{
    int i;
    for (i = sh.nwires - 1; i >= 0; i--) {
        const Wire *w = &sh.wires[i];
        if (x >= w->x0 - tol && x <= w->x1 + tol && y >= w->y0 - tol && y <= w->y1 + tol)
            return i;
    }
    return -1;
}

/* ---- the example: an oscillator from a Schmitt NAND, R1 and C1, a second
   NAND buffering it into an LED, the package's supply with its decoupling
   capacitor, and a connector for the power ---- */

#define G(v) ((v) * GRID)

static void wire_g(int gx, int gy, int x0, int y0, int x1, int y1)
{
    wire_add(G(gx + x0), G(gy + y0), G(gx + x1), G(gy + y1));
}

void example(int gx, int gy, int n)
{
    static const signed char wires[][4] = {
        {17, 16, 17, 19}, {17, 19, 20, 19},                     /* +5V to U1A's A */
        {25, 20, 27, 20}, {27, 20, 27, 25}, {25, 25, 27, 25},   /* the output back through R1 */
        {27, 20, 31, 20},                                       /* and on to U1B */
        {31, 19, 31, 21}, {31, 19, 32, 19}, {31, 21, 32, 21},   /* U1B's inputs tied */
        {18, 25, 21, 25}, {18, 21, 18, 25}, {18, 21, 20, 21},   /* R1 and C1 to U1A's B */
        {18, 25, 18, 26},
        {37, 20, 39, 20}, {43, 20, 45, 20}, {45, 24, 45, 26},   /* R2, the LED */
        {58, 10, 60, 10}, {60, 8, 60, 10}, {60, 10, 63, 10},    /* the package's supply */
        {52, 16, 50, 16}, {50, 16, 50, 18},
        {8, 40, 11, 40}, {11, 38, 11, 40}, {8, 41, 12, 41}, {12, 41, 12, 43},   /* J1 */
    };
    char r[8], s[8];
    unsigned k;
    sprintf(r, "U%dA", n);
    part_add(T_NAND, G(gx + 20), G(gy + 20), 0, r, "74HC132");
    sprintf(r, "U%dB", n);
    part_add(T_NAND, G(gx + 32), G(gy + 20), 0, r, "74HC132");
    sprintf(r, "R%d", 2 * n - 1);
    part_add(T_RES, G(gx + 21), G(gy + 25), 0, r, "470k");
    sprintf(r, "C%d", 2 * n - 1);
    part_add(T_CAP, G(gx + 18), G(gy + 26), 1, r, "1u");
    sprintf(r, "R%d", 2 * n);
    part_add(T_RES, G(gx + 39), G(gy + 20), 0, r, "330");
    sprintf(r, "D%d", n);
    part_add(T_LED, G(gx + 45), G(gy + 20), 1, r, "RED");
    sprintf(r, "U%d", n);
    part_add(T_DIP14, G(gx + 52), G(gy + 10), 0, r, "74HC132");
    sprintf(r, "C%d", 2 * n);
    part_add(T_CAP, G(gx + 63), G(gy + 10), 1, r, "100n");
    sprintf(r, "J%d", n);
    part_add(T_CONN, G(gx + 8), G(gy + 40), 0, r, "PWR");
    /* the supplies */
    k = 0;
    {
        static const signed char gnd[][2] = {{18, 29}, {45, 26}, {50, 18}, {63, 13}, {12, 43}};
        static const signed char vcc[][2] = {{17, 16}, {60, 8}, {11, 38}};
        for (k = 0; k < 5; k++) {
            sprintf(s, "#G%d", 5 * n + k);
            part_add(T_GND, G(gx + gnd[k][0]), G(gy + gnd[k][1]), 0, s, "GND");
        }
        for (k = 0; k < 3; k++) {
            sprintf(s, "#P%d", 3 * n + k);
            part_add(T_VCC, G(gx + vcc[k][0]), G(gy + vcc[k][1]), 0, s, "+5V");
        }
    }
    for (k = 0; k < sizeof wires / sizeof wires[0]; k++)
        wire_g(gx, gy, wires[k][0], wires[k][1], wires[k][2], wires[k][3]);
    label_add(G(gx + 29), G(gy + 20), "OSC");
    label_add(G(gx + 18), G(gy + 23), "RC");
}
