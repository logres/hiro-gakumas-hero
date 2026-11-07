"""ExecutionResult：操作 → 主循环。动作执行了什么、等了多久、之后在哪个页面、是否出现期望的转移。"""

from dataclasses import dataclass, field

from hiro.contracts.action import Action
from hiro.contracts.base import VERSION, Contract


@dataclass
class ExecutionResult(Contract):
    """一次动作执行的结果。"""

    action: Action
    ok: bool  # 动作已下发且观察到生效（画面按期望变化 / 读到新状态）
    taps: list[list[int]] = field(default_factory=list)  # 实际点击的 720x1280 逻辑坐标 [[x, y], …]
    waited_s: float = 0.0  # 执行后等待画面变化的时长
    page_before: str | None = None
    page_after: str | None = None
    expected_transition: bool | None = None  # page_after 是否在转移图允许的后继里（None = 没校验）
    retries: int = 0
    error: str | None = None  # 未生效 / 异常的说明
    seconds: float = 0.0  # 从下发到判定完成的总耗时
    version: str = VERSION
    customization_evidence: dict | None = None  # Strict executor settlement evidence; no inferred effects.
