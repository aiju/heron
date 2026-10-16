/* Physical pages and address spaces.
 *
 * Physical pages are counted: a page shared between processes is freed
 * when the last one lets go. Pages beyond RAM (a device's registers, VRAM)
 * aren't counted.
 *
 * A process's address space is its context of the page map, which is its
 * page table: there's nothing in memory behind it (RFC 0029, 10 suggests
 * page tables in RAM as the truth once there are more processes than
 * contexts; with 127 there's no need yet). The kernel keeps, for each of
 * the three regions of the space (the image and heap, the mmap area, the
 * stack), the lowest and highest page mapped, so it only looks at those
 * when a process goes. A context is cleared once, the first time it's
 * used, and left clear by vm_destroy. */

#include "kernel.h"

u32 ram_size;
static u32 npages;
static u8 refcnt[4096];         /* up to 16 MB of RAM */
static u16 free_stack[4096];
static u32 nfree;
static u8 ctx_clean[MAX_PROCS];

/* the regions' page spans, per process: lo[r] > hi[r] when empty */
static u16 span_lo[MAX_PROCS][3];
static u16 span_hi[MAX_PROCS][3];

void mem_init(u32 first_free)
{
    u32 pg;
    ram_size = INFO_RAM;
    if (ram_size > 16u << 20)
        ram_size = 16u << 20;
    npages = ram_size >> PAGE_SHIFT;
    for (pg = npages; pg-- > (first_free >> PAGE_SHIFT);) {
        refcnt[pg] = 0;
        free_stack[nfree++] = pg;
    }
    for (pg = 0; pg < MAX_PROCS; pg++) {
        int r;
        for (r = 0; r < 3; r++) {
            span_lo[pg][r] = 0xFFFF;
            span_hi[pg][r] = 0;
        }
    }
    /* context 0 is the idle one: nothing mapped */
    map_clear(0, PAGES_PER_CTX);
    ctx_clean[0] = 1;
}

/* a page full of zeros: page_zero (entry.s) stores four words at a time */
static void zero_page(u32 pa)
{
    page_zero(PHYS(pa));
}

u32 page_alloc(void)
{
    u32 pg;
    if (!nfree)
        return 0;
    pg = free_stack[--nfree];
    refcnt[pg] = 1;
    zero_page(pg << PAGE_SHIFT);
    return pg << PAGE_SHIFT;
}

void page_ref(u32 pa)
{
    u32 pg = pa >> PAGE_SHIFT;
    if (pg < npages)
        refcnt[pg]++;
}

void page_free(u32 pa)
{
    u32 pg = pa >> PAGE_SHIFT;
    if (pg >= npages)
        return;
    if (refcnt[pg] == 0)
        panic("freeing free page %x", pa);
    if (--refcnt[pg] == 0)
        free_stack[nfree++] = pg;
}

u32 pages_free(void)
{
    return nfree;
}

static int region(u32 page)
{
    if (page < (MMAP_BASE >> PAGE_SHIFT))
        return 0;
    if (page < (MMAP_TOP >> PAGE_SHIFT))
        return 1;
    return 2;
}

static void ensure_clean(struct proc *p)
{
    if (!ctx_clean[p->pid]) {
        map_clear(p->pid * PAGES_PER_CTX, PAGES_PER_CTX);
        ctx_clean[p->pid] = 1;
    }
}

u32 pte_of(struct proc *p, u32 va)
{
    return map_get(p->pid * PAGES_PER_CTX + (va >> PAGE_SHIFT));
}

void pte_set(struct proc *p, u32 va, u32 pte)
{
    u32 page = va >> PAGE_SHIFT;
    int r = region(page);
    ensure_clean(p);
    ctx_clean[p->pid] = 1;
    if (pte & PTE_V) {
        if (page < span_lo[p->pid][r])
            span_lo[p->pid][r] = page;
        if (page > span_hi[p->pid][r])
            span_hi[p->pid][r] = page;
    }
    map_set(p->pid * PAGES_PER_CTX + page, pte);
}

static u32 prot_bits(u32 prot)
{
    u32 b = PTE_V;
    if (prot & PROT_WRITE)
        b |= PTE_W;
    if (prot & PROT_EXEC)
        b |= PTE_X;
    return b;
}

static int range_ok(u32 va, u32 n)
{
    if (va & (PAGE - 1))
        return 0;
    if (va < PAGE || va >= USER_TOP || n > (USER_TOP - va) >> PAGE_SHIFT)
        return 0;
    return 1;
}

int vm_alloc(struct proc *p, u32 va, u32 n, u32 prot)
{
    u32 i;
    if (!range_ok(va, n))
        return -EINVAL;
    ensure_clean(p);
    for (i = 0; i < n; i++)
        if (pte_of(p, va + i * PAGE) & PTE_V)
            return -EEXIST;
    if (n > nfree)
        return -ENOMEM;
    for (i = 0; i < n; i++) {
        u32 pa = page_alloc();
        pte_set(p, va + i * PAGE, pa | prot_bits(prot));
    }
    p->pages += n;
    return 0;
}

int vm_free(struct proc *p, u32 va, u32 n)
{
    u32 i;
    if (!range_ok(va, n))
        return -EINVAL;
    for (i = 0; i < n; i++) {
        u32 a = va + i * PAGE;
        u32 pte = pte_of(p, a);
        if (pte & PTE_V) {
            page_free(pte & ~(PAGE - 1));
            map_set(p->pid * PAGES_PER_CTX + (a >> PAGE_SHIFT), 0);
            p->pages--;
        }
    }
    return 0;
}

int vm_protect(struct proc *p, u32 va, u32 n, u32 prot)
{
    u32 i;
    if (!range_ok(va, n))
        return -EINVAL;
    for (i = 0; i < n; i++) {
        u32 a = va + i * PAGE;
        u32 pte = pte_of(p, a);
        if (!(pte & PTE_V))
            return -EFAULT;
        pte_set(p, a, (pte & ~(PAGE - 1)) | prot_bits(prot));
    }
    return 0;
}

int vm_map_phys(struct proc *p, u32 va, u32 pa, u32 n, u32 prot)
{
    u32 i;
    if (!range_ok(va, n) || (pa & (PAGE - 1)) || (pa & WINDOW))
        return -EINVAL;
    ensure_clean(p);
    for (i = 0; i < n; i++)
        if (pte_of(p, va + i * PAGE) & PTE_V)
            return -EEXIST;
    for (i = 0; i < n; i++) {
        u32 a = pa + i * PAGE;
        page_ref(a);
        pte_set(p, va + i * PAGE, a | prot_bits(prot));
    }
    p->pages += n;
    return 0;
}

int vm_share(struct proc *from, u32 from_va, struct proc *to, u32 to_va, u32 n, u32 prot)
{
    u32 i;
    if (!range_ok(from_va, n) || !range_ok(to_va, n))
        return -EINVAL;
    ensure_clean(to);
    for (i = 0; i < n; i++) {
        if (!(pte_of(from, from_va + i * PAGE) & PTE_V))
            return -EFAULT;
        if (pte_of(to, to_va + i * PAGE) & PTE_V)
            return -EEXIST;
    }
    for (i = 0; i < n; i++) {
        u32 pa = pte_of(from, from_va + i * PAGE) & ~(PAGE - 1);
        page_ref(pa);
        pte_set(to, to_va + i * PAGE, pa | prot_bits(prot));
    }
    to->pages += n;
    return 0;
}

/* Unmap everything, and leave the context clear. */
void vm_destroy(struct proc *p)
{
    int r;
    u32 base = p->pid * PAGES_PER_CTX;
    for (r = 0; r < 3; r++) {
        u32 pg;
        u32 hi = span_hi[p->pid][r];
        for (pg = span_lo[p->pid][r]; pg <= hi; pg++) {
            u32 pte = map_get(base + pg);
            if (pte & PTE_V) {
                page_free(pte & ~(PAGE - 1));
                map_set(base + pg, 0);
            }
        }
        span_lo[p->pid][r] = 0xFFFF;
        span_hi[p->pid][r] = 0;
    }
    p->pages = 0;
}

/* Copy into another process's memory (or this one's, through the
 * window); need_w asks for the pages to be writable to it. */
int copy_to_proc(struct proc *p, u32 va, const void *src, u32 n, int need_w)
{
    const char *s = src;
    while (n) {
        u32 off = va & (PAGE - 1);
        u32 chunk = PAGE - off;
        u32 pte;
        int e;
        if (chunk > n)
            chunk = n;
        if (va >= USER_TOP)
            return -EFAULT;
        pte = pte_of(p, va);
        if (!(pte & PTE_V) || (need_w && !(pte & PTE_W)))
            return -EFAULT;
        e = ucopy(PHYS((pte & ~(PAGE - 1)) | off), s, chunk);
        if (e)
            return e;
        va += chunk;
        s += chunk;
        n -= chunk;
    }
    return 0;
}

int copy_from_proc(struct proc *p, u32 va, void *dst, u32 n)
{
    char *d = dst;
    while (n) {
        u32 off = va & (PAGE - 1);
        u32 chunk = PAGE - off;
        u32 pte;
        int e;
        if (chunk > n)
            chunk = n;
        if (va >= USER_TOP)
            return -EFAULT;
        pte = pte_of(p, va);
        if (!(pte & PTE_V))
            return -EFAULT;
        e = ucopy(d, PHYS((pte & ~(PAGE - 1)) | off), chunk);
        if (e)
            return e;
        va += chunk;
        d += chunk;
        n -= chunk;
    }
    return 0;
}
