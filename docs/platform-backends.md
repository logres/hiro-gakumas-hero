# 平台接口与 Windows 实验实现

设备、OCR、窗口恢复的 macOS 实现集中在 `src/hiro/platforms/macos/`。
Windows OCR 已提供 `hiro.platforms.windows.ocr`，使用已安装的 KAA/kotonebot 资源中的日文、英文模型。
Windows 前台设备原型为 `hiro.platforms.windows.device`；窗口 provider 为 `hiro.platforms.windows.window`。
OCR 已完成模拟结果测试与本机合成图片识别；这不代表 DMM 截图、输入或完整游戏流程已经实机验收。
决策、规则、提示词和状态记账保持原实现；本次额外增加的模型接入见 [LLM 配置](llm-backends.md)。

## 保持不变的调用入口

| 入口 | 平台实现 |
|---|---|
| `hiro.device.connect(backend="auto")` | `DeviceBackend.connect` |
| `hiro.real_click.click(x, y)` | `DeviceBackend.real_click` |
| `hiro.vision.ocr.ocr / ocr_boxes` | `OCRBackend` |
| `hiro.loop.landscape.LandscapeGuard` | `WindowBackend.create_guard` 生成的独立实例 |
| `hiro.real_click.window_bounds()` | `WindowBackend.window_bounds` |

`ocr_digits / ocr_int / ocr_text / ocr_batch` 与数字图像预处理仍在公共 OCR 模块。
`real_click.to_screen` 仅为兼容保留的 PlayCover 纯坐标函数（28 像素标题栏），Windows 不应复用。

## 配置与生命周期

三个接口分别由 `HIRO_DEVICE_BACKEND`、`HIRO_OCR_BACKEND`、`HIRO_WINDOW_BACKEND` 选择。
值为实现所有对应方法的模块路径，或 `包.模块:无参工厂`，工厂返回实现对象。

```powershell
# 已提供的 Windows OCR 模块（模块直接实现 ocr / ocr_boxes）。
$env:HIRO_OCR_BACKEND = 'hiro.platforms.windows.ocr'
# 显式选择前台设备原型；截图激活游戏，点击移动真实鼠标。
$env:HIRO_DEVICE_BACKEND = 'hiro.platforms.windows.device'
# 默认精确匹配窗口标题 gakumas；也可选择一个已确认的 HWND。
$env:HIRO_WINDOW_TITLE = 'gakumas'
$env:HIRO_WINDOW_BACKEND = 'hiro.platforms.windows.window'
```

程序内也可在连接设备之前调用 `hiro.platforms.register("ocr", provider)`，其优先级高于环境变量。
没有配置时，macOS 自动选择原 Mac 实现；其他平台在首次使用能力时抛出
`PlatformUnavailableError` 并提示配置项。单纯导入公共入口不会加载 Apple 框架。
模块/工厂结果按配置缓存；`platforms.reset()` 用于测试或重新配置，不负责停止设备。
设备由调用方持有并负责停止；每次创建 `LandscapeGuard` 都创建新的恢复状态。

## Windows 实现需要履行的契约

- **设备**：返回已启动、能交给 kotonebot/KAA `init_context(target_device=...)` 的兼容设备。
  截图与点击使用现有的 720×1280 逻辑坐标；物理屏幕、客户区、DPI、缩放转换由实现负责。
  `connect` 的 `backend` 参数继续表示平台内部的截图/输入方式（Mac 为 auto/maatools/quartz）。
  `real_click` 是显式真实鼠标兜底，不应在普通截图或连接时触发。
- **OCR**：输入 BGR 图像；输出文字和 0–1 置信度。框为原始输入图像左上原点的
  `(x1, y1, x2, y2)` 像素坐标；内部放大 `scale` 不应改变输出坐标系。
  引擎不可用必须抛错；空列表只表示没有识别到文字。
- **窗口**：`tick(img, texts=None)` 仅在实际执行窗口恢复后返回 True，主循环据此跳过本帧。
  `in_live(img)` 必须适配 DMM 实际布局，不可照搬“横屏即 LIVE”的 PlayCover 假设。
  若某客户端确实无需窗口修复，可提供无操作 guard，但仍须正确判断 LIVE。

## 验证范围

Windows OCR 默认将日文与英文请求交给日文识别模型；仅英文请求使用英文模型。
模型与引擎延迟加载并缓存；缺少依赖或模型时抛错，不下载模型，也不回退到默认中文识别模型。
不支持的语言明确报错。具体配置、依赖和合成识别结果见 [Windows 验证记录](windows-validation.md)。

Windows 设备拒绝零个或多个匹配窗口，连接时固定 HWND 与进程；激活后核对前台窗口。
截图按客户区实际大小更新缩放器；截图后发生尺寸变化则拒绝使用旧截图坐标点击。
配置 `HIRO_WINDOW_HWND` 时优先使用该句柄（十进制或 `0x` 十六进制）。
安装步骤见 [Windows 环境安装](windows-setup.md)。

Windows window provider 只做窗口边界查询和 KAA LIVE 跳过按钮模板识别，不执行
PlayCover 的全屏修复。仅确认有按钮标记的 16:9 LIVE 画面；隐藏控件、演出开始页、
横屏弹窗尚未覆盖。控制器遇到无法确认的横屏会明确停下，不再仅凭宽高比无限等待。
这是实验实现，仍需真实 DMM 画面扩充和验收。

`tests/test_platform_backends.py` 在不安装 KAA / Apple 框架时验证公共导入、Windows 缺失实现报错、
注入设备与窗口恢复、OCR 公共辅助函数、配置优先级和 Mac 默认选择。
Mac 实现主体为搬迁，仍需在 Mac + PlayCover 上做真实截图、OCR 和窗口切换验证。
本版本不宣称整个 `run_hif` 可在 Windows 开局：KAA 和实际 Windows provider 仍是实机前置条件。
