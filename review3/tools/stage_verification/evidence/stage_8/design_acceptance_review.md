# design_acceptance_review — stage 8 design gate (UNSIGNED)

Status: **unsigned**. Each item must eventually be one of:

- `PASS` + evidence
- `FAIL` + reason
- `NOT_APPLICABLE` + justification

Do **not** provide a single overall checkbox.

## Items

| ID | Item | Status | Evidence / Reason |
|----|------|--------|-------------------|
| D1 | Fixed SVG P&ID (no React Flow fake flow) | | |
| D2 | Enter+Space keyboard selection | | |
| D3 | RuntimeName ≠ programName | | |
| D4 | Atomic `/writes` same-cycle apply | | |
| D5 | Faceplate AUTO/MAN/CAS editability | | |
| D6 | Writeback whitelist; no PV/realtime | | |
| D7 | Trend dual-axis + PV←Tank2 note | | |
| D8 | Control quality metrics + 60s window | | |
| D9 | Batch 2000 + unique temps + CSV | | |
| D10 | Downsample ≤3000 keep extrema | | |
| D11 | Realtime/Batch mutex | | |
| D12 | OPC UA external write reflected | | |
| D13 | Process/port cleanup on exit | | |
| D14 | Builtin YAML never polluted | | |
| D15 | Single-page batch discoverability | | |

Prospective: leave Status empty until business + evidence complete.
