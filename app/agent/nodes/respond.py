"""respond — 生成最终响应"""

import time
from app.agent.state import AgentState, StepStatus, trace_patch

from app.agent.state import AgentState, StepStatus, trace_patch


def respond(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1
    answer = state.get("final_answer") or "（无响应）"

    return {
        "final_answer": answer,
        **trace_patch(step=step, node="respond", action="respond",
                      status=StepStatus.SUCCESS, output_summary=answer[:200]),
        "step_count": step,
    }
