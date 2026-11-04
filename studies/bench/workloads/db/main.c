/* The inventory's run: the three tables loaded and joined, the report
   made, and its checksum and counts reported. The tables are linked in
   by the harness (workload.py makes them). */

#include <stdio.h>
#include "bench.h"
#include "db.h"

extern const unsigned char t_parts[], t_suppliers[], t_moves[];
extern unsigned t_parts_len, t_suppliers_len, t_moves_len;

int main(void)
{
    load_suppliers(t_suppliers, t_suppliers_len);
    load_parts(t_parts, t_parts_len);
    load_moves(t_moves, t_moves_len);
    report_all();
#ifdef SHOW
    /* on the host, -DSHOW: the report itself */
    printf("%.*s", report_len, report);
#endif
    bench_report("parts", nparts);
    bench_report("suppliers", nsups);
    bench_report("moves", moves_used);
    bench_report("bad", bad_fields << 24 | bad_number << 16 | bad_code << 8 | bad_supplier);
    bench_report("reorder", n_reorder);
    bench_report("matches", n_matches);
    bench_report("length", report_len);
    bench_report("report", bench_hash(BENCH_HASH0, report, report_len));
    return 0;
}
