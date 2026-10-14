; The microkernel write: r1 writes of the first r2 bytes of a line, each a
; call to the console server (thread 1). The text is in a shared page
; (put there once), so a call carries only where and how much.
        .include "sys.inc"
        .org 0
start:  MOV  r8, r1
        MOV  r10, r2
        ; the line into the shared page
        LEA  r1, [line]
        MOV  r2, #SHARED + 4096
        MOV  r3, #(line_end - line) / 4
.cp:    MOV  r4, [r1]+
        ST   r4, [r2]+
        DEC  r3
        BNE  .cp
.loop:  MOV  r1, #1
        MOV  r2, #SHARED + 4096
        MOV  r3, r10
        SWI  #SYS_CALL
        DEC  r8
        BNE  .loop
        SWI  #SYS_EXIT
        .align 4
        .include "line.inc"
