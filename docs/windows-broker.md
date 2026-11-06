# Windows 双进程执行

Hiro 主进程在普通权限运行 OCR、状态机、规则、LLM 和 trace。独立的 Windows
代理绑定启动时选定的游戏 HWND/PID，持有输入所需权限。它是当前登录桌面的
普通常驻进程，不注册系统服务、开机任务或修改 UAC 策略。

## 启动与调试

```powershell
# 首次启动确认一次 Windows UAC；已运行时只检查并复用。
pwsh -NoProfile -File scripts/start-windows-broker.ps1

# 在运行主程序的普通 PowerShell 中设置 provider：
. ./scripts/use-windows-broker.ps1
.venv/Scripts/python.exe tools/check_dmm_menu.py --backend windows_broker

# 后续修改主程序、重启 Python 都复用同一代理，不再提权。
.venv/Scripts/python.exe -m hiro.platforms.windows.broker status

# 明确结束本次代理会话：
.venv/Scripts/python.exe -m hiro.platforms.windows.broker shutdown
```

`device.stop()` 只结束本地设备对象，不关闭代理。更新代理自身代码需要显式退出
并重新启动，因此仍需 UAC；代理不热加载任意 Python、PowerShell 或模型代码。
主进程的 API Key、Codex CLI 和模型调用不通过代理。

## 接口与边界

代理仅监听 `127.0.0.1` 的临时端口；凭据文件保存在 Git 忽略的
`reports/windows-broker/session.json`，目录 ACL 限定当前用户、SYSTEM 和管理员。
请求使用随机 Bearer token，不接受浏览器 Origin。只开放 `status`、`capture`、
`click`、`swipe`、`shutdown`，不开放任意代码执行或文件读写。

截图返回已归一化的 BGR PNG 和观察标记，坐标保持 Hiro 原有逻辑坐标；物理像素
换算在代理内完成。输入核对观察标记、窗口进程、客户区尺寸与坐标范围。
连接丢失后不自动重发输入，因为无法知道游戏是否已接收到上次动作。
窗口关闭或重建后不会自动换目标；状态查询和退出仍可用。

输入使用前台模式，会移动真实鼠标。运行期间保持桌面解锁，并避免同时操作鼠标。
代理运行时申请防休眠，退出时撤销。它没有实现 PlayCover MaaTools 的后台输入能力。

## 当前验证

已在 DMM 上验证普通 Python（完整性 8192）通过代理（12288）打开菜单、识别 X、
关闭并返回首页。主进程退出后，另一个主进程成功重连同一代理 PID。
这证明两进程和重启调试通路，不代表完整 H.I.F 已验收。
所有公开功能的进度见 [功能对照](windows-feature-parity.md)。
