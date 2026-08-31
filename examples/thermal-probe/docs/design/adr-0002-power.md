# ADR-0002: Linear regulator for the always-on rail

## Status
Accepted — 2026-08-14

## Context
`ELE-001` caps standby draw at 40 uA on the always-on rail. The rail is 3.3 V
and carries under 12 mA even when the display is refreshing, so the question is
quiescent current, not efficiency at load.

## Decision
MCP1700 LDO from VBAT, rather than a buck converter.

## Consequences
- Quiescent current 1.6 uA typ, 4 uA max over temperature. That is 10% of the
  40 uA budget, which leaves room for the reference and the MCU's stop-mode
  leakage.
- Dropout is 178 mV at 100 mA, so the minimum usable cell voltage is 3.48 V.
  That truncates the discharge curve and costs roughly 4% of nameplate
  capacity — accepted, and it feeds the `SYS-001` analysis.
- Efficiency above 5 mA is poor. The display refresh burst runs at 12 mA for
  40 ms once a minute, which is 8 uAh per hour of waste. Negligible here, but
  if a backlight is ever added this decision has to be revisited.

## Alternatives considered
- **TPS62740 buck**: 360 nA Iq and far better burst efficiency, but it needs a
  2.2 uH inductor and 4 mm² of board the `MEC-001` envelope does not have at
  the agreed 38 mm width.
- **Direct from VBAT, no regulator**: the ADC reference would then move with
  the cell, and `ELE-003` asks for 0.2 degC over the range. Ratiometric
  measurement against a gated REF3025 was cheaper than a regulator good enough
  to be a reference.
