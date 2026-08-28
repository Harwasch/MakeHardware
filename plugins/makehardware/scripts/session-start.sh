#!/usr/bin/env bash
# SessionStart hook — brief the agent on the state of the world.
#
# WHY THIS EXISTS, given the environment already has a setup script:
#
#   The setup script runs ONCE, at environment build time, and its result is a
#   filesystem snapshot. It cannot tell a session anything, because by the time
#   a session runs it finished days ago.
#
#   This runs at the start of EVERY session, and SessionStart is one of the few
#   hooks whose stdout is added to the agent's context. That is the whole point:
#   the agent begins the session already knowing which tools are degraded and
#   where the project stands, instead of discovering it three tool calls in or,
#   worse, planning work that depends on something that is not installed.
#
# It deliberately does NOT:
#   * export anything — each Bash tool call is a fresh shell, so exports here
#     would be dead code
#   * start Xvfb — hw-kicad-up calls hw-display-start itself, and starting a
#     display every session for the sessions that never open KiCad is waste
#   * touch the network or install anything
#
# Silent when there is nothing worth saying.
set -uo pipefail

STATUS=/opt/makehardware/status.json
lines=()

# --- toolchain health -------------------------------------------------------
if [ -f "${STATUS}" ]; then
    degraded=$(jq -r '.components | to_entries[]
                      | select(.value.state != "PASS" and .value.state != "SKIP")
                      | "\(.key)=\(.value.state)"' "${STATUS}" 2>/dev/null \
               | paste -sd' ' -)
    if [ -n "${degraded}" ]; then
        lines+=("Toolchain degraded: ${degraded} — run hw-doctor before planning work that needs them.")
    fi
elif [ -d /opt/hw-py ]; then
    lines+=("No /opt/makehardware/status.json — this environment predates the current setup script. Run hw-doctor to see what is actually installed.")
fi

# --- project state ----------------------------------------------------------
if [ -f plan.yaml ] && command -v plan-render >/dev/null 2>&1; then
    if ! plan_summary=$(plan-render plan.yaml --summary 2>&1); then
        lines+=("plan.yaml does not validate — fix it before starting work: $(printf '%s' "${plan_summary}" | head -3 | paste -sd' ' -)")
    else
        headline=$(printf '%s' "${plan_summary}" | head -1)
        ready=$(printf '%s' "${plan_summary}" | sed -n '/Ready to start now/,$p' \
                | grep -E '^\s+- ' | sed 's/^ *- /  /')
        blocked=$(printf '%s' "${plan_summary}" | sed -n '/Blocked/,/^$/p' \
                  | grep -E '^\s+\*?\s*[A-Z]' | sed 's/^ *\*\? */  /')
        lines+=("Plan: ${headline}")
        [ -n "${blocked}" ] && lines+=("Blocked:" "${blocked}")
        [ -n "${ready}" ]   && lines+=("Ready to start:" "${ready}")
    fi
fi

if [ ${#lines[@]} -gt 0 ]; then
    printf 'MakeHardware — session brief\n'
    printf '%s\n' "${lines[@]}"
fi
exit 0
