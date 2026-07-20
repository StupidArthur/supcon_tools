# Optional tracked baseline directory

This is not the default state directory. The default is
`.git/stage_verification/`, as documented in the parent README.

A team that wants baselines reviewed as source artifacts may explicitly pass
this directory with `--state-dir`, review the generated file, and commit it
before implementation. Non-default state verification requires the reviewer
key. The verifier cannot prove ownership when all processes have equal local
permissions; repository review remains part of the trust model.
