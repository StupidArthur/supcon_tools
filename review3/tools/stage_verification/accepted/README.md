"""Accepted stage checkpoints sealed by the reviewer after finalize.

Files in this directory are machine-readable stage seals:

```text
second_order_tank_stage_N.accepted.json
```

They are created only by ``verify_stage.py N --finalize`` after automated gates
pass and every manual gate has a valid attestation. Implementation agents must
not hand-edit these files.
"""
