# EXP-002 construct gate

**Harness status:** NULL

Mechanical harness output only; this is not a ledger verdict.

- Target: `book_hitting_usd`
- Backstop mass is reported only and never enters Spearman.
- Target-attached rows: 172

## Family statistics

| Window | F_vs_oi | F_vs_path | F_static | integrity |
|---|---:|---:|---:|---|
| construct-dev | 0.016482877791505174 | 0.0201438975790343 | 0.02132787944062582 | True |
| construct-val | 0.06066966899717216 | -0.06522311844176425 | 0.09860051384153778 | True |

## Floor

- Locked: `False`
- Floor: `None`

## PASS clauses

- `construct_val_F_vs_oi_ge_floor`: False
- `construct_val_F_vs_oi_ci95_excludes_zero`: False
- `construct_val_F_vs_path_ge_floor`: False
- `construct_val_F_vs_path_ci95_excludes_zero`: False
- `shape_gate`: True
- `stability_sep_oct`: True
- `stability_nov_dec`: True
- `F_static_not_above_F_vs_oi`: False

## NULL reasons

- construct-dev floor not locked
