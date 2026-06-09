"""
记忆管理接口 — V0

提供会话记忆的查询、偏好管理等功能。

日志统一使用 logger_config.get_logger。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import (
    ErrorResponse,
    MemoryListResponse,
    MemoryQueryRequest,
    PreferenceRequest,
    PreferenceResponse,
    get_long_term_memory,
    get_short_term_memory,
)
from app.utils.logger_config import get_logger

logger = get_logger("api_memory")

router = APIRouter(prefix="/api/v0/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# 会话记忆
# ---------------------------------------------------------------------------

@router.get(
    "/session/{session_id}",
    response_model=MemoryListResponse,
    summary="获取会话记忆",
)
async def get_session_memory(session_id: str, limit: int = 50):
    """获取指定会话的短期和长期记忆"""
    stm = get_short_term_memory()
    ltm = get_long_term_memory()

    short = stm.get_history_as_dicts(session_id)
    long_msgs = ltm.get_messages(session_id, limit=limit)
    conversation = ltm.get_conversation(session_id)

    logger.debug("会话记忆查询 session=%s st=%d lt=%d", session_id, len(short), len(long_msgs))

    return MemoryListResponse(
        total=len(short) + len(long_msgs),
        items=[{
            "short_term": short,
            "long_term": long_msgs,
            "conversation": conversation,
        }],
        limit=limit,
        offset=0,
    )


@router.delete(
    "/session/{session_id}",
    summary="清除会话记忆",
)
async def clear_session_memory(session_id: str):
    """清除指定会话的短期记忆"""
    stm = get_short_term_memory()
    stm.clear_session(session_id)
    logger.info("会话记忆已清除 session=%s", session_id)
    return {"session_id": session_id, "status": "cleared"}


# ---------------------------------------------------------------------------
# 票据查询
# ---------------------------------------------------------------------------

@router.get(
    "/invoices",
    response_model=MemoryListResponse,
    summary="查询历史票据",
)
async def list_invoices(limit: int = 50, offset: int = 0):
    """获取最近识别过的票据列表"""
    ltm = get_long_term_memory()
    invoices = ltm.list_invoices(limit=limit, offset=offset)

    logger.debug("票据列表查询 limit=%d offset=%d count=%d", limit, offset, len(invoices))

    return MemoryListResponse(
        total=len(invoices),
        items=invoices,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# 偏好管理
# ---------------------------------------------------------------------------

@router.get(
    "/preferences",
    summary="获取所有偏好设置",
)
async def get_preferences():
    """获取所有用户偏好"""
    ltm = get_long_term_memory()
    prefs = ltm.get_all_preferences()
    return {"preferences": prefs}


@router.post(
    "/preferences",
    response_model=PreferenceResponse,
    summary="设置用户偏好",
)
async def set_preference(req: PreferenceRequest):
    """设置单条偏好"""
    ltm = get_long_term_memory()
    ltm.set_preference(req.key, req.value)
    logger.info("偏好已设置: %s=%s", req.key, req.value)
    return PreferenceResponse(key=req.key, value=req.value)
