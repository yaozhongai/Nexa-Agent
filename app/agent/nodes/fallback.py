"""fallback — 兜底节点"""

import time
from app.agent.state import AgentState, StepStatus, trace_patch

from app.agent.state import AgentState, StepStatus, trace_patch


def fallback(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    return {
        "final_answer": state.get("final_answer") or "抱歉，暂时无法处理该请求。",
        **trace_patch(step=step, node="fallback", action="fallback",
                      latency_ms=int((time.time() - t0) * 1000),
                      status=StepStatus.SUCCESS, reason="fallback response"),
        "step_count": step,
    }
