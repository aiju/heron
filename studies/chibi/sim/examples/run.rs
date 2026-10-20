//! Run a RAM image on the machine from power-on, without Python: for
//! profiling the engine. `cargo run --release --example run -- STORE RAM`
//! (sim.py's `dump` writes both).

use chibi_sim::{Config, Machine, Status, Store};

fn main() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 3 {
        return Err("usage: run STORE.bin RAM.bin [stretch]".into());
    }
    let read = |p: &str| std::fs::read(p).map_err(|e| format!("{p}: {e}"));
    let store = Store::from_image(&read(&args[1])?)?;
    let cfg = Config {
        stretch: args.get(3).is_some_and(|s| s == "stretch"),
        ..Config::default()
    };
    let mut m = Machine::new(store, cfg);
    m.load(0, &read(&args[2])?);
    let t = std::time::Instant::now();
    let st = m.run(u64::MAX, 1 << 40)?;
    let dt = t.elapsed().as_secs_f64();
    let c = m.cpu.cycles;
    println!(
        "{st:?}: {} instructions, {c} cycles, {} ticks in {dt:.3} s, {:.1} M cycles/s",
        m.cpu.instructions,
        m.cpu.ticks,
        c as f64 / dt / 1e6
    );
    print!(
        "{}",
        String::from_utf8_lossy(&m.board.fixture.out)
            .chars()
            .rev()
            .take(60)
            .collect::<String>()
            .chars()
            .rev()
            .collect::<String>()
    );
    if st != Status::Halted {
        return Err("didn't stop".into());
    }
    Ok(())
}
