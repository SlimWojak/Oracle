# EXP-000 label sensitivity: Binance-only vs consolidated index (D-022)

- old inventory: reports/exp000/clusters.json
- new inventory: reports/exp000/index_clusters.json

## Horizon 60 bars

- clusters: 1679 old vs 1658 new
- retained (overlap, compatible direction): 1630
- direction changed: 0
- removed: 49 (by year: 2020: 13, 2021: 17, 2022: 6, 2023: 7, 2024: 4, 2025: 1, 2026: 1)
- added: 17 (by year: 2020: 8, 2021: 1, 2022: 1, 2023: 4, 2024: 1, 2025: 1, 2026: 1)
- pure->mixed: 11, mixed->pure: 23
- |start shift| seconds (median/p90/max): 0.0 / 180.0 / 172800.0

## Horizon 240 bars

- clusters: 1940 old vs 1935 new
- retained (overlap, compatible direction): 1897
- direction changed: 0
- removed: 43 (by year: 2020: 7, 2021: 7, 2022: 5, 2023: 4, 2024: 10, 2025: 3, 2026: 7)
- added: 26 (by year: 2020: 17, 2021: 1, 2022: 3, 2023: 2, 2024: 1, 2026: 2)
- pure->mixed: 15, mixed->pure: 21
- |start shift| seconds (median/p90/max): 0.0 / 564.0000000000055 / 254700.0
