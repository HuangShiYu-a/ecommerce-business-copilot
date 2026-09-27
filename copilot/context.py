"""用户上下文：store_id 隔离 + 角色（Tool 隐含入参）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserContext:
    user_id: int
    role: str                       # customer_service / operations
    store_id: int                   # 1=STORE_01, 2=STORE_02
    permissions: frozenset = field(default_factory=frozenset)


def ops_ctx(store_id: int) -> UserContext:
    return UserContext(user_id=1, role="operations", store_id=store_id)


def session_ctx(session: dict) -> UserContext:
    """从会话构造 UserContext（V1 单用户 demo，替代硬编码 ops_ctx）。

    角色取 Workspace Mode（UNSET/CUSTOMER_SERVICE/OPERATIONS）或兼容旧 role；
    未设置时回退 operations（与 legacy ops_ctx 一致）。UNSET 的目录过滤由 toolkit 承担，
    ctx 本身只携带 store/user 供工具执行与审计。
    """
    return UserContext(
        user_id=int(session.get("user_id") or 1),
        role=session.get("workspace_mode") or session.get("role") or "operations",
        store_id=int(session.get("store_id") or 1),
    )


def mode_to_role(mode: str | None) -> str:
    """Workspace Mode（大写）→ 小写角色（customer_service/operations）；UNSET/未知回退 operations。

    消除大写 workspace_mode 与工具 allowed_roles（小写）的大小写冲突（审查发现 1）。
    """
    m = (mode or "").lower()
    return m if m in ("customer_service", "operations") else "operations"


def normalize_mode(mode: str | None) -> str:
    """小写 domain → 大写 Workspace Mode（UNSET/CUSTOMER_SERVICE/OPERATIONS）；未知回退 OPERATIONS。

    request_capability(domain) 的 LLM 参数为小写，需归一化到工作台/工厂使用的大写约定。
    """
    m = (mode or "").upper()
    return m if m in ("UNSET", "CUSTOMER_SERVICE", "OPERATIONS") else "OPERATIONS"


# 能力切换的文本确认/拒绝（P1：用户打字"切换/确认"而非点按钮）
_CAP_REJECT = ("拒绝", "不用", "算了", "取消", "不切换", "不确认", "no")
_CAP_CONFIRM = ("确认切换", "切换", "确认", "好的", "可以", "同意", "继续", "yes", "ok")
# 疑问句标记（F9）：含疑问词的消息不当作确认/拒绝，避免"请分析是否切换成功了"误触切换
_QUESTION_MARKERS = ("吗", "？", "?", "是否", "为什么", "怎么")


def capability_text_decision(message: str | None) -> str | None:
    """识别用户对能力切换的文本意图：返回 "confirm" / "reject" / None。

    拒绝词优先（"不切换"含"切换"）；疑问句（含 吗/？/是否/为什么/怎么）不判定，
    防"请分析是否切换成功了"这类问句因含"切换"子串被误判为确认（F9）。
    仅用于存在 capability_pending 时的下一轮。
    """
    msg = (message or "").strip().lower()
    if not msg:
        return None
    if any(k in msg for k in _QUESTION_MARKERS):
        return None
    for k in _CAP_REJECT:
        if k in msg:
            return "reject"
    for k in _CAP_CONFIRM:
        if k in msg:
            return "confirm"
    return None


def capability_domain_switch(message: str | None) -> str | None:
    """文本显式域切换识别（F4，无 pending 时的兜底）。

    消息同时含确认意图 + 显式能力域（运营/客服）→ 返回归一化 Workspace Mode
    （OPERATIONS/CUSTOMER_SERVICE）；否则 None（无法确定目标域，不猜测）。
    拒绝词优先（"不用切换"等）；仅"好的/切换"无域名的消息无法确定目标，返回 None。
    """
    msg = (message or "").strip().lower()
    if not msg or any(k in msg for k in _CAP_REJECT):
        return None
    if capability_text_decision(msg) != "confirm":
        return None
    if "客服" in msg or "customer_service" in msg:
        return "CUSTOMER_SERVICE"
    if "运营" in msg or "operations" in msg:
        return "OPERATIONS"
    return None
