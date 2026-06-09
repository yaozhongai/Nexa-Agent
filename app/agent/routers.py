"""
LangGraph conditional edge 路由函数

原则：
- 只根据 AgentState 判断跳转
- 不修改状态
- 不依赖 current_node
- 不通过 Handler 返回字符串
"""

from app.agent.state import AgentState, RouteType, RunStatus


def route_after_normalize(state: AgentState) -> str:
    """归一化后 → 路由节点"""
    return "route_task"


def route_after_task(state: AgentState) -> str:
    """路由任务分发"""
    result = state.get("route_result")
    if result is None:
        return "fallback"

    rt = result.route_type
    has_image = bool(state.get("image_refs", []))

    if rt == RouteType.VISION_DIRECT:
        return "vision_direct"
    elif rt == RouteType.VISION_SCHEMA:
        return "vision_schema"
    elif rt == RouteType.RAG_QA:
        # 有图片的 RAG_QA 本质是 VISION_REASON：先 VLM 感知，再 LLM 推理
        if has_image:
            return "vision_perceive"
        return "retrieve"
    elif rt == RouteType.TOOL_ACT:
        return "tool_act_placeholder"
    else:
        return "fallback"


def route_after_reason(state: AgentState) -> str:
    """推理后：是否需要校验"""
    route = state.get("route_result")
    if route and route.need_verify:
        return "verify"
    return "respond"


def route_after_verify(state: AgentState) -> str:
    """校验后：通过还是重试"""
    # 取最后一条校验结果
    results = state.get("validation_results", [])
    if results and not results[-1].passed:
        # 检查 step_count 是否超限
        if state.get("step_count", 0) < state.get("max_steps", 4):
            return "reason"
    return "respond"


def route_after_validation(state: AgentState) -> str:
    """校验后 → respond"""
    return "respond"
