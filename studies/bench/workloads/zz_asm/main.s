        .global main
main:   PUSH r7
        MOV  r1, #5381
        MOV  r2, #blob
        MOV  r3, [blob_len]
        CALL bench_hash
        MOV  r2, r1
        LEA  r1, [.lab]
        CALL bench_report
        JMP  [sp]+
.lab:   .asciz "hash"
        .align 2
