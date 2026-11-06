# Windows 环境安装

此流程安装 Windows 开发、设备适配与离线 OCR 所需环境，生成 KAA 的资源代码。它不会启动游戏、点击桌面或下载公开游戏数据；完成安装不代表完整实机游玩已经可用。

## 安装

准备 Git、uv 与 PowerShell 7，在仓库根目录运行：

```powershell
pwsh -NoProfile -File scripts/setup-windows.ps1
```

脚本初始化仓库固定的 `vendor/kaa` 子模块，创建 Python 3.10 的 `.venv`，通过显式 editable 路径安装本地 KAA 与宿主 `.[dev]`。这里不单独使用 `.[dev,play]`：`uv pip install` 不会按 `[tool.uv.sources]` 自动选择本地 KAA。已有 `.venv` 若不是 Python 3.10，脚本报错并保留它，需要自行明确选择环境后重跑。

缺少 `kaa/tasks/R.py` 时，脚本在 `vendor/kaa` 工作目录调用官方 `tools/make_resources.py`。该生成器会删除并重建 `kaa/sprites`，因此启动前会检查源码中三个输入/输出常量、解析后的绝对路径（含链接跳转），并确认输出仍在子模块内、被 Git 忽略且没有已跟踪文件。只重建可生成资源，不额外制作备份。KAA 换版本后需要显式重新生成：

```powershell
pwsh -NoProfile -File scripts/setup-windows.ps1 -Regen
```

所有外部命令的非零退出码都会使脚本失败。安装最后只检查宿主与生成的 KAA 资源能否导入，不连接设备。

## 选择已有 Windows 能力

在实际运行 Python 的同一 PowerShell 进程中配置：

```powershell
$env:HIRO_DEVICE_BACKEND = 'hiro.platforms.windows.device'
$env:HIRO_OCR_BACKEND = 'hiro.platforms.windows.ocr'
$env:HIRO_WINDOW_BACKEND = 'hiro.platforms.windows.window'
# 将移动、按下、抬起放入一个 SendInput 批次，已通过 DMM 菜单开关实测。
# 不设置时仍使用原 windows_native 输入。
$env:HIRO_WINDOWS_MODE = 'windows_sendinput'
```

设备 provider 是显式前台实现：截图会尝试激活选中的窗口，输入会移动真实鼠标。设置环境变量本身不会启动游戏或发送输入；调用设备连接和控制入口时才会使用这些能力。不要据此推断后台挂机可用。

OCR 使用已安装资源中的日文/英文模型，详细实测与限制见 [Windows 验证记录](windows-validation.md)。Windows 窗口 provider 用 KAA 模板确认带跳过按钮的 LIVE，不执行 Mac 全屏补救。尚不覆盖隐藏控件、演出开始页和横屏弹窗；未知横屏会停下等待人工处理。完整 play 流程尚未完成验收。

## 数据与验收

2026-11-06 已通过实际 DMM 首页菜单打开、关闭及回到首页验证。可用限定入口复测：

```powershell
pwsh -NoProfile -File scripts/verify-windows-menu.ps1 -Elevate
```

`-Elevate` 显式请求 Windows 标准 UAC，适用于游戏已在管理员权限运行的情况；
确认后空出鼠标，脚本自行记录结果到 `reports/windows-probe/menu-verification.log`。
不传该参数时不提权；权限不足会在输入前停止。该入口最多打开、关闭菜单各一次，
不会进行培育、奖励领取或购买。菜单必须已在首页；若上次失败留下菜单，可用
`-CloseExisting` 只识别并关闭它。完整游玩和后台输入仍未验收。

游戏启动后，可先单独核查 Hiro 的实际截图与 OCR，不发送点击：

```powershell
.venv/Scripts/python.exe tools/probe_windows_game.py
```

此命令会激活目标窗口，将原始/逻辑截图及 OCR 框保存到忽略目录 `reports/windows-probe/`。
它验证截图识别链路，不代表游戏接受输入或完整游玩通过。默认仍精确匹配标题 `gakumas`。

报告也记录 Hiro 与游戏的进程完整性级别。游戏高于 Hiro 时，截图可能正常而输入被 Windows
限制；设备层现在会在点击/滑动前明确报错。先让两者使用相同权限级别，不关闭 UAC 或更改
安全策略。工具不会自行提权。权限依据见 [Microsoft SendInput/UIPI 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)。

公开游戏数据使用官方 KAA `GameDataUpdater` / `apply_pending` 流程，在仓库根目录单独执行：

```powershell
.venv/Scripts/python.exe tools/update_game_data.py
```

已有数据可用 `HIRO_KAA_GAME_DATA` 指向。工具先下载到 staging，再通过 KAA 校验与应用；不会启动游戏。
不要把数据准备成功或 macOS 脚本打印的开局命令当作 Windows 已就绪证明。

运行测试：

```powershell
.venv/Scripts/python.exe -m pytest -q
```

Codex 内的安装和 import 成功不能证明外部桌面集成成功。应在独立启动的外部 PowerShell 7 中使用该 `.venv` 的绝对 Python 路径重复核对模型、资源与目标窗口可见性；从 Codex 启动的子进程不自动脱离应用包虚拟化。实际截图、输入与窗口恢复需要另行验证，安装脚本不触发这些桌面操作。
