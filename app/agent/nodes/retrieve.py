"""retrieve — 长期记忆检索节点

读取长期记忆（历史票据、偏好、历史消息），合成 retrieved_context。
短期记忆上下文已由 load_short_term_context 注入，直接从 state 读取。
"""

import time
from app.agent.state import AgentState, StepStatus, EvidenceItem, trace_patch
from app.api.deps import get_long_term_memory
from app.utils.logger_config import get_logger

logger = get_logger("node.retrieve")


def retrieve(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    route = state.get("route_result")
    session_id = state.get("session_id", "")

    if route and not route.need_retrieve:
        return {
            **trace_patch(step=step, node="retrieve", action="skip",
                          latency_ms=int((time.time() - t0) * 1000),
                          status=StepStatus.SKIPPED, reason="route says no retrieve"),
            "step_count": step,
        }

    ltm = get_long_term_memory()

    ctx_items = []

    # ── 短期记忆上下文（由 load_short_term_context 注入，直接复用）──
    short_term = state.get("short_term_context", [])
    for m in short_term[-6:]:
        ctx_items.append(EvidenceItem(
            source_type="memory",
            content=f"{m.get('role', '')}: {m.get('content', '')[:200]}",
            title="short_term",
        ))

    # ── 长期记忆：偏好 ──
    try:
        prefs = ltm.get_all_preferences()
        if prefs:
            ctx_items.append(EvidenceItem(
                source_type="memory",
                content=str(prefs)[:300],
                title="preferences",
            ))
    except Exception as exc:
        logger.warning("偏好读取失败: %s", exc)

    # ── 长期记忆：历史票据 ──
    try:
        invoices = ltm.list_invoices(limit=3)
        for inv in invoices:
            ctx_items.append(EvidenceItem(
                source_type="document",
                content=f"发票 {inv.get('invoice_code', '')} 金额{inv.get('amount', '')} 日期{inv.get('invoice_date', '')}",
                title=f"invoice_{inv.get('id', '')}",
            ))
    except Exception as exc:
        logger.warning("历史票据读取失败: %s", exc)

    logger.info("RETRIEVE lt=%d st=%d", len(ctx_items), len(short_term))

    return {
        "retrieved_context": ctx_items,
        **trace_patch(step=step, node="retrieve", action="retrieve",
                      latency_ms=int((time.time() - t0) * 1000),
                      status=StepStatus.SUCCESS,
                      reason=f"lt={len(ctx_items)} st={len(short_term)}"),
        "step_count": step,
    }
