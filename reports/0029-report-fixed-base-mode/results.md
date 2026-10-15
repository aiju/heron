# Report 0029: generated tables

Written by `heron fixed_base report --write` ([studies/fixed_base](../../studies/fixed_base/README.md)); don't edit by hand.

## Egret

Each program's own cycles (less start-up and compiling it, as report 0017 counts them), with the whole VM assembled for 1b with `[rT + 4R]` and the JIT emitting it, against plain 1b. `r11` is the frame record in the hand-written interpreter and the JIT, `r9` the frame's slots. D32-separate, then the geometric means on D32-wide too.

| Program | Interpreter, rT = r11 | JIT, rT = r11 | JIT, rT = r9 | C loop, rT = r11 |
|---|---:|---:|---:|---:|
| bignum | -0.02% | -0.04% | -0.06% | -0.01% |
| bst | -1.79% | -1.93% | -0.49% | -0.53% |
| closures | -0.58% | -0.94% | -1.75% | -0.19% |
| crc | -0.64% | -1.21% | -1.16% | -0.21% |
| fib | -1.17% | -2.47% | -0.99% | -0.36% |
| hello | -0.12% | -0.07% | +0.01% | -0.19% |
| json | -0.63% | -0.97% | -0.37% | -0.22% |
| life | -0.01% | -0.02% | -1.68% | -0.00% |
| mandel | -0.06% | -0.11% | -1.87% | -0.02% |
| matmul | -0.32% | -0.35% | -0.44% | -0.14% |
| queens | -0.29% | -0.54% | -1.26% | -0.09% |
| richards | -1.68% | -3.32% | -0.79% | -0.49% |
| shapes | -1.36% | -1.56% | -0.48% | -0.42% |
| sieve | -0.00% | -0.02% | -2.30% | -0.00% |
| sort | -0.19% | -0.28% | -1.66% | -0.07% |
| trees | -1.50% | -2.88% | -0.75% | -0.45% |
| wordfreq | -0.14% | -0.18% | -0.86% | -0.06% |
| **geomean, D32-separate** | **-0.62%** | **-1.00%** | **-1.00%** | **-0.20%** |
| **geomean, D32-wide** | **-0.48%** | **-0.84%** | **-0.82%** | **-0.16%** |

From the scans of the baseline runs: the cycles each one-parcel form would save, as the mean over the programs, D32-separate / D32-wide. *rT: MOV, ST* is the loads and stores, three cells of draft 2's map (`MOV`, `MOVS` and the store), *+ LEA* a fourth; *every operation* adds the ALU operations and `JMP [rT + 4R]`. *[R + 4k]* is RFC 0028 10.1's other option, `MOV` and `ST` with k = 1–4 and any base; *every [R + 4..60]* is 1a's short offsets, any base and operation.

| Build, rT | rT: MOV, ST | rT: + LEA | rT: every operation | MOV/ST [R + 4k], k = 1–4 | Every [R + 4..60] word |
|---|---:|---:|---:|---:|---:|
| Interpreter, r11 | 0.54% / 0.82% | 0.62% / 0.82% | 0.62% / 0.82% | 0.85% / 1.03% | 1.86% / 1.79% |
| JIT, r11 | 0.75% / 0.36% | 0.86% / 0.54% | 0.97% / 0.63% | 1.66% / 1.20% | 2.84% / 2.22% |
| JIT, r9 | 0.87% / 0.76% | 0.99% / 0.86% | 1.00% / 0.87% | 1.66% / 1.20% | 2.84% / 2.22% |
| C loop, r11 | 0.16% / 0.20% | 0.20% / 0.26% | 0.20% / 0.26% | 0.26% / 0.23% | 1.29% / 1.44% |

Which operations the accesses through rT are. *MOVS* is a load a branch on N or Z follows directly, which reads its flags: in draft 2, where `MOV` leaves the flags alone, it would be `MOVS`.

| Build, rT | Operations |
|---|---:|
| Interpreter, r11 | ST 50%, MOV 25%, LEA 13%, MOVS 12% |
| JIT, r11 | ST 55%, MOV 23%, LEA 11%, JMP 11% |
| JIT, r9 | MOV 64%, LEA 24%, ST 11%, CMP 1% |
| C loop, r11 | ST 79%, LEA 20% |

## The Lisp

Compiled, with v1bx's tagged operations, over the compiled forms' running. *Fields at 4..60:* executed word accesses `[R + 4k]` through the best single register, which `[rT + 4R]` as it is would make one parcel. *Closure in rT:* what keeping the current closure in rT would save, net of setting it on entry (an estimate, experiments.lisp). *Runtime variables:* executed accesses to the words at 0x100–0x13F, which a globals pointer in rT would reach.

| Program | Fields at 4..60, best register: cycles saved | Free-variable reads, of instructions | Closure in rT, D32-separate | Closure in rT, D32-wide | Runtime variables, of instructions |
|---|---:|---:|---:|---:|---:|
| boyer | 0.06% | 0.01% | 0.00% | 0.00% | 3.43% |
| closures | 0.03% | 4.17% | 2.61% | 1.56% | 4.09% |
| deriv | 0.03% | 0.09% | 0.08% | 0.04% | 5.06% |
| destruct | 0.13% | 3.71% | 2.16% | 1.46% | 3.25% |
| div | 0.07% | 1.36% | 0.02% | -0.54% | 5.30% |
| fib | 0.00% | 0.04% | 0.03% | 0.01% | 3.99% |
| meta | 0.04% | 0.11% | -0.00% | -0.02% | 2.63% |
| nqueens | 0.04% | 0.02% | -0.00% | -0.01% | 2.95% |
| sieve | 0.02% | 7.08% | 8.04% | 6.06% | 2.09% |
| sort | 0.11% | 2.05% | 1.67% | 1.41% | 3.22% |
| strings | 0.13% | 1.98% | 1.63% | 1.56% | 2.10% |
| tak | 0.00% | 0.00% | 0.00% | 0.00% | 4.03% |
| **mean** | **0.06%** | **1.72%** | **1.35%** | **0.96%** | **3.51%** |

## The nucleus

Cycles per operation on D32-separate (the nucleus's own, for the scenarios that only keep it busy), and the change with the nucleus assembled for `[rT + 4R]` as it is. In the IPC paths `r6` is the other thread's TCB, `r8` the current thread's (copied from `r14` with banks), and `r14` the current thread between traps with banks. The last two columns are from the scans: the cycles a short form would save, per operation.

| Scenario, banks | Cycles | rT = r6 | rT = r8 | rT = r14 | MOV/ST [R + 4k], k = 1–4 | Every [R + 4..60] word |
|---|---:|---:|---:|---:|---:|---:|
| yield, none | 257 | -2.33% | -1.17% | +0.00% | 1 (0.4%) | 9 (3.5%) |
| yield, half | 207 | -2.90% | +0.00% | -0.97% | 2 (1.0%) | 8 (3.9%) |
| yield, full | 222 | -2.70% | +0.00% | -0.90% | 3 (1.4%) | 8 (3.6%) |
| ipc, none | 390 | -3.08% | -2.56% | +0.00% | 7 (1.8%) | 25 (6.4%) |
| ipc, half | 293 | -4.78% | -2.73% | -0.34% | 9 (3.1%) | 23 (7.8%) |
| ipc, full | 347 | -3.46% | -2.31% | +0.00% | 11 (3.2%) | 23 (6.6%) |
| preempt, none | 249 | -3.32% | -1.61% | +0.00% | 1 (0.4%) | 11 (4.4%) |
| preempt, half | 203 | -2.81% | +0.00% | -0.84% | 2 (1.0%) | 10 (4.9%) |
| preempt, full | 147 | -3.40% | +0.00% | -1.36% | 2 (1.4%) | 7 (4.8%) |
| irqdrv, none | 640 | -2.66% | -1.25% | +0.00% | 5 (0.8%) | 26 (4.1%) |
| irqdrv, half | 545 | -3.12% | -0.55% | -0.55% | 7 (1.3%) | 24 (4.4%) |
| irqdrv, full | 503 | -2.98% | -0.60% | -0.40% | 8 (1.6%) | 21 (4.2%) |
| wipc, none | 576 | -2.08% | -1.74% | +0.00% | 7 (1.2%) | 25 (4.3%) |
| wipc, half | 479 | -2.92% | -1.67% | -0.21% | 9 (1.9%) | 23 (4.8%) |
| wipc, full | 533 | -2.25% | -1.50% | +0.00% | 11 (2.1%) | 23 (4.3%) |
| wserv1, none | 1249 | -1.60% | -0.64% | +0.00% | 8 (0.6%) | 30 (2.4%) |
| wserv1, half | 1123 | -1.78% | -0.53% | +0.00% | 10 (0.9%) | 28 (2.5%) |
| wserv1, full | 1165 | -1.72% | -0.52% | +0.00% | 12 (1.0%) | 28 (2.4%) |

The nucleus's code, in bytes:

| Banks | 1b | rT = r6 | rT = r8 | rT = r14 |
|---|---:|---:|---:|---:|
| none | 1486 | 1434 (-3.5%) | 1412 (-5.0%) | 1486 (+0.0%) |
| half | 1394 | 1338 (-4.0%) | 1344 (-3.6%) | 1378 (-1.1%) |
| full | 1474 | 1420 (-3.7%) | 1424 (-3.4%) | 1462 (-0.8%) |

The accesses through `r6` are (*MOVS* as for Egret) MOV 67%, MOVS 19%, ST 14%.
