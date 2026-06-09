"""
Nexa Agent V0 — CLI

LangGraph 原生调用，不再依赖 AgentStateMachine / Handler。
"""

from __future__ import annotations

import argparse
import os
import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from app.agent.state import create_initial_state, to_public_response, ImageRef
from app.agent.graph import get_graph
from app.memory.long_term import LongTermMemory
from app.utils.logger_config import get_logger

logger = get_logger("cli")


def main():
    parser = argparse.ArgumentParser(description="Nexa Agent V0 CLI")
    parser.add_argument("--message", "-m", required=True)
    parser.add_argument("--image", "-i")
    parser.add_argument("--backend", "-b", default="deepseek",
                        choices=["deepseek", "kimi", "glm"])
    parser.add_argument("--model", default="")
    parser.add_argument("--session", "-s", default="cli-session")
    args = parser.parse_args()

    from app.core.config import get_config
    config = get_config()

    # 初始化 LLM（通过 deps）
    from app.llm.client import create_llm_client
    llm = create_llm_client(backend=args.backend, model=args.model or "")
    if not llm.is_available():
        logger.error("LLM 不可用: backend=%s", args.backend)
        sys.exit(1)

    # 注入依赖
    import app.api.deps as deps
    deps._llm_client = llm
    from app.memory.short_term import ShortTermMemory
    from app.pipeline.extractor import ExtractionPipeline
    from app.pipeline.ollama_vlm import OllamaVLMEngine
    stm = ShortTermMemory(max_turns=config.short_term_max_turns)
    ltm = LongTermMemory(db_path=config.db_path)
    pipeline = ExtractionPipeline()
    if config.vlm_enabled:
        vlm = OllamaVLMEngine(model=config.vlm_model_name, base_url=config.vlm_base_url,
                               ctx_size=config.vlm_ctx_size)
        pipeline.set_vlm_engine(vlm)
        pipeline.set_prefer_mode("vlm")
    deps._short_term_memory = stm
    deps._long_term_memory = ltm
    deps._extraction_pipeline = pipeline

    # 构造初始状态
    imgs = [ImageRef(image_id="cli_1", path=args.image)] if args.image else []
    state = create_initial_state(
        user_input=args.message,
        session_id=args.session,
        image_refs=imgs,
    )

    # Trace
    from app.trace.service import create_trace_run, complete_trace_run, emit_trace_event
    from app.trace.schema import TraceEventType

    rid = state.get("request_id", "")
    create_trace_run(request_id=rid, session_id=args.session or "cli")

    # LangGraph 原生调用
    graph = get_graph()
    result = graph.invoke(state, {
        "configurable": {"thread_id": args.session},
        "recursion_limit": 30,
    })

    # 从 action_trace 发射 Trace 事件
    for item in result.get("action_trace", []):
        if item.node:
            emit_trace_event(
                trace_id=rid, request_id=rid, session_id=args.session or "cli",
                event_type=TraceEventType.NODE_COMPLETED,
                title=item.node, node_name=item.node,
                duration_ms=item.latency_ms or 0,
            )

    pub = to_public_response(result)

    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("🤖 %s", pub.get("answer", ""))
    route = pub.get("route", {})
    route_type = route.get("route_type", "") if route else ""
    trace_nodes = [t["node"] for t in pub.get("trace", [])]
    logger.info("📈 %s | path=%s", route.get("route_type", ""), "→".join(trace_nodes))

    # 完成 Trace + 展示
    complete_trace_run(rid, final_answer_summary=pub.get("answer", "")[:200])

    from app.trace.service import get_trace_events
    events = get_trace_events(rid)
    if events:
        parts = []
        for e in events:
            if e.node_name:
                dur = f" {e.duration_ms}ms" if e.duration_ms else ""
                parts.append(f"{e.node_name}{dur}")
        logger.info("  ⏱ %s", " → ".join(parts))
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    ltm.close()


if __name__ == "__main__":
    main()
