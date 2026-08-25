# EXP-005 — taker-flow variance-compression replication

- Run status: `COMPLETE_VALID`
- Mechanical disposition: **NULL**
- Pre-OOS implementation SHA: `7fa0709011f451d0fc5ef95b5f4b5e7baf8152ed`
- Frozen development-state SHA-256: `317bdc2926b35163f2da10a3ecb12d09e5ec8e87e87b3dbc363e0de9ffa1e8c2`
- Comparison: `M0_FLOW` versus freshly fitted `M0_COMMON` on identical rows.
- OOS refit: no.
- News: `NEWS_NOT_AVAILABLE` (non-gating).

## Family relative Brier skill

| Period | Fixed | Twin |
|---|---:|---:|
| validation | 0.001785 | -0.000040 |
| test_2025 | 0.002180 | 0.000309 |
| test_2026 | 0.001346 | -0.000305 |

The frozen all-period/all-family rule is mechanical; no rescue is permitted.
M1 remains `BLOCKED_ASOF`; no later rung is authorized.
