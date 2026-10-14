//! Page reference statistics, for sizing an MMU's translation cache (the
//! kernel study, studies/kernel). Off unless a tool turns it on; then
//! every instruction fetch and every data access outside the I/O page is
//! counted by virtual page.
//!
//! For each stream (fetches, data, both) it keeps an LRU stack of pages
//! and a histogram of stack distances, so one run gives the misses of a
//! fully associative LRU translation cache of every size: the references
//! at distance n or more, plus the first touches. It also runs a few
//! direct-mapped caches, which is what a cache in plain SRAM would be.

/// The direct-mapped cache sizes simulated.
pub const DIRECT_SIZES: [usize; 4] = [16, 64, 256, 1024];

pub struct Lru {
    stack: Vec<u32>,
    /// references by stack distance (0: the page used last)
    pub hist: Vec<u64>,
    /// first touches
    pub cold: u64,
    pub refs: u64,
    /// direct-mapped caches, tags per entry (u32::MAX: empty), and misses
    direct: Vec<(Vec<u32>, u64)>,
}

impl Lru {
    fn new() -> Lru {
        Lru {
            stack: Vec::new(),
            hist: Vec::new(),
            cold: 0,
            refs: 0,
            direct: DIRECT_SIZES
                .iter()
                .map(|&n| (vec![u32::MAX; n], 0))
                .collect(),
        }
    }

    #[inline]
    fn touch(&mut self, page: u32) {
        self.refs += 1;
        if self.stack.first() == Some(&page) {
            if self.hist.is_empty() {
                self.hist.push(0);
            }
            self.hist[0] += 1;
            return;
        }
        for (tags, misses) in &mut self.direct {
            let i = page as usize & (tags.len() - 1);
            if tags[i] != page {
                tags[i] = page;
                *misses += 1;
            }
        }
        match self.stack.iter().position(|&p| p == page) {
            Some(i) => {
                if self.hist.len() <= i {
                    self.hist.resize(i + 1, 0);
                }
                self.hist[i] += 1;
                self.stack[..=i].rotate_right(1);
            }
            None => {
                self.cold += 1;
                self.stack.insert(0, page);
            }
        }
    }

    /// Misses of a fully associative LRU cache of n entries.
    pub fn misses(&self, n: usize) -> u64 {
        self.cold + self.hist.iter().skip(n).sum::<u64>()
    }

    /// Misses of the direct-mapped caches, by DIRECT_SIZES.
    pub fn direct_misses(&self) -> Vec<u64> {
        self.direct.iter().map(|(_, m)| *m).collect()
    }

    /// Pages touched.
    pub fn pages(&self) -> usize {
        self.stack.len()
    }
}

pub struct PageStats {
    pub shift: u32,
    pub fetch: Lru,
    pub data: Lru,
    pub both: Lru,
    pub stores: u64,
    /// instructions whose page differs from the previous instruction's
    pub fetch_page_changes: u64,
    last_fetch: u32,
}

impl PageStats {
    pub fn new(shift: u32) -> PageStats {
        PageStats {
            shift,
            fetch: Lru::new(),
            data: Lru::new(),
            both: Lru::new(),
            stores: 0,
            fetch_page_changes: 0,
            last_fetch: u32::MAX,
        }
    }

    #[inline]
    pub fn fetch(&mut self, pc: u32) {
        let p = pc >> self.shift;
        if p != self.last_fetch {
            self.fetch_page_changes += 1;
            self.last_fetch = p;
        }
        self.fetch.touch(p);
        self.both.touch(p);
    }

    #[inline]
    pub fn data(&mut self, a: u32, store: bool) {
        if a >= 0xFFFF_0000 {
            return;
        }
        let p = a >> self.shift;
        self.stores += store as u64;
        self.data.touch(p);
        self.both.touch(p);
    }
}
