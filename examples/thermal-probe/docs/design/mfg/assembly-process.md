# Assembly and test process

For a first article run of 25. Written so someone who has not seen the board
can run it, because at 25 pieces that is who will.

## Assembly

1. **Solder paste**, top side only, from the supplied stencil. 0.12 mm
   stainless, 1:1 apertures except `DS1`, which is reduced to 90% — the
   display frame bridged on the prototype at 1:1.
2. **Place** the ten top-side parts. Seven are polarised; the assembly drawing
   marks pin 1 with a red dot and the position file carries the rotations.
3. **Reflow** to the paste manufacturer's SAC305 profile. Peak 245 °C, time
   above liquidus 60–90 s.
4. **Hand-fit** `BT1` and the probe lead after reflow. The cell clip is
   through-hole and the lead is a crimp.
5. **Clean** — no-clean paste, so this is a rinse only where flux sits under
   `DS1`.

## Test, in this order

Each step gates the next. A board that fails one does not move on.

1. **Shorts.** VBUS to GND and V3P3 to GND, both above 10 kΩ, before power is
   applied. A short here is a paste defect and the board goes back.
2. **Rails, unloaded.** VBUS 5.0 V ±5%, V3P3 3.30 V ±2%, VREF 2.500 V ±0.1%.
   VREF is the one that matters — it is the measurement reference and
   `ELE-003` depends on it.
3. **Standby current.** Under 40 µA at 3.3 V with the display off, which is
   the `ELE-001` budget. Expect 32–36 µA; anything above 40 µA is a fail and
   is nearly always `U3` fitted in the wrong orientation.
4. **Probe channel.** A 100 Ω precision resistor in place of the probe should
   read 0.00 °C ±0.20 °C. That is `ELE-003` end to end.
5. **Two-point calibration** at 0 °C and 60 °C, written to EEPROM. Record both
   raw readings against the serial number.
6. **Soak.** Four hours at −25 °C, then repeat step 4. The freezer is the
   product's whole environment and the first prototype passed at bench
   temperature and failed cold.

## What is not decided yet

* **The test fixture.** Steps 1–4 need a bed of nails and there is no layout to
  build one against. Estimated at £400 and not quoted.
* **Who calibrates.** Step 5 needs a stirred bath the assembly house does not
  have. Either it comes back in house or the process needs rewriting around a
  dry block.
