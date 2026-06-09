"""normalize_input — 归一化用户输入

V0: 记录 Observation + 推进状态
V1: 图片解码 / 文件内容提取 / InputType 推断
"""

import time
from app.agent.state import (
    AgentState, RunStatus, StepStatus, Observation, ObservationSource, trace_patch,
)


def normalize_input(state: AgentState) -> dict:
    t0 = time.time()
    step = state.get("step_count", 0) + 1

    obs = Observation(
        source=ObservationSource.USER,
        content=state.get("user_input", ""),
        node="normalize_input",
    )

    elapsed = int((time.time() - t0) * 1000)
    return {
        "observations": [obs],
        "status": RunStatus.NORMALIZED,
        **trace_patch(step=step, node="normalize_input", action="normalize",
                      status=StepStatus.SUCCESS, reason="input normalized",
                      latency_ms=elapsed),
        "step_count": step,
    }
