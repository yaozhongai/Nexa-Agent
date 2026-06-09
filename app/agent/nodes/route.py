"""

import time
from app.agent.state import (
route_task — 任务路由节点

两层路由：
  L1 规则匹配 (0ms) → 高置信度直接返回
  L2 DeepSeek V4 Flash → 模糊输入兜底
"""

from app.agent.state import (
    AgentState, RunStatus, StepStatus, RouteResult, RouteType, RiskLevel, trace_patch,
)
from app.utils.task_router import route_task as rule_route
from app.llm.client import LLMMessage, create_llm_client
from app.utils.logger_config import get_logger

logger = get_logger("node.route")

# L2 LLM 路由 prompt
_ROUTE_PROMPT = """你是一个任务路由器。分析用户输入，输出 JSON。

## 路由类型
- vision_direct: 用户有图片，问题可以直接从图片中回答（如"这是什么""金额多少""里面有什么"）
- vision_schema: 用户有图片，要求提取结构化信息（如"提取发票字段""输出JSON""整理成表格"）
- rag_qa: 纯文本问答，无图片；或者图片+复杂推理（如"是否可以报销""原因是什么""给出建议"）
- tool_act: 要求执行操作（如"重启设备""生成工单""发送邮件"）

## 输出格式
{"route_type": "<类型>", "confidence": 0.0~1.0, "reason": "<简短理由>"}

## 示例
用户: "你好" → {"route_type": "rag_qa", "confidence": 0.95, "reason": "纯文本问候"}
用户: "金额多少" (有图) → {"route_type": "vision_direct", "confidence": 0.95, "reason": "图片直答"}
用户: "提取发票信息" (有图) → {"route_type": "vision_schema", "confidence": 0.95, "reason": "结构化提取"}
用户: "是否可以报销" (有图) → {"route_type": "rag_qa", "confidence": 0.9, "reason": "需推理判断"}

只输出 JSON。"""


def route_task(state: AgentState) -> dict:
    step = state.get("step_count", 0) + 1
    image_refs = state.get("image_refs", [])
    image_path = image_refs[0].path if image_refs else None
    user_input = state.get("user_input", "")

    # ── L1: 规则匹配 ──
    r = rule_route(user_input, image_path)

    # ── L2: LLM 兜底（规则置信度不足时） ──
    if r.confidence < 0.9 or r.route_type.value == "unknown":
        logger.info("规则置信度不足 (%.2f)，进入 LLM 路由", r.confidence)
        llm_result = _llm_route(user_input, bool(image_path))
        if llm_result:
            r.route_type = RouteType(llm_result.get("route_type", r.route_type.value))
            r.confidence = llm_result.get("confidence", r.confidence)
            r.reason = llm_result.get("reason", r.reason)
            r.matched_rules.append("llm_fallback")

    # ── 构造新 RouteResult ──
    legacy_map = {"vision_reason": "rag_qa", "text_qa": "rag_qa"}
    mapped_type = legacy_map.get(r.route_type.value, r.route_type.value)

    route_result = RouteResult(
        route_type=RouteType(mapped_type),
        confidence=r.confidence,
        reason=r.reason,
        matched_rules=list(r.matched_rules),
        need_retrieve=r.need_retrieve,
        need_reason=r.need_reason,
        need_verify=r.need_verify,
        need_memory_write=r.need_memory,
        risk_level=RiskLevel.LOW,
    )

    logger.info("ROUTE → %s confidence=%.2f source=%s",
                route_result.route_type.value, route_result.confidence,
                "llm" if "llm_fallback" in r.matched_rules else "rule")

    return {
        "route_result": route_result,
        "status": RunStatus.ROUTED,
        **trace_patch(step=step, node="route_task", action="route",
                      status=StepStatus.SUCCESS, reason=route_result.reason,
                      confidence=route_result.confidence),
        "step_count": step,
    }


def _llm_route(user_input: str, has_image: bool):
    """DeepSeek V4 Flash 意图分类"""
    try:
        client = create_llm_client("deepseek", model="deepseek-v4-flash")
        prefix = f"[用户有图片] " if has_image else "[纯文本] "
        response = client.chat(
            [LLMMessage.user(_ROUTE_PROMPT + f"\n\n用户: {prefix}{user_input}")],
            temperature=0.0,
            max_tokens=128,
        )
        raw = response.content.strip()
        if "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

        import json
        data = json.loads(raw)
        logger.info("LLM 路由结果: %s", data)
        return data
    except Exception as exc:
        logger.warning("LLM 路由失败: %s", exc)
        return None
