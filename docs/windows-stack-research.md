# Windows 截图、输入与日文 OCR 方案调研

调研日期：2026-11-06。范围是替换 PlayCover/Quartz/Apple Vision 的平台边界，保留游戏决策、契约与回放逻辑。本文只做源码和官方资料核查，没有向游戏发送输入，没有实测截图或 OCR 准确率。

## 建议

优先复用项目已固定的 KAA/kotonebot Windows DMM 实现：原生模式先做可用基线，后台模式作为显式配置并实机验收。不要为平台移植引入整套 Maa 任务流水线。若 KAA 边界不能满足需求，MaaFramework 的 Win32Controller 可以仅作截图/输入适配器；FramePool 截图配 Seize 输入是可验证的起点，PostMessage/SendMessage 不能在未测试时承诺后台可用。这是工程推断，依据是以下现成接口和各输入方式的兼容性说明。

OCR 建议用独立适配器加载明确指定的日文模型和字符字典，保持现有文本/矩形输出契约。优先兼容 KAA 已依赖的 rapidocr_onnxruntime 1.4 系列，不把当前 rapidocr 3.x 示例直接复制进旧环境。Windows OCR 可以作为无额外模型下载的可选方案，但必须先探测日语 OCR 能力。

## 固定依赖与 KAA：已核查源码

本仓库 gitlink 固定 KAA 为 `b2d0970817eb68678703448af7dc0bed03ce7486`。该提交 pyproject 要求 Python ~=3.10.0、kotonebot[windows]==0.20.1、pywin32==310、rapidocr_onnxruntime~=1.4、onnxruntime~=1.14.0、numpy<2.0。宿主项目的 Python >=3.10 和未限定 numpy 并不代表整套 play 环境可任意升级；应按兼容交集安装。[固定依赖源码](https://github.com/XcantloadX/kotones-auto-assistant/blob/b2d0970817eb68678703448af7dc0bed03ce7486/pyproject.toml)

固定提交的 DMM 分支已经创建 WindowsDevice：
- windows_native：WindowsNativeImpl(device=d, window_query=WindowQuery(title='gakumas'))，同一实现提供 screenshot 与 touch。
- windows_background：PrintWindowImpl(d, query) 截图，SendMessageImpl(d, query, wait_cursor_idle=lc.cursor_wait_speed) 输入。
- 这些类来自独立发行包 kotonebot，不是 KAA 源树；实现检查应锁定 0.20.1，不能用 kotonebot main 替代。[固定 DMM 创建逻辑](https://github.com/XcantloadX/kotones-auto-assistant/blob/b2d0970817eb68678703448af7dc0bed03ce7486/kaa/main/kaa.py)

后台配置的 cursor_wait_speed 表示点击前等待鼠标静止的速度阈值，0 禁用；这已经表明后台输入仍存在与真实鼠标活动相关的限制，不能宣称完全不干扰鼠标。[固定配置定义](https://github.com/XcantloadX/kotones-auto-assistant/blob/b2d0970817eb68678703448af7dc0bed03ce7486/kaa/config/base_config.py)

KAA 与 kotonebot 仓库均标示 GPL-3.0；本项目已是 GPL-3.0-or-later。发行仍应保留各自许可证、来源与修改记录；这不是对所有模型或第三方二进制许可证的统一确认。[KAA](https://github.com/XcantloadX/kotones-auto-assistant) / [kotonebot](https://github.com/XcantloadX/kotonebot)

## MaaFramework：备选，不需要改变决策层

当前官方 Python 源码的构造签名为 Win32Controller(hWnd, screencap_method=Background, mouse_method=Seize, keyboard_method=Seize)。v5 已把单一 input_method 拆成 mouse_method 和 keyboard_method。因此必须固定 Maa 包版本并按该版本源码实现。[Python 源码](https://github.com/MaaXYZ/MaaFramework/blob/main/source/binding/Python/maa/controller.py) / [v5 变更记录](https://github.com/MaaXYZ/MaaFramework/issues/850)

官方控制说明列出 FramePool=2（Windows 10 1903+、可后台截图）、PrintWindow=16（可后台截图）、ScreenDC=32（前台屏幕截图），Background 是 FramePool | PrintWindow。组合位掩码会测试候选并选择最快的可用方式；如果需要可重复验证某一种方式，应显式指定，而不是把自动选择结果当作固定实现。[官方控制方式](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/2.4-ControlMethods.md)

该文档也说明 FramePool/PrintWindow 的最小化支持是“伪最小化”：修改透明度与点击穿透并恢复窗口；它不是对真正最小化窗口渲染的保证。其他方式在最小化时失败。因此首轮验收应要求目标窗口非最小化，并单独测试遮挡、缩放和最小化。

Seize 会抢占鼠标且不支持后台；SendMessage/PostMessage 支持后台但兼容性中等，目标提升权限时可能需要同等级权限。官方明确没有对所有 Win32 程序通用的输入方式。[官方控制方式](https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/2.4-ControlMethods.md)

自行包装 SendInput 也不能绕开这些限制：Microsoft 说明它受 UIPI 限制，只能向相同或更低完整性等级程序注入；返回零或 GetLastError 不一定指出 UIPI 是失败原因。返回“已插入事件数”更不代表游戏已消费点击，应以后续界面变化验收。[SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput)

MaaFramework 仓库标示 LGPL-3.0。[官方仓库](https://github.com/MaaXYZ/MaaFramework)

## 日文 OCR 选择与版本差异

| 方案 | 精确接口依据 | 适配建议与局限 |
| --- | --- | --- |
| rapidocr_onnxruntime 1.4 | RapidOCR(config_path=None, **kwargs)，调用返回 (result, timings)，完整识别行包含四点框、文本与分数 | 与 KAA 现有依赖一致；显式提供匹配的日文识别模型/keys。不能只切换一个未经该版本确认的 lang 参数 |
| 当前 rapidocr | 官方当前文档使用 RapidOCR(params={...})、Rec.lang_type='japan'、OCRVersion/EngineType 等枚举 | 可新建隔离依赖方案，但不是旧 rapidocr_onnxruntime 的原地 API 替换 |
| PaddleOCR | 2.x 官方示例 PaddleOCR(use_angle_cls=True, lang='japan')，调用 ocr.ocr(...)；3.x 官方管线另有新接口 | 支持日文，但 Paddle 推理运行时和版本迁移成本更高；为此次平台移植不必额外引入 |
| Windows.Media.Ocr | TryCreateFromLanguage(Language('ja-JP'))，RecognizeAsync(SoftwareBitmap) | 必须检查 AvailableRecognizerLanguages / IsLanguageSupported；无法解析到已安装 OCR 语言时创建返回 null；没有与 RapidOCR 等同的置信度输出 |

旧 API 与结果结构依据：[RapidOCR v1.4.4 main.py](https://github.com/RapidAI/RapidOCR/blob/v1.4.4/python/rapidocr_onnxruntime/main.py)。现代接口与日文模型路由依据：[RapidOCR 官方模型表](https://rapidai.github.io/RapidOCRDocs/main/en/model_list/)。官方说明默认支持中文和英文，其他语言需选择模型：[RapidOCR 官方介绍](https://rapidai.github.io/RapidOCRDocs/main/en/)。

PaddleOCR 的日文语言代码为 japan：[2.10 官方快速开始](https://www.paddleocr.ai/v2.10.0/en/quick_start.html) / [3.x 官方 OCR 管线](https://paddlepaddle.github.io/PaddleOCR/main/en/version3.x/pipeline_usage/OCR.html)。不要把日文支持等同于已经证明能读本游戏的小号字体；准确率需要同一批真实截图比对。

Windows OCR 返回按行、词拆分的文字和位置，受 MaxImageDimension 限制；适配器应查询上限并处理裁剪/缩放后的坐标还原。[OcrEngine](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine?view=winrt-26100) / [语言创建失败语义](https://learn.microsoft.com/en-us/uwp/api/windows.media.ocr.ocrengine.trycreatefromlanguage?view=winrt-26100)。Windows 自带 API 的可用性不代表可重新分发其语言包；部署时应探测用户设备。

RapidOCR 与 PaddleOCR 源代码许可证均为 Apache-2.0。下载的特定模型文件仍需记录具体来源、版本、摘要和其分发说明，不用代码许可证代替模型核查。[RapidOCR LICENSE](https://github.com/RapidAI/RapidOCR/blob/main/LICENSE) / [PaddleOCR LICENSE](https://github.com/PaddlePaddle/PaddleOCR/blob/main/LICENSE)

## 最小验收边界（尚未执行）

1. 只读探测唯一目标 HWND、进程路径、客户区物理像素尺寸、DPI、可见/最小化状态；避免同名窗口误选。
2. 先截图，确认只有客户区、色彩通道正确、没有黑帧、与现有归一化坐标一致；测试 100%/150% DPI 和窗口移动。
3. 用用户允许的可逆目标单次点击并观察界面变化；分别验证前台和后台方法，不把 Win32 调用成功当作成功操作。
4. 用相同静态截图验证文字内容、框坐标、空结果、数字、假名、汉字和低分策略；未加载日文模型时明确失败，不悄悄使用默认中文模型。
5. 从独立于 Codex 应用包的环境运行同样的入口。Codex 内 Python import、路径回读或子进程启动成功不能证明用户桌面环境已正确识别窗口、模型或安装位置。

结论属于源码支持的实施建议；真实 DMM 客户端上的截图、输入、后台行为和 OCR 质量均仍需实机验收。

