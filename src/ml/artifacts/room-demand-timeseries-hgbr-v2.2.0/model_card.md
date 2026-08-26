# room-demand-timeseries-hgbr-v2.2.0

## Purpose

Predict paid rooms sold for D+1 through D+10 from historical daily facts available at the end of the cutoff date.

## Training and validation

- Training source: synthetic Walkerhill-structured world A daily facts
- Training rows: 227,790
- Validation WAPE: 17.5320%
- Baseline improvement: 10.3979%
- September observed values used: no

## Limitations

- This is synthetic-data validation, not evidence of actual Walkerhill accuracy.
- Runtime feature parity and dynamic service E2E must pass before service approval.
- Known TEST-A/B results are reproduction evidence only; a newly generated Hidden Test is required for independent performance evidence.
