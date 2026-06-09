"""validate_direct / validate_schema / verify — 校验节点

L1: validate_direct, validate_schema
L2: verify (仅 need_verify=True)
"""

import json
import time
from app.agent.state import (
    AgentState, StepStatus, ValidationResult, trace_patch,
)
from app.utils.validate import validate_direct_answer, validate_schema_result
from app.api.deps import get_llm_client
from app.llm.client import LLMMessage
from app.utils.logger_config import get_logger

logger = get_logger("node.verify")


def validate_direct(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    answer = state.get("final_answer") or ""
    v = validate_direct_answer(answer)
    elapsed = int((time.time() - t0) * 1000)
    return {
        "validation_results": [ValidationResult(validator_name="direct_answer", passed=v.passed, issues=v.issues)],
        "final_answer": answer if v.passed else f"[VLM 异常] {'; '.join(v.issues)}",
        **trace_patch(step=step, node="validate_direct", action="validate",
                      status=StepStatus.SUCCESS if v.passed else StepStatus.FAILED,
                      reason="passed" if v.passed else f"issues: {v.issues}", latency_ms=elapsed),
        "step_count": step,
    }


def validate_schema(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    answer = state.get("final_answer") or ""
    ok, data, issues = validate_schema_result(answer)
    elapsed = int((time.time() - t0) * 1000)
    return {
        "validation_results": [ValidationResult(validator_name="schema_result", passed=ok, issues=issues)],
        "structured_output": data if ok else None,
        **trace_patch(step=step, node="validate_schema", action="validate",
                      status=StepStatus.SUCCESS if ok else StepStatus.FAILED,
                      reason="passed" if ok else f"issues: {issues}", latency_ms=elapsed),
        "step_count": step,
    }


_VERIFY_PROMPT = """请对以下回答进行严格质量检查。

【用户问题】
{user_input}

【上下文 / 图片识别内容】
{context}

【待检查的回答】
{answer}

## 检查标准
1. 回答是否直接针对用户问题？
2. 关键事实是否与上下文一致？（无编造）
3. 是否有严重遗漏？
4. 逻辑是否自洽？

## 输出格式 (JSON)
{{
    "passed": true/false,
    "score": 0.0 ~ 1.0,
    "issues": ["问题1", "问题2"],
    "revised_answer": "修正后的回答（仅在 passed=false 时提供）"
}}

只输出 JSON。"""


def verify(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    answer = state.get("final_answer") or ""
    user_input = state.get("user_input", "")

    context_parts = []
    for obs in state.get("observations", []):
        if hasattr(obs, "source") and obs.source.value == "vlm":
            context_parts.append(f"[VLM感知] {obs.content[:500]}")
    prev_results = state.get("validation_results", [])
    if prev_results:
        last = prev_results[-1]
        if last.issues:
            context_parts.append(f"[上次反思发现的问题] {'; '.join(last.issues)}")
    context = "\n".join(context_parts) if context_parts else "（无附加上下文）"

    prompt = _VERIFY_PROMPT.format(user_input=user_input, context=context, answer=answer)

    try:
        llm = get_llm_client()
        resp = llm.chat([LLMMessage.user(prompt)], temperature=0.0, max_tokens=512)
        data = _parse_verify_response(resp.content)
        result = ValidationResult(
            validator_name="llm_verifier", passed=data.get("passed", True),
            issues=data.get("issues", []), revised_answer=data.get("revised_answer"),
            confidence=data.get("score"),
        )
        elapsed = int((time.time() - t0) * 1000)
        logger.info("VERIFY passed=%s score=%s issues=%d %dms", result.passed, result.confidence, len(result.issues), elapsed)
        return {
            "validation_results": [result],
            "final_answer": result.revised_answer if not result.passed and result.revised_answer else answer,
            **trace_patch(step=step, node="verify", action="verify",
                          status=StepStatus.SUCCESS if result.passed else StepStatus.FAILED,
                          reason="passed" if result.passed else f"issues: {result.issues}",
                          confidence=result.confidence, latency_ms=elapsed),
            "step_count": step,
        }
    except Exception as exc:
        elapsed = int((time.time() - t0) * 1000)
        logger.warning("verify LLM 调用失败，默认通过: %s", exc)
        return {
            "validation_results": [ValidationResult(validator_name="llm_verifier", passed=True, issues=[])],
            **trace_patch(step=step, node="verify", action="verify",
                          status=StepStatus.SUCCESS, reason="llm_failed_default_pass", latency_ms=elapsed),
            "step_count": step,
        }


def _parse_verify_response(raw: str) -> dict:
    text = raw.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0].strip()
    elif "```" in text:
        text = text.split("```")[1].split("```")[0].strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"passed": "true" in text.lower(), "score": 0.5, "issues": ["Verifier JSON 解析失败"]}
