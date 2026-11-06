# 单帧选卡对照

`tools/replay_card_choice.py` 只读取一帧 `SELECT_CARD` 的决策输入 `state`，对照当时记录的动作、当前规则基线和显式启用的机制选卡。trace 与 state 的契约版本均须至少 1.1，且该帧须有原决策；旧版 1.0 的 `state` 可能是执行后态，因此拒绝回放。工具不会连接游戏设备、点击或执行动作；结果是冻结局面对照，不能证明整局分数会提升。

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe tools/replay_card_choice.py traces/<run>/steps.jsonl --seq 42
.venv/Scripts/python.exe tools/replay_card_choice.py traces/<run> --seq 42 --adapter codex:gpt-6.1-sol
```

默认不调用模型；只有传 `--adapter codex[:model]` 或 `--adapter openai:model` 才调用一次机制模型。身份默认取 trace 同目录的 `run.json:idol`，也可传 `--idol <偶像卡ID>`；输出会标明来源。`--seq` 必填且只处理一帧。输出为 JSON，包含原动作、两种当前决策及理由、模型调用 trace、局面摘要、输入状态哈希、代码/提示词文件哈希，以及相关非敏感策略开关（如 `HIRO_REVIEW_FIRST_EXAM_ROLES`）的生效值。两次对照各自重建输入状态，互不污染。

对照不从后续帧或 `state_after` 补全信息，也不会把 trace 中没有记录的 `picked_musts`、`seen_deck` 等决策器内部状态伪造成事实。牌组完整性、定制效果和其他未知信息仍按未知处理。私有 trace 留在本地，不加入仓库。
