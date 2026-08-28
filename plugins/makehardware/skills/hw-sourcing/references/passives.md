# Passives

House preferences. **Placeholders pending the human's real standards.**

## Defaults until told otherwise

* **Size:** 0402 for dense digital, 0603 where hand-rework is plausible.
  Nothing smaller than 0402 without a reason recorded in the design docs.
* **Resistors:** thick film, 1%, E96 only where 1% is actually needed;
  otherwise E24 to keep the BOM short.
* **Ceramics:** X7R or better for anything in a control loop, decoupling or
  timing path. **Never Y5V.** Derate MLCC capacitance for DC bias — a 10 uF
  0603 at 5 V can be a third of its marked value, and this is the single most
  common quiet failure in a power design.
* **Voltage rating:** 2x the working voltage as a floor, more on anything
  behind an inductor or exposed to a transient.
* **Electrolytics:** avoid where a ceramic or polymer will do; when required,
  check the ripple current and the endurance rating at the actual operating
  temperature, not at 20 °C.

## Tolerance stack

When several passives set one number (a divider, a filter corner, a current
limit), do the worst-case stack rather than assuming nominal. If the stack
misses the requirement, tighten one part deliberately — do not tighten all of
them.
