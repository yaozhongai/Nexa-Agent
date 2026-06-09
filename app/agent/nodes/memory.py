"""update_memory — 记忆持久化节点"""

import time
from app.agent.state import AgentState, StepStatus, RouteType, trace_patch

from app.agent.state import AgentState, StepStatus, RouteType, trace_patch
from app.api.deps import get_short_term_memory, get_long_term_memory
from app.utils.logger_config import get_logger

logger = get_logger("node.memory")


def update_memory(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    route = state.get("route_result")

    # 路由标记不写记忆
    if route and not route.need_memory_write:
        return {
            **trace_patch(step=step, node="update_memory", action="skip",
                          latency_ms=int((time.time() - t0) * 1000),
                          status=StepStatus.SKIPPED, reason="no memory write"),
            "step_count": step,
        }

    stm = get_short_term_memory()
    ltm = get_long_term_memory()
    sid = state.get("session_id", "")
    ui = state.get("user_input", "")
    fa = state.get("final_answer") or ""

    stm.add_message(sid, "user", ui)
    stm.add_message(sid, "assistant", fa)
    ltm.upsert_conversation(sid)
    ltm.save_message(sid, "user", ui)
    ltm.save_message(sid, "assistant", fa)

    # VISION_SCHEMA 场景保存票据数据
    route_type = route.route_type if route else None
    if route_type == RouteType.VISION_SCHEMA:
        image_refs = state.get("image_refs", [])
        image_path = image_refs[0].path if image_refs else None
        so = state.get("structured_output") or {}
        ltm.save_invoice(sid, {"filename": image_path or "", "details": so})

    logger.info("UPDATE memory session=%s", sid)

    return {
        **trace_patch(step=step, node="update_memory", action="persist",
                      latency_ms=int((time.time() - t0) * 1000),
                      status=StepStatus.SUCCESS),
        "step_count": step,
    }
