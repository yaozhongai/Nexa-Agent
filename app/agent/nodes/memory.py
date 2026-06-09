"""update_memory — 记忆持久化节点

STM（短期记忆）：每轮对话始终写入，保证多轮上下文可用。失败不阻断主流程。
LTM（长期记忆）：由 need_memory_write 门控，避免临时查询污染持久存储。
"""

import time
from app.agent.state import AgentState, StepStatus, RouteType, trace_patch, error_patch
from app.api.deps import get_short_term_memory, get_long_term_memory
from app.utils.logger_config import get_logger

logger = get_logger("node.memory")


def update_memory(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    route = state.get("route_result")
    sid = state.get("session_id", "")
    ui = state.get("user_input", "")
    fa = state.get("final_answer") or ""
    result = {}
    need_ltm = route.need_memory_write if route else False

    # ── 短期记忆：始终写入（保证多轮上下文）──
    try:
        stm = get_short_term_memory()
        stm.write_from_state(dict(state))
        logger.info("STM written session=%s", sid)
    except Exception as exc:
        logger.warning("STM 写入失败 session=%s: %s", sid, exc)
        result.update(error_patch(
            error_type="short_term_memory_write_failed",
            message=str(exc), node="update_memory", recoverable=True,
        ))

    # ── 长期记忆：仅 need_memory_write=True 时写入 ──
    if need_ltm:
        try:
            ltm = get_long_term_memory()
            ltm.upsert_conversation(sid)
            ltm.save_message(sid, "user", ui)
            ltm.save_message(sid, "assistant", fa)
            logger.info("LTM written session=%s", sid)
        except Exception as exc:
            logger.warning("LTM 写入失败 session=%s: %s", sid, exc)
            result.update(error_patch(
                error_type="long_term_memory_write_failed",
                message=str(exc), node="update_memory", recoverable=True,
            ))

        # ── VISION_SCHEMA 额外保存票据 ──
        route_type = route.route_type if route else None
        if route_type == RouteType.VISION_SCHEMA:
            try:
                ltm = get_long_term_memory()
                image_refs = state.get("image_refs", [])
                image_path = image_refs[0].path if image_refs else None
                so = state.get("structured_output") or {}
                ltm.save_invoice(sid, {"filename": image_path or "", "details": so})
                logger.info("Invoice saved session=%s", sid)
            except Exception as exc:
                logger.warning("票据保存失败 session=%s: %s", sid, exc)
                result.update(error_patch(
                    error_type="invoice_save_failed",
                    message=str(exc), node="update_memory", recoverable=True,
                ))

    result.update({
        **trace_patch(step=step, node="update_memory", action="persist",
                      latency_ms=int((time.time() - t0) * 1000),
                      status=StepStatus.SUCCESS,
                      reason=f"stm_written ltm={'written' if need_ltm else 'skipped'}"),
        "step_count": step,
    })
    return result
