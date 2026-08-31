# Standby current — corner sweep

ngspice, deck at `sim/standby/standby.cir`, run 2026-08-27.
Cross-checked against the closed-form leakage sum (1.6 + 42 + 1 + 12 uA typ).

| Corner | Measured | Required | Margin |
|---|---|---|---|
| 25 °C, 3.7 V nom | 12.4 µA | ≤ 40 µA | +69% |
| −30 °C, 4.2 V max | 9.1 µA | ≤ 40 µA | +77% |
| +40 °C, 3.5 V min | 31.8 µA | ≤ 40 µA | +20% |
| +60 °C, 4.2 V max (beyond spec) | 58.2 µA | ≤ 40 µA | **−46% FAIL** |

The +60 °C corner is outside the `SYS-002` range of −30 to +40 °C and is
reported for information: it shows the margin is dominated by the reference's
temperature coefficient, so a hotter variant of this product would need the
reference gated rather than always on.

**Not yet varied:** the reference could be duty-cycled with the ADC instead of
running continuously, which would remove 42 µA of the 31.8 µA worst case
outright. That is the obvious lever and it has not been modelled.

`observations` was empty on all four runs — no singular-matrix or
convergence warnings.
