# Windows / DMM 开源功能对照清单

更新日期：2026-11-07。依据当前源码、`AGENTS.md`、`docs/assets.md`、`docs/hif-playbook.md`、Windows broker 与安装验证记录，以及本地实机运行结果。本清单区分已完成的设备接入、局部 DMM 验证和仍未跑通的完整流程；早期审计记录保留在 `windows-validation.md`，不能以其当时的「尚未接入」结论描述当前实现。

## 验收边界

目标是让原仓库**已经公开实现**的功能通过 Windows / DMM 运行，并将高权限设备操作集中到独立 broker；不把作者私有系统的成绩或未实现功能当作移植完成条件。**已接入**指实现和针对性验证存在，**局部验证**指仅有明确限定的 DMM 证据，**待验收**指不能据现有证据声称整项实机可用。

最新有效实机证据包括：普通权限 Python（完整性 8192）经常驻高权限 broker（PID 54384，完整性 12288）在实际 DMM 窗口完成截图、首页菜单打开/关闭并返回首页；多个普通客户端重连及多次 `resume` 复用同一 broker，无需每次 UAC。实际滑动与设置读取成功；支援卡 20 个编成扫描完成，`reports/live/support-inventory.json` 记录 23 张卡、`problems: []`。第 2 步全帧日文 OCR 曾把编成号 7 误读成 1，现改用固定裁剪、白字预处理和英文 OCR，并在编号未知时停止扫描。实机逐步选择支援编成 7→15、回忆编成 1→2→1，核对四张回忆卡，原租借逻辑选入「もうすぐ本番ですね」（Vi、Lv60、突破4）。白线葛城リーリヤ（支援编成 15、回忆编成 1）的真实选拔已开始并消耗 AP：前两天礼物/训练取卡、第 3 天授業取卡、第 4 天按规则完成 Vi SP，进入第 5 天。以上是局部运行证据；**选拔三考、本战、日常及回忆全量库存仍未验收**。最新完整回归为 **621 passed、530 skipped、27 warnings**；跳过的截图用例不构成识别通过。

## 功能清单

| 开源功能 | 主要文件 | 当前 Windows 证据 | 完成所需工作 / 实机验收 |
| --- | --- | --- | --- |
| 安装、固定 KAA、生成资源、公开数据更新 | `scripts/setup-windows.ps1`、`tools/update_game_data.py`、`hiro/kaa_env.py` | 已有；固定 KAA 环境导入成功，公开数据 baseline 可用 | 独立外部 PowerShell 重跑导入、自检并核对实际数据路径；不要修改 `vendor/kaa` |
| 设备选择、截图、720×1280 逻辑坐标 | `hiro/device.py`、`platforms/windows/{broker,broker_server,device,target}.py` | broker 设备代理已接入；普通客户端从固定 DMM HWND/PID 获取归一化截图；原 721×1281 → 720×1280 和 34 OCR 区域已核对 | 移动/缩放、窗口重建、横竖切换、负屏幕坐标和跨屏 DPI 仍需实机覆盖；旧观察标记/几何变化应拒绝输入 |
| 点击、滑动、前台 fallback | `platforms/windows/{broker,broker_server,input,device}.py`、`hiro/real_click.py`、`tap.py` | 普通客户端经 broker 完成真实菜单开/关/返回首页与实际滑动；`real_click` 已交由所选 provider；broker 固定 HWND/PID 并串行化输入 | 前台 SendInput 会移动真实鼠标；更复杂页面的滑动、断连时的操作结果和窗口生命周期仍需实机验证 |
| 日文/英文 OCR、框坐标与文本排序 | `platforms/windows/ocr.py`、`vision/ocr.py` | 模型、合成样例、首页、设置、支援及局部选拔画面的真实 OCR 已使用；第 2 步白底编成号 7→1 误读已按实际裁剪修复 | 继续核对小字、描边、数值和动画背景；RapidOCR 的断词/排序不同于 Apple Vision，局部修复不能代表全页面准确 |
| 判页、HUD、分数、NPC/名次/突破线、手牌/徽章、状态、道具、饮料 | `vision/{pages,quick,hif,digits,cards,status,items,drinks,observe}.py`、`perception/lesson.py` | 第 1～4 天局部页面已实机使用；HUD 原生缩放、增长率箭头排除、P 数字、缺日数及分段体力读数已按实帧修正；未知偶像 trend 在预演中保持未知值，不因此停止决策 | 继续在真实 DMM 选拔考试及本战覆盖分数、NPC/名次、突破线、手牌、徽章、道具、饮料等字段及 None 退路；保留状态互验 |
| 素材插件、图标补齐、卡图与图标渲染缓存 | `plugins.py`、`defaults/assets.py`、`vision/assets.py`、`tools/assets/capture_icons.py`、`vision/card_icon_render.py` | 素材包与公开数据已接入，离线功能已有 | Windows 路径与缓存生成 smoke；新图标来自用户本地截图，label/apply 仍需核查；导出客户端 sprite 的工具不可假设沿用 iOS 路径 |
| 整局选拔 → 本战、本战单独运行 | `tools/play_game.py`、`hiro/run_hif.py` | 白线葛城リーリヤ的真实选拔已开始并消耗 AP，完成第 4 天 Vi SP 并进入第 5 天；尚无完整选拔局或本战证据 | 验证选拔三考、qualify→main 子进程传递、本战 R1/中场/R2、main-only 和最终结果；选拔退出非零不得自动开本战 |
| 新开局、续跑、跨端培育拦截 | `loop/{controller,resume}.py`、`run_hif.py` | 实际 `new` 已进入选拔；多次 `resume` 经普通客户端复用同一 broker 并继续推进 | 仍需覆盖跨端进度默认停机退出 3、异常恢复及完整流程；不能把恢复操作变成放弃 |
| 支援与回忆库存扫描（列表/编成/详情翻页） | `tools/support_inventory.py`、`tools/memory_inventory.py`、`hiro/memory_scan.py`、`vision/{support_screens,memory}.py` | DMM 支援编成 `--live` 已扫完 20 个编成，报告 23 张卡、`problems: []`；实际滑动已工作；未知编成号会停下而不猜。回忆库存及支援卡全量 `--list` 未验收 | 继续验证全量列表分页、详情刷新、取消退出和回忆库存；扫描会操作 UI 但不点決定；本地帧不得提交 |
| 离线编成建议、主属性、回忆优先级、租借估价 | `brain/{formation_plan,formation,support_select}.py`、`state/memory_priority.py` | 已有纯策略和方案文件流程 | 用实际库存生成方案；确认偶像与方案绑定、环境覆盖优先级、默认支援效果缺失退路 |
| 开局支援/回忆编成核对与支援租借 | `produce/{formation_check,rental,memory_picker,idol_switch}.py`、`vision/memory_icons.py`、`kaa_env.py`、`loop/kaa_patches.py` | 支援编成 7→15、回忆编成 1→2→1 实机切换，四张回忆卡核对，租借「もうすぐ本番ですね」（Vi、Lv60、突破4）成功；新偶像皮肤切换弹窗曾人工选「切り替えない」，默认关闭的自动处理只有受控测试 | 其他编成/租借候选与不匹配退出 3、挑不到卡停机仍需覆盖；弹窗自动拒绝需另做实机验证 |
| 日程/训练/行动/外出/活动/礼物/休息 | `produce/hif.py`、`brain/{hif_rules,deciders}.py`、`defaults/schedule_hif.json` | 真实选拔前两天礼物/训练取卡、第 3 天授業取卡、第 4 天规则选择 Vi SP 并完成 | 继续验收剩余选拔日程、本战 9 项及其他行动入口；不通过平台移植擅自改变社区策略 |
| 卡牌获得、删除、换卡、强化/定制、P 道具选择 | `produce/{card_exclude,deck_review,special_guidance}.py`、`brain/{pick,cards,pitem}.py`、`vision/{customize,pitem_select}.py` | 第 1 天和第 3 天的取卡结果已有局部实机证据；删除、换卡、强化/定制和 P 道具选择仍待验收 | 页面布局/候选识别、二段换卡顺序、保护卡/未知卡取消、P 道具触发强化页逐项覆盖 |
| 商店/相談、饮料上限替换、中场补卡/饮料/回复 | `produce/{shop,drink_swap,interval}.py`、`vision/shop.py`、`brain/drinks.py` | 原实现已有，DMM 待验收 | 价格与余额互验、刷新限额、选购确认、R1/R2 体力延续，不能假定轮间回满 |
| 考试观察、状态记账、规则出牌、饮料、跳过、免费重试 | `brain/battle.py`、`exec/exam.py`、`defaults/{advisor,exam_state}.py`、`produce/{exam_policy,hif}.py` | 可替换插件已有；DMM 考试待验收 | 先 rules-only 再可选 LLM；确认合法动作/边界、剩余行动和实际结果；只免费次数/票券、最多 3 次，带ジュエル取消 |
| 模型无关 LLM、CLI/API、usage/费用记录 | `brain/llm.py`、`docs/llm-backends.md`、`loop/report.py` | Claude/OpenAI 兼容已有；普通权限进程中实际 Codex CLI `ask_json` 返回 `ready: true`；API 适配器和失败退路有测试，尚无真实 API 调用验收 | 模型与凭据留在普通权限主进程，broker 不启动模型；仍需在实际游戏决策链验证 CLI/API 结果及 usage；选择页/考试禁用 rescue 点击 |
| AP 饮料、通信错误、日期切换、首次设置弹窗、未知页兜底 | `loop/{ap_refill,comm_error,date_change,skip_settings,rescue}.py`、`kaa_patches.py` | 原安全处理已有 | DMM OCR 同义/断词与按钮定位验收；不花付费货币、不点标题/放弃；rescue 点击前重截图并限制次数 |
| LIVE/横屏、窗口生命周期 | `loop/landscape.py`、`platforms/windows/window.py` | 仅带 skip 按钮的 KAA LIVE 模板、半分辨率及负例；`tick` 无动作 | DMM LIVE 开始、控件隐藏、LIVE 结束、横屏弹窗尚缺；不能仅按横屏判 LIVE；未知横屏停机；不复用 PlayCover 全屏修复 |
| 暂停旗标、看门狗、重复/恢复边界 | `loop/{pause_flag,repeat_guard,errors,session}.py` | 原实现已有；broker 协议对失败输入不自动重发 | 实机覆盖 broker 故障/断连、普通进程 pause/watchdog 和恢复边界；broker 请求不得绕过这些上层约束 |
| 日常六项及弹窗守护/超时 | `tools/daily/run_daily.py`、`hiro/daily_guard.py` | 接 KAA 已有，无 DMM 逐项实机证据 | activity_funds、presents、assignment、contest、mission_reward、club_reward 各自验收；guard 线程与主任务的设备访问串行；contest 无编成 skip；采购/支援升级/抽卡/produce 保持关闭 |
| trace、记录器、manifest、日志/局报告、离线回放与不变量 | `contracts/trace.py`、`recorder.py`、`loop/{manifest,report,replay,replay_events,ledger}.py`、`state/invariants*.py` | 平台无关实现已有 | 离线 demo/replay smoke；broker 错误要出现在执行结果/日志，截图和状态归普通主进程 trace；不因 IPC 失去可复盘性 |
| HTML 复盘、牌库视图、标注、审计与预演统计 | `tools/viewer/`、`tools/audit/`、`tools/preview_stats.py` | HTML/Python 实现已有 | Windows 生成并浏览 demo HTML，批注导入/审计 smoke；preview_stats 只消费已有插件 trace，不提供模拟器 |
| 可选远端发布/批注服务器 | `tools/viewer/{publish,pull_notes,notes_server}.py`、`deploy_notes.sh` | publish 依赖 rsync+ssh；部署脚本面向 Linux/systemd | Windows 如需发布须明确安装 rsync/OpenSSH 或另做等效传输；远端 Linux 部署不是 Windows 游戏依赖；本地 HTML 无需部署 |

## 两进程 broker：已接入与待验证边界

启动和使用方法见 [`windows-broker.md`](windows-broker.md)。`scripts/start-windows-broker.ps1` 经一次 UAC 启动常驻高权限进程；普通进程由 `scripts/use-windows-broker.ps1` 选择 provider。`scripts/verify-windows-menu.ps1 -Elevate` 是早期限定测试入口，不能代替常驻 broker。

- 主进程保留识别、状态、规则、LLM/密钥、trace、日常与培育流程；broker 只暴露 `status`、`capture`、`click`、`swipe`、`shutdown`，不接受任意 shell、Python 或文件操作。已通过认证 localhost 接口、固定目标 HWND/PID 和观察标记传递截图及输入。
- 客户端对设备调用加锁，服务端核对窗口身份、前台、几何与坐标；目标退出/重建和旧观察标记均应拒绝输入。连接丢失或结果不明时不重发。`real_click` 已按当前 provider 选择设备；普通客户端重启后复用同一 broker 的实机路径已通过。
- broker 在运行期间申请防休眠，退出时撤销。它是前台输入方案，仍移动真实鼠标；不提供后台 MaaTools 语义。
- 协议、权限、无效参数和断连有测试，DMM 截图、菜单点击、滑动及多次 `resume` 复用同一 broker 已有实机证据。`tools/play_game.py` 的 qualify/main 子进程交接、daily_guard 并发、窗口变化及完整游戏流程仍需逐项运行验收。

## 剩余平台依赖与文档偏差

- Apple API 已隔离到 `platforms/macos/{device,ocr,window,real_click}.py`：Quartz、AppKit、Vision、Foundation、osascript 与 MaaTools 不能移植性地直接调用。公共 `platforms.get_backend` 在非 Mac 上要求显式选择三个 provider，不会自动启用 Windows。
- `real_click.to_screen` 是遗留纯函数，包含 PlayCover 28px 标题栏偏移；Windows 使用客户区转换。Windows `real_click` 已由所选 provider 转发，不再强制 native。
- `scripts/setup.sh` 与文档中的 `.venv/bin/python`、`PYTHONPATH=src command`、`open` 是 Unix 用法；Windows 应用 PowerShell 环境变量与 `.venv/Scripts/python.exe`。`tools/play_game.py` 的 caffeinate 已有 darwin 条件；Windows broker 已实现运行期防休眠。
- `tools/assets/export_card_sprites.py` 的客户端数据定位需单独核对 Windows/DMM；使用现成 bundled assets 不依赖该可选导出。`deploy_notes.sh` 面向远端 Linux，不应作为 Windows 本地安装步骤。
- `docs/assets.md` 的「只在 macOS 跑」及部分 Apple Vision 注释是历史描述；不能据此否定已通过的 Windows 局部验证，也不能把局部验证扩展为全流程通过。
- 不能以 Codex 内导入/写入/回读证明外部应用可见：环境、AppData/LocalCache/注册表是否重定向仍需按实际证据判断。外部提升进程和实际 DMM 响应支持当前设备链路，未证明所有虚拟化均已消失。

## 原版就没有的能力（不算 Windows 缺失）

实测另发现原公开决策器多处无条件采用やる気构筑的必拿卡、冲突牌、删换卡和饮料估值。Windows 显式身份模式现在通过主数据推荐效果限定这些规则的适用范围：其他路线的选卡按推荐效果、持有、强化与稀有度作有限选择；未知数据保留未知。没有专用策略的删除、消费和饮料替换会取消、结束或等待，不能把这些保守退路写成对应路线已经具备完整策略。白線リーリヤ的完整好印象培育与本战仍在验收中。

1. 私有考试存档读取、模拟器、确定化世界预演搜索专家、价值表。README 的夺冠成绩使用完整私有系统，不能给默认规则版承诺同等分数；插件接口保留即可。
2. 默认素材源拿不到可靠支援卡效果、考试要求/倍率换算/星级基准；应保留 None/规则退路，不能猜数据。
3. 自动将建议方案写入游戏编成位尚未实现，原工作流由用户按报告手动保存。回忆租借有评分但没有页面执行器；其他流派定制关键词与非 Da 路线估价也有原有限制，见 `formation-plan.md`。
4. Android/ADB 只有预留接口。Mac MaaTools 在后台且不移动鼠标的语义不是当前 Windows 前台 SendInput 的现有能力；双进程提升也不会自动提供后台输入。

## 实机运行前提与完成顺序

1. PowerShell 7 / UTF-8、Git/uv、Python 3.10；固定 KAA `b2d0970817eb68678703448af7dc0bed03ce7486`，安装兼容交集（既有记录：kotonebot 0.20.1、NumPy 1.26.4、RapidOCR 1.4.4、ONNX Runtime 1.14.1、pywin32 310），生成 R.py/sprites，公开数据与 bundled assets 可用。
2. 依 [`windows-broker.md`](windows-broker.md) 启动并选择 broker provider，同时显式设置 Windows OCR/window provider；LLM 主进程保持普通权限。唯一 DMM 游戏窗口、桌面解锁，前台输入期间保留鼠标使用空间。native 输入需同/更高完整性等级，不能绕过 UIPI。
3. broker 的 UAC 启动、普通客户端重连及实际菜单链路已通过。更换安装或运行环境时，再从独立外部 PowerShell 核对真实路径、import、模型/CLI 登录和跨应用可见性；不能把 Codex 应用内写入回读当成这些检查。
4. offline demo/replay 和针对改动的测试之后，利用已通过的 broker 截图/菜单/滑动、支援编成扫描与真实选拔第 1～4 天的局部证据，继续验收选拔三考、第 2/3 步其他分支、回忆库存和支援全量列表；再逐项日常及本战。每一步保存本地证据和实际 UI 结果，未知画面停下处理。
5. H.I.F 开始前：首页、无别端进行中的培育、AP 或 AP ドリンク足够、正确偶像/编成号/回忆/主属性；`HIRO_MEMORY_CARDS` 或方案提供已带入技能卡。未选择 LLM 时用 `--no-llm`；需要 LLM 时在普通用户环境提供适配器配置。
6. 最终验收至少覆盖：qualify 三场 → main R1/中场/R2、main-only、resume、安全退出、日常六项、库存两类、方案核对、trace/viewer/replay。没有跑到的项明确写待验收，不用菜单通过代替。

仅提交源码、文档和合成测试；截图、OCR 帧、trace、账号、密钥、主数据库、自建素材及运行配置留在 `.gitignore` 覆盖的本地目录。
