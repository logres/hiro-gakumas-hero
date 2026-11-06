# 来源：digital-hiro hiro/loop/landscape.py（c3fc27f）
"""横屏 LIVE 黑屏的处理（PlayCover 已知问题，PlayCover issue #1496、社区「画面回転でブラックアウトしたらフルスクリーン切替」）。

选拔赛 / 本战结束后的 LIVE 要求横屏，PlayCover 窗口不跟着转，游戏在跑但画面全黑、后台点击无效。
进入全屏（应用菜单「显示 → 进入全屏幕」）会让窗口重新布局，LIVE 就能渲染；LIVE 结束回到竖屏后再退出全屏，否则又是黑屏。
菜单操作需要把游戏短暂切到前台，结束后把原来的前台应用还回去。实机 2026-10-31 第四局验证。
"""

import logging
import subprocess
import time

from AppKit import NSRunningApplication, NSWorkspace

BUNDLE_ID = "jp.co.bandainamcoent.BNEI0421"
MENU_VIEW = "显示"  # 系统语言为中文；英文 / 日文系统按下面的候选找
ENTER = ("进入全屏幕", "Enter Full Screen", "フルスクリーンにする")
EXIT = ("退出全屏幕", "Exit Full Screen", "フルスクリーンを解除")
MENUS = ("显示", "View", "表示")

logger = logging.getLogger(__name__)


def _game_pid() -> int | None:
    apps = NSRunningApplication.runningApplicationsWithBundleIdentifier_(BUNDLE_ID)
    return int(apps[0].processIdentifier()) if apps and len(apps) else None


def _front_app():
    return NSWorkspace.sharedWorkspace().frontmostApplication()


def _click_menu(pid: int, items: tuple[str, ...]) -> bool:
    script = f"""
tell application "System Events" to tell (first process whose unix id is {pid})
  set frontmost to true
  delay 0.5
  repeat with mname in {{{", ".join(f'"{m}"' for m in MENUS)}}}
    try
      set theMenu to menu 1 of menu bar item (mname as text) of menu bar 1
      repeat with itm in {{{", ".join(f'"{i}"' for i in items)}}}
        if exists menu item (itm as text) of theMenu then
          click menu item (itm as text) of theMenu
          return "ok"
        end if
      end repeat
    end try
  end repeat
  return "none"
end tell"""
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() == "ok"


class LandscapeGuard:
    """controller 每轮喂一帧：黑屏持续 BLACK_S 秒 → 进全屏；全屏中 LIVE 计时消失或又黑屏持续 → 退全屏并还原前台应用。"""

    BLACK_S = 20.0
    EXIT_BLACK_S = 8.0

    def __init__(self):
        self.black_since: float | None = None
        self.fullscreen = False
        self.prev_front: NSRunningApplication | None = None
        self.entered_at = 0.0

    def in_live(self, img) -> bool:
        """LIVE 演出中（横向画面、全屏中或黑屏）：画面本来就认不出，调用方不要按「持续未识别」停下。"""
        if img is None:
            return self.fullscreen
        mid = img[img.shape[0] // 8 : img.shape[0] * 7 // 8, img.shape[1] // 8 : img.shape[1] * 7 // 8]
        return self.fullscreen or img.shape[1] > img.shape[0] or float(mid.mean()) < 3.0

    def tick(self, img, texts: list[str] | None = None) -> bool:
        """返回 True 表示本轮做了窗口操作（调用方跳过本轮分发）。"""
        now = time.monotonic()
        # 只看中间区域：全屏后窗口顶部有一条白边，整帧均值会超过阈值（q8 / q9 LIVE 结束后一直没退出全屏）
        black = img is not None and float(img[img.shape[0] // 8 : img.shape[0] * 7 // 8, img.shape[1] // 8 : img.shape[1] * 7 // 8].mean()) < 3.0
        if not black:
            self.black_since = None
        elif self.black_since is None:
            self.black_since = now
        if not self.fullscreen and img is not None and img.shape[1] > img.shape[0] and not black:
            # 横向且有画面：已经在全屏 LIVE 里（例如人工点了「进入全屏幕」），之后照常负责退出
            self.fullscreen, self.entered_at = True, now
        if not self.fullscreen:
            if black and now - self.black_since >= self.BLACK_S:
                return self._enter()
            return False
        # 全屏中：LIVE 结束后游戏回竖屏 → 横向全屏窗口又是黑的
        if black and now - self.black_since >= self.EXIT_BLACK_S and now - self.entered_at > 30:
            return self._exit()
        return False

    def _enter(self) -> bool:
        pid = _game_pid()
        if pid is None:
            return False
        self.prev_front = _front_app()
        ok = _click_menu(pid, ENTER)
        logger.warning("横屏 LIVE 黑屏 %.0fs：进入全屏让窗口重新布局（%s）", self.BLACK_S, "成功" if ok else "失败")
        if ok:
            self.fullscreen, self.entered_at, self.black_since = True, time.monotonic(), None
        return ok

    def _exit(self) -> bool:
        pid = _game_pid()
        ok = pid is not None and _click_menu(pid, EXIT)
        logger.warning("LIVE 结束：退出全屏（%s）", "成功" if ok else "失败")
        self.fullscreen, self.black_since = False, None
        if self.prev_front is not None and int(self.prev_front.processIdentifier()) != pid:
            self.prev_front.activateWithOptions_(0)
        self.prev_front = None
        return ok


def create_guard():
    return LandscapeGuard()


def window_bounds():
    from .real_click import window_bounds as bounds
    return bounds()
