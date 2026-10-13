; ramp_rows(job): for now the C version
        .global _ramp_rows
        .section .text._ramp_rows
_ramp_rows:
        BRA  _ramp_rows_c
