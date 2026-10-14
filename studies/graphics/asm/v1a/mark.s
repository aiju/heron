; mark_n(name, count): the end of a benchmark phase. The HALT stops the
; simulator, which reads the name (r1), the count (r2), the cycles so far
; and the screen, and resumes (studies/graphics/run.py).

        .global _mark_n
        .section .text._mark_n
_mark_n:
        HALT
        RET
