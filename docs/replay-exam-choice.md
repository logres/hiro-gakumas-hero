# 单帧考试决策回放

`tools/replay_exam_choice.py` 使用 `Step.exam_decision_input` 中决策前冻结的完整 `BattleState`、`ExamMemory`、合法动作和预演，对照历史最终选择与当前完整规则链。默认不调用模型。旧 trace 没有该快照时明确拒绝；`Step.state.exam` 与末态 `exam_memory.json` 不能无损还原当时的决策输入。

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe tools/replay_exam_choice.py traces/<run> --seq 42
.venv/Scripts/python.exe tools/replay_exam_choice.py traces/<run> --seq 42 --adapter codex:gpt-6.1-sol --max-model-calls 3
```

显式 `--adapter codex[:model]` 或 `openai:model` 时，工具只对指定的一帧运行一次完整决策链；硬规则拦截可能触发模型重问，实际模型调用最多 `--max-model-calls` 次（默认 3，范围 1–10）。达到上限时适配器返回失败，现有规则链继续完成兜底，并在模型 trace 记录错误。不会连接游戏设备或执行动作，也不读取 `state_after` 或后续帧。

输出 JSON 包含冻结输入及 BattleState/ExamMemory 的 SHA-256、当前代码/偶像提示词/策略引用文件 hash、白名单策略开关（含 `HIRO_FALLBACK_DRINKS`）、原始模型回复与历史最终动作、当前规则和可选模型决策的理由、warnings 与合法性。`warnings` 记录硬规则和末回合覆盖的原动作及原因。当前代码 hash 与历史运行时可能不同；单帧对照不能证明整场考试分数会提升。私有 trace 留在本地，不加入仓库。
