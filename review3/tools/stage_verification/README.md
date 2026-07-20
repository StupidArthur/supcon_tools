# 二阶水箱阶段验收器

本目录把阶段 0–8 的施工边界和退出门禁变成机器可读规则。实现 agent 不再用文字回报证明完成，而是反复运行统一验证命令。

## 0. 根目录约定

```text
Git root:      仓库 `.git` 所在目录（本 monorepo 为 supcon_tools/）
Project root:  review3/（含 tools/stage_verification、playbook、config-tool）
Verifier root: review3/tools/stage_verification/
```

`--repo-root` 始终指向 **Project root**，不是 Git root。快照与命令 cwd 只覆盖 project root，不会把同仓库 sibling 项目纳入范围。

## 1. 验收者先准备 acceptance suite 和 baseline

派发阶段前，验收者必须先创建 manifest 中列出的 `locked_acceptance_paths`。阶段 5–8 的 reviewer suite 路径分别位于：

```text
tools/stage_verification/acceptance/stage_5/
tools/stage_verification/acceptance/stage_6/
tools/stage_verification/acceptance/stage_7/
tools/stage_verification/acceptance/stage_8/
```

这些文件现在故意不存在：必须由验收者结合阶段契约编写，不能让实现 agent 自己定义验收标准。缺少任一路径时 `--record-baseline` 会拒绝执行，表示该阶段尚不可派发。广泛 glob 还会累计锁定 baseline 时已经存在的 Python、前端和 Go 测试；agent 可以新增普通自测，但不能删改已接受回归测试。

验收者随后记录基线：

```powershell
$env:STAGE_VERIFICATION_REVIEW_KEY = '<long-random-reviewer-secret>'
python tools/stage_verification/verify_stage.py 5 `
  --record-baseline `
  --acceptance-mode prospective
```

阶段 0–4 使用 `--acceptance-mode retrospective`；阶段 5–8 使用 `prospective`。默认 baseline 位于 **Git root** 下的 `.git/stage_verification/`。在当前 Codex 工作区中，验收者可获批写入 `.git`，实现 agent 只能读取，因此适用于未提交且累计脏的仓库。实现 agent 不得使用 `--record-baseline`、`--force-baseline` 或 `--state-dir`。

也可以显式使用验收者拥有的仓库外目录；非默认 `--state-dir` 在验证时必须提供与 baseline 信任锚一致的 reviewer key。需要通过代码评审管理 baseline 的团队，可以把 `--state-dir` 指向仓库内目录并先提交文件。

## 2. 实现 agent 只运行验证

```powershell
python tools/stage_verification/verify_stage.py 5
```

验证内容包括：

- 必读文档、阶段必需产物和必须保留的旧入口；
- 相对阶段 baseline 的修改文件白名单和绝对禁改路径；
- 新增的下一阶段符号，既有符号计数不会误报；
- manifest、规范、验证器和累计 acceptance tests 的哈希；
- manifest 中所有命令的退出码、输出和超时；Windows 超时会终止命令进程树；
- 相对 baseline 的 trailing whitespace 和冲突标记，包括 untracked 新文件；
- `git diff HEAD --check` 作为辅助信息，不让累计旧脏误伤阶段判定。

reviewer key 会在启动每个 npm、Go、Wails、Python 或其他被测命令前从子进程环境删除。

JSON 结果应写到 verifier state 目录或仓库外，避免下一轮 scope 多出一个文件：

```powershell
python tools/stage_verification/verify_stage.py 5 --format json `
  --json-output .git/stage_verification/stage-5-result.json
```

## 3. 人工门禁

阶段 2、6、7、8 含普通测试无法证明的视觉或真实端到端门禁。自动检查全绿后仍返回 `NEEDS_MANUAL`（退出码 3）。验收者检查后使用同一 reviewer key 签署：

```powershell
$env:STAGE_VERIFICATION_REVIEW_KEY = '<same-reviewer-secret>'
python tools/stage_verification/verify_stage.py 2 --attest pid_visual_review `
  --reviewer '<name>' --evidence '<screenshot/path/notes>'
python tools/stage_verification/verify_stage.py 2
```

attestation 绑定 baseline、manifest、签署时的最终文件树和自动检查状态摘要。签署后任何被纳入快照的文件变化都会使它失效；`--evidence` 若指向文件，还会绑定该文件的 SHA-256。只有验收者最终运行时提供 reviewer key；实现 agent 不持有该 key，因此只能得到 `NEEDS_MANUAL`。

全部自动门禁与人工签署通过后，验收者封存阶段：

```powershell
python tools/stage_verification/verify_stage.py 4 `
  --finalize `
  --reviewer '<name>'
python tools/stage_verification/verify_stage.py 4 --verify-accepted
python tools/stage_verification/verify_all.py --check-config
python tools/stage_verification/verify_all.py --accepted-through 4
```

## 信任边界

这是 tamper-evident 工作流，不是针对同权限恶意进程的密码学沙箱：

- baseline fingerprint 能发现直接或意外改动，但普通 SHA 可以被拥有文件写权限的人重算；
- HMAC 只证明 attestation 对应受保护 baseline 中的 reviewer 信任锚；
- 真正的隔离依赖 `.git/stage_verification` 或外部 state 目录只由验收者写入，以及 reviewer key 不交给实现 agent；
- 如果 agent 与验收者拥有完全相同的文件、Git、环境变量和验证器修改权限，本工具不能阻止其伪造结果，最终仍需代码评审。

## 退出码

| 退出码 | 结果 | 含义 |
|---:|---|---|
| 0 | `PASS` | 所有自动和人工门禁通过 |
| 1 | `FAIL` | 至少一个自动检查失败 |
| 2 | configuration error | manifest、baseline、acceptance suite 或参数不可用；不会运行被篡改 manifest 的命令 |
| 3 | `NEEDS_MANUAL` | 自动检查通过，但缺少有效人工验收 |

阶段 8 要求全量 Python 回归通过。如果已知历史失败在阶段 8 前仍存在，应先回到其所属阶段或单独完成基线债务清理，再记录阶段 8 baseline；阶段 8 本身不允许借验收之名修改业务实现。
