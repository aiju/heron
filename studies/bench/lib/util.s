; The benchmark's library for hand-written workloads (draft 2), in the C
; calling convention: arguments in r1-r4, the result in r1, r0-r7
; caller-saved, the return address in r7. Linked in when a workload uses
; it; the C workloads have the same functions in bench.c.
;
;   bench_putc    r1 = byte                   write a byte to the console
;   bench_puts    r1 = string                 write a NUL-terminated string
;   bench_hex     r1 = value                  write 8 lowercase hex digits
;   bench_report  r1 = label, r2 = value      write "label xxxxxxxx\n"
;   bench_hash    r1 = hash, r2 = ptr, r3 = n hash n bytes into r1
;
; bench_hash is h = (h * 33) ^ byte for every byte, started from
; BENCH_HASH0 = 5381: shifts and adds only, so a machine without a fast
; multiply doesn't pay for checking its results.

CONSOLE = 0xFFFFFF00

        .global bench_putc, bench_puts, bench_hex, bench_report, bench_hash

bench_putc:
        MOV  byte [CONSOLE], r1
        RET

bench_puts:
        MOV  r3, #CONSOLE
.loop:  MOVS r2, byte [r1]+
        BEQ  .done
        MOV  byte [r3], r2
        BRA  .loop
.done:  RET

bench_hex:
        MOV  r3, #CONSOLE
        MOV  r4, #8
.loop:  MOV  r2, r1
        LSR  r2, #28
        CMP  r2, #10
        BCC  .digit
        ADD  r2, #'a' - '0' - 10
.digit: ADD  r2, #'0'
        MOV  byte [r3], r2
        LSL  r1, #4
        DBNZ r4, .loop
        RET

bench_report:
        PUSH r7
        PUSH r2
        CALL bench_puts
        MOV  r1, #' '
        MOV  byte [CONSOLE], r1
        POP  r1
        CALL bench_hex
        MOV  r1, #10
        MOV  byte [CONSOLE], r1
        JMP  [sp]+

bench_hash:
        TST  r3, r3
        BEQ  .done
.loop:  MOV  r4, r1
        LSL  r4, #5
        ADD  r1, r4
        MOV  r4, byte [r2]+
        XOR  r1, r4
        DBNZ r3, .loop
.done:  RET
