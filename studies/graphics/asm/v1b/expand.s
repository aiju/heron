; expand_rows(job): for now the C version
        .global _expand_rows
        .section .text._expand_rows
_expand_rows:
        BRA  _expand_rows_c
