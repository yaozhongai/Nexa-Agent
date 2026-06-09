"""
LangGraph 主图 — build_agent_graph()

原则：
- LangGraph 是唯一图执行引擎
- 所有节点返回 dict partial update
- 所有跳转通过 conditional edge
- 不再有 Handler / AgentStateMachine
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.agent.state import AgentState
from app.agent.routers import (
    route_after_task, route_after_reason, route_after_verify,
)
# nodes
from app.agent.nodes.normalize import normalize_input
from app.agent.nodes.route import route_task
from app.agent.nodes.load_context import load_short_term_context
from app.agent.nodes.vision import vision_direct, vision_schema, vision_perceive
from app.agent.nodes.retrieve import retrieve
from app.agent.nodes.reason import reason
from app.agent.nodes.verify import validate_direct, validate_schema, verify
from app.agent.nodes.respond import respond
from app.agent.nodes.memory import update_memory
from app.agent.nodes.fallback import fallback
from app.utils.logger_config import get_logger

logger = get_logger("agent_graph")


def _tool_act_placeholder(state: AgentState) -> dict:
    """TOOL_ACT 占位节点 — V1 替换为 react_subgraph"""
    return {"final_answer": "[TOOL_ACT 暂未实现]", "status": "completed"}


def build_agent_graph() -> StateGraph:
    """构建并编译主图"""
    builder = StateGraph(AgentState)

    # 注册节点
    builder.add_node("normalize_input", normalize_input)
    builder.add_node("load_short_term_context", load_short_term_context)
    builder.add_node("route_task", route_task)
    builder.add_node("vision_direct", vision_direct)
    builder.add_node("vision_schema", vision_schema)
    builder.add_node("vision_perceive", vision_perceive)
    builder.add_node("validate_direct", validate_direct)
    builder.add_node("validate_schema", validate_schema)
    builder.add_node("retrieve", retrieve)
    builder.add_node("reason", reason)
    builder.add_node("verify", verify)
    builder.add_node("respond", respond)
    builder.add_node("update_memory", update_memory)
    builder.add_node("fallback", fallback)
    builder.add_node("tool_act_placeholder", _tool_act_placeholder)

    # 入口
    builder.set_entry_point("normalize_input")
    builder.add_edge("normalize_input", "load_short_term_context")
    builder.add_edge("load_short_term_context", "route_task")

    # route → 分发
    builder.add_conditional_edges("route_task", route_after_task, {
        "vision_direct": "vision_direct",
        "vision_schema": "vision_schema",
        "vision_perceive": "vision_perceive",
        "retrieve": "retrieve",
        "tool_act_placeholder": "tool_act_placeholder",
        "fallback": "fallback",
    })

    # VISION_DIRECT 路径
    builder.add_edge("vision_direct", "validate_direct")
    builder.add_edge("validate_direct", "respond")
    builder.add_edge("respond", "update_memory")
    builder.add_edge("update_memory", END)

    # VISION_SCHEMA 路径
    builder.add_edge("vision_schema", "validate_schema")
    builder.add_edge("validate_schema", "respond")

    # RAG_QA / VISION_REASON 路径
    builder.add_edge("vision_perceive", "retrieve")
    builder.add_edge("retrieve", "reason")
    builder.add_conditional_edges("reason", route_after_reason, {
        "verify": "verify",
        "respond": "respond",
    })
    builder.add_conditional_edges("verify", route_after_verify, {
        "reason": "reason",
        "respond": "respond",
    })

    # TOOL_ACT / Fallback → respond → END
    builder.add_edge("tool_act_placeholder", "respond")
    builder.add_edge("fallback", "respond")

    return builder.compile(checkpointer=MemorySaver())


# 全局编译实例
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_agent_graph()
        logger.info("LangGraph 主图已编译")
    return _compiled_graph
