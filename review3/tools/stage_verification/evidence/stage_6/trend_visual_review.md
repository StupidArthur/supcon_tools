# trend_visual_review — stage 6 human gate (UNSIGNED)

Status: **unsigned** — requirements only; do not treat this file as an attestation.

## Required visual evidence (when business UI exists)

Reviewers must capture screenshots/recordings that show:

1. **dual-axis** chart is recognizable (left vs right scales)
2. **previous run** series uses secondary / muted styling
3. **series toggle** controls work for each curve
4. Parameter event timeline shows **pending** / **applied** / **failed** distinctly
5. Binding note visible: `pid2.PV ← tank_2.level`
6. After **stale**, plotting stops appending and flow/trend animation freezes

## Left axis

- Tank 2 level (`tank_2.level`)
- SV (`pid2.SV`)

## Right axis

- MV (`pid2.MV`)
- Valve current opening (`valve_1.current_opening`)

## Notes

- This gate is prospective until stage 6 UI is implemented.
- Signing / finalize is deferred until batch 7 lifecycle / baselines.
