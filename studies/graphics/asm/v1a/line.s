; line_run(job): for now the C version
        .global _line_run
        .section .text._line_run
_line_run:
        BRA  _line_run_c
