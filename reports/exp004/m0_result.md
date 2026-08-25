# EXP-004 frozen M0 result

**Mechanical disposition:** `NULL`

- Pre-OOS implementation SHA: `680f2af101f88b55e761945390f6da020c9e9a71`
- OOS execution: one consumed run from the exact clean SHA above
- Kappa (six decimals): `0.771724`
- M1: `BLOCKED_ASOF` (not implemented or scored)
- M2+ / later rungs: unauthorized
- News slice: `NEWS_NOT_AVAILABLE` (non-gating)

## Family results

| Period | Label | family Brier skill | bootstrap 95% interval |
|---|---|---:|---:|
| validation-2024 | fixed | 0.038968 | [0.030376, 0.049594] |
| validation-2024 | twin | 0.019171 | [0.014066, 0.024590] |
| test-2025 | fixed | 0.069481 | [0.053737, 0.093018] |
| test-2025 | twin | 0.014413 | [0.008979, 0.019094] |
| test-2026-01..07 | fixed | 0.062367 | [0.040468, 0.090313] |
| test-2026-01..07 | twin | 0.010884 | [0.005397, 0.015762] |

## Primary cells

| Period | Label | Cell | rows | base rate | Brier skill | episodes | precision | clusters | recall | median lead s |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| validation-2024 | fixed | 1h_up | 8243 | 0.008492 | 0.022187 | 9 | 0.222222 | 58 | 0.034483 | 1080.0 |
| validation-2024 | fixed | 1h_down | 8243 | 0.011404 | 0.017159 | 9 | 0.111111 | 82 | 0.012195 | 1440.0 |
| validation-2024 | fixed | 4h_up | 8243 | 0.069756 | 0.062304 | 10 | 0.400000 | 164 | 0.018293 | 3540.0 |
| validation-2024 | fixed | 4h_down | 8243 | 0.076307 | 0.054223 | 6 | 0.333333 | 164 | 0.012195 | 4920.0 |
| validation-2024 | twin | 1h_up | 8243 | 0.011889 | 0.011250 | 49 | 0.122449 | 82 | 0.073171 | 1530.0 |
| validation-2024 | twin | 1h_down | 8243 | 0.014194 | 0.006473 | 56 | 0.071429 | 107 | 0.037383 | 1980.0 |
| validation-2024 | twin | 4h_up | 8243 | 0.088075 | 0.034300 | 53 | 0.245283 | 207 | 0.053140 | 2100.0 |
| validation-2024 | twin | 4h_down | 8243 | 0.089531 | 0.024660 | 54 | 0.240741 | 211 | 0.056872 | 3840.0 |
| test-2025 | fixed | 1h_up | 8439 | 0.004740 | 0.029456 | 5 | 0.000000 | 38 | 0.000000 | undefined |
| test-2025 | fixed | 1h_down | 8439 | 0.006754 | 0.028428 | 3 | 0.000000 | 49 | 0.000000 | undefined |
| test-2025 | fixed | 4h_up | 8439 | 0.040171 | 0.115425 | 5 | 0.400000 | 115 | 0.017391 | 6900.0 |
| test-2025 | fixed | 4h_down | 8439 | 0.052257 | 0.104612 | 3 | 0.666667 | 120 | 0.016667 | 7320.0 |
| test-2025 | twin | 1h_up | 8439 | 0.011139 | 0.005552 | 62 | 0.032258 | 81 | 0.024691 | 2070.0 |
| test-2025 | twin | 1h_down | 8439 | 0.013509 | 0.004280 | 71 | 0.056338 | 98 | 0.040816 | 1800.0 |
| test-2025 | twin | 4h_up | 8439 | 0.079749 | 0.022577 | 66 | 0.136364 | 213 | 0.037559 | 8430.0 |
| test-2025 | twin | 4h_down | 8439 | 0.094324 | 0.025241 | 55 | 0.272727 | 233 | 0.060086 | 7110.0 |
| test-2026-01..07 | fixed | 1h_up | 4871 | 0.005954 | 0.040716 | 2 | 0.500000 | 26 | 0.038462 | 1680.0 |
| test-2026-01..07 | fixed | 1h_down | 4871 | 0.004722 | 0.036974 | 2 | 0.000000 | 21 | 0.000000 | undefined |
| test-2026-01..07 | fixed | 4h_up | 4871 | 0.047629 | 0.095519 | 2 | 1.000000 | 79 | 0.012658 | 7500.0 |
| test-2026-01..07 | fixed | 4h_down | 4871 | 0.051324 | 0.076259 | 3 | 1.000000 | 72 | 0.013889 | 4380.0 |
| test-2026-01..07 | twin | 1h_up | 4871 | 0.010470 | 0.002728 | 20 | 0.000000 | 48 | 0.000000 | undefined |
| test-2026-01..07 | twin | 1h_down | 4871 | 0.010881 | 0.006119 | 28 | 0.142857 | 47 | 0.085106 | 2970.0 |
| test-2026-01..07 | twin | 4h_up | 4871 | 0.073907 | 0.018085 | 20 | 0.250000 | 122 | 0.040984 | 5520.0 |
| test-2026-01..07 | twin | 4h_down | 4871 | 0.079655 | 0.016604 | 27 | 0.370370 | 132 | 0.075758 | 6180.0 |

The disposition is the frozen D-033 mechanical rule. There is no pooled-period,
fixed-only, or descriptive-slice rescue and no post-OOS retuning.
