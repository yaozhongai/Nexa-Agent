"""
AgentState — LangGraph 全局状态协议 V2

原则：
- AgentState 是 TypedDict，不是 Pydantic 大对象
- 所有节点返回 partial update dict
- 追加型字段使用 reducer
- to_public_response() 是唯一对外出口
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field
from typing_extensions import Annotated, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.message import add_messages


# ======================================================================
# Reducers
# ======================================================================

def append_list(old: Optional[list], new: Optional[list]) -> list:
    if old is None: old = []
    if new is None: new = []
    return old + new


def merge_dict(old: Optional[dict], new: Optional[dict]) -> dict:
    if old is None: old = {}
    if new is None: new = {}
    return {**old, **new}


# ======================================================================
# 枚举
# ======================================================================

class InputType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    MULTIMODAL = "multimodal"
    FILE = "file"


class RouteType(str, Enum):
    VISION_DIRECT = "vision_direct"
    VISION_SCHEMA = "vision_schema"
    RAG_QA = "rag_qa"
    TOOL_ACT = "tool_act"
    FALLBACK = "fallback"


class RunStatus(str, Enum):
    INIT = "init"
    NORMALIZED = "normalized"
    ROUTED = "routed"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    WAITING_HUMAN_CONFIRM = "waiting_human_confirm"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ObservationSource(str, Enum):
    USER = "user"
    VLM = "vlm"
    LLM = "llm"
    MEMORY = "memory"
    DOCUMENT = "document"
    TOOL = "tool"
    VERIFIER = "verifier"
    SYSTEM = "system"


class ToolCallStatus(str, Enum):
    PLANNED = "planned"
    VALIDATED = "validated"
    WAITING_CONFIRM = "waiting_confirm"
    EXECUTING = "executing"
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class ConfirmDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EDITED = "edited"


# ======================================================================
# 子 Schema (Pydantic BaseModel)
# ======================================================================

class ImageRef(BaseModel):
    image_id: str
    path: Optional[str] = None
    url: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    source: Literal["upload", "clipboard", "api", "local"] = "upload"


class FileRef(BaseModel):
    file_id: str
    filename: Optional[str] = None
    path: Optional[str] = None
    url: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    source: Literal["upload", "api", "local"] = "upload"


class RouteResult(BaseModel):
    route_type: RouteType
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    matched_rules: list[str] = Field(default_factory=list)
    need_retrieve: bool = False
    need_reason: bool = False
    need_verify: bool = False
    need_memory_write: bool = False
    risk_level: RiskLevel = RiskLevel.LOW


class ActionTraceItem(BaseModel):
    step: int
    node: str
    action: str
    status: StepStatus = StepStatus.PENDING
    reason: str = ""
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    latency_ms: Optional[int] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    error_message: Optional[str] = None


class Observation(BaseModel):
    source: ObservationSource
    content: str
    structured_data: Optional[dict[str, Any]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    source_id: Optional[str] = None
    node: Optional[str] = None


class EvidenceItem(BaseModel):
    source_type: Literal["image","memory","document","tool","model","user"]
    content: str
    source_id: Optional[str] = None
    title: Optional[str] = None
    score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCallRecord(BaseModel):
    provider: Optional[str] = None
    model_name: str
    node: str
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None


class ToolCallRecord(BaseModel):
    tool_call_id: str
    tool_name: str
    tool_input: dict[str, Any]
    status: ToolCallStatus = ToolCallStatus.PLANNED
    risk_level: RiskLevel = RiskLevel.LOW
    require_human_confirm: bool = False
    confirm_reason: Optional[str] = None
    tool_output: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    latency_ms: Optional[int] = None


class ValidationResult(BaseModel):
    validator_name: str
    passed: bool
    issues: list[str] = Field(default_factory=list)
    revised_answer: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class HumanConfirmRequest(BaseModel):
    confirm_id: str
    reason: str
    risk_level: RiskLevel
    tool_call: Optional[ToolCallRecord] = None
    question: Optional[str] = None
    options: list[str] = Field(default_factory=list)


class HumanConfirmResult(BaseModel):
    confirm_id: str
    decision: ConfirmDecision
    comment: Optional[str] = None
    edited_payload: Optional[dict[str, Any]] = None


class AgentError(BaseModel):
    error_type: str
    message: str
    node: Optional[str] = None
    recoverable: bool = True
    detail: dict[str, Any] = Field(default_factory=dict)


# ======================================================================
# AgentState — TypedDict + Reducer
# ======================================================================

class AgentState(TypedDict, total=False):
    # 基础标识
    request_id: str
    session_id: str
    user_id: Optional[str]

    # 输入
    user_input: str
    input_type: InputType
    image_refs: list[ImageRef]
    file_refs: list[FileRef]
    input_metadata: Annotated[dict[str, Any], merge_dict]

    # LangGraph 消息
    messages: Annotated[list[BaseMessage], add_messages]

    # 会话上下文
    history_summary: Optional[str]
    short_term_context: list[dict[str, Any]]

    # 路由
    route_result: Optional[RouteResult]

    # 运行状态
    status: RunStatus
    step_count: int
    max_steps: int

    # 检索与证据
    memory_candidates: Annotated[list[EvidenceItem], append_list]
    retrieved_context: Annotated[list[EvidenceItem], append_list]
    evidence: Annotated[list[EvidenceItem], append_list]

    # 模型 / 感知 / 工具观察
    observations: Annotated[list[Observation], append_list]
    model_calls: Annotated[list[ModelCallRecord], append_list]
    tool_calls: Annotated[list[ToolCallRecord], append_list]
    tool_results: Annotated[list[ToolCallRecord], append_list]

    # ReAct 中间控制
    pending_tool_call: Optional[ToolCallRecord]
    react_decision_summary: Optional[str]
    react_finished: bool

    # 校验
    validation_results: Annotated[list[ValidationResult], append_list]

    # 人工确认 / 用户追问
    need_user_clarification: bool
    clarification_question: Optional[str]
    need_human_confirm: bool
    human_confirm_request: Optional[HumanConfirmRequest]
    human_confirm_result: Optional[HumanConfirmResult]

    # 执行轨迹
    action_trace: Annotated[list[ActionTraceItem], append_list]

    # 错误
    errors: Annotated[list[AgentError], append_list]

    # 输出
    final_answer: Optional[str]
    structured_output: Optional[dict[str, Any]]
    confidence: Optional[float]

    # Debug
    debug: bool
    debug_info: Annotated[dict[str, Any], merge_dict]


# ======================================================================
# 构造函数
# ======================================================================

def infer_input_type(
    user_input: str,
    image_refs: list[ImageRef],
    file_refs: list[FileRef],
) -> InputType:
    has_text = bool(user_input.strip())
    has_image = bool(image_refs)
    has_file = bool(file_refs)
    if has_text and has_image: return InputType.MULTIMODAL
    if has_image: return InputType.IMAGE
    if has_file: return InputType.FILE
    return InputType.TEXT


def create_initial_state(
    user_input: str,
    session_id: str,
    request_id: Optional[str] = None,
    user_id: Optional[str] = None,
    image_refs: list[ImageRef] | None = None,
    file_refs: list[FileRef] | None = None,
    input_metadata: Optional[dict[str, Any]] = None,
    debug: bool = False,
    max_steps: int = 6,
) -> AgentState:
    image_refs = image_refs or []
    file_refs = file_refs or []

    if not user_input.strip() and not image_refs and not file_refs:
        raise ValueError("user_input、image_refs、file_refs 不能同时为空")

    input_type = infer_input_type(user_input, image_refs, file_refs)

    return {
        "request_id": request_id or str(uuid4()),
        "session_id": session_id,
        "user_id": user_id,
        "user_input": user_input,
        "input_type": input_type,
        "image_refs": image_refs,
        "file_refs": file_refs,
        "input_metadata": input_metadata or {},
        "messages": [HumanMessage(content=user_input)] if user_input else [],
        "history_summary": None,
        "short_term_context": [],
        "route_result": None,
        "status": RunStatus.INIT,
        "step_count": 0,
        "max_steps": max_steps,
        "memory_candidates": [],
        "retrieved_context": [],
        "evidence": [],
        "observations": [],
        "model_calls": [],
        "tool_calls": [],
        "tool_results": [],
        "pending_tool_call": None,
        "react_decision_summary": None,
        "react_finished": False,
        "validation_results": [],
        "need_user_clarification": False,
        "clarification_question": None,
        "need_human_confirm": False,
        "human_confirm_request": None,
        "human_confirm_result": None,
        "action_trace": [],
        "errors": [],
        "final_answer": None,
        "structured_output": None,
        "confidence": None,
        "debug": debug,
        "debug_info": {},
    }


# ======================================================================
# Patch Helpers
# ======================================================================

def trace_patch(
    *, step: int, node: str, action: str, status: StepStatus,
    reason: str = "", input_summary: Optional[str] = None,
    output_summary: Optional[str] = None, latency_ms: Optional[int] = None,
    confidence: Optional[float] = None, error_message: Optional[str] = None,
) -> dict:
    return {"action_trace": [ActionTraceItem(
        step=step, node=node, action=action, status=status, reason=reason,
        input_summary=input_summary, output_summary=output_summary,
        latency_ms=latency_ms, confidence=confidence, error_message=error_message,
    )]}


def error_patch(
    *, error_type: str, message: str, node: Optional[str] = None,
    recoverable: bool = True, detail: Optional[dict[str, Any]] = None,
) -> dict:
    return {"errors": [AgentError(
        error_type=error_type, message=message, node=node,
        recoverable=recoverable, detail=detail or {},
    )]}


def final_answer_patch(
    *, final_answer: str, structured_output: Optional[dict[str, Any]] = None,
    confidence: Optional[float] = None,
) -> dict:
    return {
        "final_answer": final_answer,
        "structured_output": structured_output,
        "confidence": confidence,
        "status": RunStatus.COMPLETED,
    }


# ======================================================================
# 对外响应过滤
# ======================================================================

def to_public_response(state: AgentState) -> dict[str, Any]:
    route = state.get("route_result")
    return {
        "request_id": state.get("request_id"),
        "session_id": state.get("session_id"),
        "status": state.get("status"),
        "answer": state.get("final_answer"),
        "structured_output": state.get("structured_output"),
        "confidence": state.get("confidence"),
        "route": route.model_dump() if route else None,
        "need_user_clarification": state.get("need_user_clarification", False),
        "clarification_question": state.get("clarification_question"),
        "need_human_confirm": state.get("need_human_confirm", False),
        "human_confirm_request": (
            state["human_confirm_request"].model_dump()
            if state.get("human_confirm_request") else None
        ),
        "trace": [item.model_dump() for item in state.get("action_trace", [])],
        "errors": [
            {"error_type": e.error_type, "message": e.message,
             "node": e.node, "recoverable": e.recoverable}
            for e in state.get("errors", [])
        ],
    }
