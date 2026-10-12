/* Structs, unions, struct copies, by-value arguments and results, malloc. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct point { int x, y; };
struct rect { struct point a, b; char tag; };
union word { unsigned u; unsigned char b[4]; unsigned short h[2]; };

struct node {
    int value;
    struct node *next;
};

typedef struct { char name[12]; int age; short score; } person;

static struct point mkpoint(int x, int y)
{
    struct point p;
    p.x = x;
    p.y = y;
    return p;
}

static struct point add(struct point p, struct point q)
{
    p.x += q.x;
    p.y += q.y;
    return p;
}

static int area(struct rect r)
{
    return (r.b.x - r.a.x) * (r.b.y - r.a.y);
}

static struct node *push(struct node *list, int v)
{
    struct node *n = malloc(sizeof *n);
    n->value = v;
    n->next = list;
    return n;
}

static struct node *reverse(struct node *l)
{
    struct node *r = 0;
    while (l) {
        struct node *n = l->next;
        l->next = r;
        r = l;
        l = n;
    }
    return r;
}

person people[3] = {{"ann", 31, 90}, {"bob", 25, -3}, {"carol", 47, 1234}};

int main(void)
{
    struct point p = mkpoint(3, 4), q;
    struct rect r;
    union word w;
    struct node *list = 0, *n;
    person tmp;
    int i, sum;
    q = add(p, mkpoint(10, 20));
    printf("q = %d %d, p = %d %d\n", q.x, q.y, p.x, p.y);
    r.a = p;
    r.b = q;
    r.tag = 'R';
    printf("area %d %c %d\n", area(r), r.tag, (int)sizeof(struct rect));
    w.u = 0x11223344;
    printf("union %x %x %x %x\n", w.b[0], w.b[3], w.h[0], w.h[1]);
    w.b[1] = 0xff;
    printf("union %x\n", w.u);
    for (i = 0; i < 10; i++)
        list = push(list, i * i);
    list = reverse(list);
    sum = 0;
    for (n = list; n; n = n->next)
        sum = sum * 3 + n->value;
    printf("list %d\n", sum);
    while (list) {
        n = list->next;
        free(list);
        list = n;
    }
    for (i = 0; i < 3; i++)
        printf("%s %d %d\n", people[i].name, people[i].age, people[i].score);
    tmp = people[0];
    people[0] = people[2];
    people[2] = tmp;
    printf("%s %s %d\n", people[0].name, people[2].name, (int)sizeof(person));
    {
        struct point pts[5];
        struct point *pp;
        for (i = 0; i < 5; i++) {
            pts[i].x = i;
            pts[i].y = i * i;
        }
        sum = 0;
        for (pp = pts; pp < pts + 5; pp++)
            sum += pp->x * 100 + pp->y;
        printf("pts %d\n", sum);
    }
    {
        char *a = malloc(100), *b = malloc(200), *c;
        strcpy(a, "hello");
        free(a);
        c = malloc(50);
        strcpy(c, "world");
        strcpy(b, c);
        printf("%s %s\n", b, c);
        c = realloc(c, 1000);
        printf("%s\n", c);
    }
    return 0;
}
