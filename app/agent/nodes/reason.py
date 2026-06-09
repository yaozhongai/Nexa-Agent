"""reason — LLM 推理节点"""

import time
from app.agent.state import (
    AgentState, StepStatus, Observation, ObservationSource,
    ModelCallRecord, trace_patch,
)
from app.api.deps import get_llm_client
from app.llm.client import LLMMessage
from app.utils.logger_config import get_logger

logger = get_logger("node.reason")


def reason(state: AgentState) -> dict:
    step = state.get("step_count", 0) + 1
    route = state.get("route_result")

    if route and not route.need_reason:
        return {
            **trace_patch(step=step, node="reason", action="skip",
                          status=StepStatus.SKIPPED, reason="route says no reason"),
            "step_count": step,
        }

    llm = get_llm_client()
    # 从 observations 收集 VLM 感知结果
    vlm_text = ""
    for obs in state.get("observations", []):
        if obs.source == ObservationSource.VLM:
            vlm_text = obs.content
            break

    system = "你是 Nexa Agent，智能助手。根据上下文和用户问题直接回答。"
    messages = [LLMMessage.system(system)]
    for m in state.get("short_term_context", []):
        role = _map_to_llm_role(m.get("role", "user"))
        content = m.get("content", "")
        entry_type = m.get("entry_type", "")
        # 非对话条目转为 system 上下文
        if role == "system" and entry_type not in ("user_message", "assistant_message", "final_answer"):
            content = f"[{entry_type}] {content}"
        messages.append(LLMMessage(role=role, content=content))
    if vlm_text:
        messages.append(LLMMessage.system(f"【图片识别内容】\n{vlm_text}"))
    messages.append(LLMMessage.user(state.get("user_input", "")))

    t0 = time.time()
    try:
        resp = llm.chat(messages)
        elapsed = int((time.time() - t0) * 1000)
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        logger.error("LLM 调用失败: %s", exc)
        return {
            "final_answer": f"[LLM调用失败: {exc}]",
            "model_calls": [ModelCallRecord(
                model_name="unknown", node="reason", success=False,
                error_message=str(exc), latency_ms=elapsed,
                prompt_tokens=None, completion_tokens=None, total_tokens=None,
            )],
            **trace_patch(step=step, node="reason", action="reason",
                          status=StepStatus.FAILED, error_message=str(exc),
                          latency_ms=elapsed),
            "step_count": step,
        }

    logger.info("REASON model=%s tokens=%d %dms", resp.model, resp.total_tokens, elapsed)

    return {
        "final_answer": resp.content,
        "observations": [Observation(
            source=ObservationSource.LLM, content=resp.content, node="reason",
        )],
        "model_calls": [ModelCallRecord(
            provider=resp.model, model_name=resp.model, node="reason",
            input_summary=state.get("user_input", "")[:100],
            output_summary=resp.content[:200],
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
            total_tokens=resp.total_tokens,
            latency_ms=elapsed, success=True,
        )],
        **trace_patch(step=step, node="reason", action="reason",
                      status=StepStatus.SUCCESS, output_summary=resp.content[:200],
                      latency_ms=elapsed, confidence=0.8),
        "step_count": step,
    }


def _map_to_llm_role(stm_role: str) -> str:
    """STM entry role → LLM API 合法 role"""
    if stm_role in ("user", "assistant", "system"):
        return stm_role
    # observer / tool → 映射为 user（作为上下文参考）
    return "user"
