"""retrieve — 记忆检索节点"""

import time
from app.agent.state import AgentState, StepStatus, EvidenceItem, trace_patch
from app.api.deps import get_short_term_memory, get_long_term_memory
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

    stm = get_short_term_memory()
    ltm = get_long_term_memory()

    history = stm.get_history(session_id)
    short_term = [{"role": m.role, "content": m.content[:500]} for m in history[-6:]]
    prefs = ltm.get_all_preferences()

    ctx_items = [
        EvidenceItem(source_type="memory", content=f"{m['role']}: {m['content'][:200]}", title="short_term")
        for m in short_term
    ]

    logger.info("RETRIEVE st=%d", len(short_term))

    return {
        "short_term_context": short_term,
        "retrieved_context": ctx_items,
        **trace_patch(step=step, node="retrieve", action="retrieve",
                      latency_ms=int((time.time() - t0) * 1000),
                      status=StepStatus.SUCCESS, reason=f"st={len(short_term)}"),
        "step_count": step,
    }
