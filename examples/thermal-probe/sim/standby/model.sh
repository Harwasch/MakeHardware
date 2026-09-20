#!/usr/bin/env bash
# Stand-in for sim/standby/standby.cir. Closed-form leakage sum at the +40 C
# corner: reference (duty-cycled), LDO quiescent, comparator, and the wake-up
# time the reference's bypass cap sets. Emits ngspice .meas format.
set -euo pipefail
ref_duty="$1"; c_ref_nf="$2"; ldo_gated="${3:-0}"; comparator="${4:-default}"

i_ref=42.0; i_ldo=1.6; i_leak=1.0
i_cmp=2.6; [ "${comparator}" = "TS881" ] && i_cmp=1.0

# A smaller reference bypass settles faster and costs a little average current:
# it is recharged from flat on every wake instead of holding between them.
i=$(awk -v r="${i_ref}" -v d="${ref_duty}" -v l="${i_ldo}" -v c="${i_cmp}" \
        -v k="${i_leak}" -v g="${ldo_gated}" -v cn="${c_ref_nf}" \
        'BEGIN{ ldo  = (g==1 ? l*0.1 : l);
                recharge = (d>=1 ? 0 : 0.6 * (100/cn - 1) * 0.55);
                printf "%.4f", r*d + ldo + c + k + recharge }')
# Wake-up: the reference settles through its bypass cap; gating the LDO adds
# its own start-up on top.
w=$(awk -v c="${c_ref_nf}" -v d="${ref_duty}" -v g="${ldo_gated}" \
        'BEGIN{ t = (d>=1 ? 0.4 : 0.42*c); if (g==1) t += 36.8; printf "%.4f", t }')

printf 'Doing analysis at TEMP = 40.000000 and TNOM = 27.000000\n'
printf 'i_standby_ua        =  %e\n' "${i}"
printf 'wake_ms             =  %e\n' "${w}"
printf 'Total analysis time (seconds) = 0.01\n'
