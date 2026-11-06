# LLM 后端

决策规则与默认后端不变：不设置 `HIRO_LLM` 时仍用 `claude:sonnet`；`--no-llm` 仍只用规则。

## 直接调用 Codex CLI

安装近期 Codex CLI，并在运行游戏的同一 Windows 用户/终端中完成 `codex login`。
PowerShell 7 配置示例：

```powershell
$env:HIRO_LLM = 'codex'
# 可选：明确使用自己账户支持的模型
$env:HIRO_LLM = 'codex:<model>'
# CLI 不在 PATH 中时，指定实际可执行文件，路径不要加额外引号或参数
$env:HIRO_CODEX_COMMAND = 'C:\path\to\codex.exe'
```

`codex-cli[:model]` 是同义写法。Windows 优先寻找 PATH 中的 `codex.exe`；若仅有 npm 的 `.cmd` 启动器，请指定原生 `codex.exe`，适配器不经 shell 执行命令。
省略模型时使用 CLI 内建默认模型；适配器不加载用户 `config.toml`，因此用户自定义模型/provider/MCP 不会带入。
CLI 仍复用已保存的登录凭据。账户是否可用、模型权限和额度由 Codex 服务决定。

每次请求用 UTF-8 stdin 发送提示词，截图用临时 JPEG 附件；在临时目录运行 `codex exec`，用临时最终消息文件读取回答。
请求启用 read-only sandbox，关闭 shell、网页搜索、view_image 工具和远程插件目录，不加载项目 AGENTS.md；提示词也要求直接返回 JSON、不用工具。
这些参数减少不必要的工具访问，不将 CLI 当作游戏操作器。临时文件在请求结束后删除。
默认超时 60 秒，不重试、不长等额度恢复；调用失败由既有决策层处理。CLI token usage 写入 trace，费用未知时保持空值。
返回任意游戏决策 JSON 对象，通过既有 `extract_json` 解析；没有添加固定 JSON Schema，以保留不同决策提示词的返回格式。

要求 CLI 支持 `--ignore-user-config`、`--ephemeral`、`--json`、`--output-last-message` 和 `--image`。旧版本不支持时会返回调用错误，请升级 CLI。
Windows 上应在实际启动游戏程序的外部终端验证 `codex --version` 和 `codex login status`，不能仅凭 Codex 应用内可见就判断跨应用可用。

## API key / OpenAI 兼容接口

```powershell
$env:HIRO_LLM = 'openai:<model>'
$env:OPENAI_API_KEY = '<your-key>'
# 可选：OpenAI 兼容服务地址；默认 https://api.openai.com/v1
$env:OPENAI_BASE_URL = 'https://api.openai.com/v1'
```

该模式直接向 `/chat/completions` 发 HTTP 请求，不需要 Codex CLI。文本、JPEG 截图、JSON object 回复和缓存 token 记账均沿用现有适配器。
兼容端点须支持所选模型、图片（使用看图兜底时）及 `response_format: json_object`；不支持 JSON mode 时，可在 Python 中用 `from_spec(..., json_mode=False)` 配置。
API key 的计费和额度属于对应 API 服务，不等于 CLI 登录额度。不要把 key 写进仓库。

实现依据：[OpenAI 官方非交互模式文档](https://developers.openai.com/codex/noninteractive)、[CLI 配置参考](https://developers.openai.com/codex/config-reference)，并核对本机 CLI `exec --help`。
自动化测试只用 mock 和本地假服务；未进行真实付费请求，也未验证游戏截图的实际模型识别质量。
