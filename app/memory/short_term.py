"""
短期记忆模块 — V0

基于内存 dict 实现，生命周期 = 单次会话。
存储：对话历史、当前票据上下文、临时推理中间结果。

所有日志输出统一使用 logger_config.get_logger。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger_config import get_logger

logger = get_logger("short_term_memory")


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """单条对话消息"""
    role: str               # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass
class SessionContext:
    """会话上下文"""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    current_invoice: Optional[Dict[str, Any]] = None   # 当前处理的票据信息
    intermediate_results: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 短期记忆管理器
# ---------------------------------------------------------------------------

class ShortTermMemory:
    """短期记忆管理器 — 基于内存 OrderedDict

    用法::

        stm = ShortTermMemory(max_turns=20)
        stm.add_message("s1", "user", "这张发票的金额是多少？")
        history = stm.get_history("s1")
    """

    def __init__(self, max_turns: int = 20):
        """
        Args:
            max_turns: 每个会话最多保留的对话轮数（一轮 = 用户+助手）
        """
        self._sessions: Dict[str, SessionContext] = OrderedDict()
        self._max_turns = max_turns
        self._max_sessions = 1000  # 最多同时持有的会话数，超出则淘汰最旧的
        logger.info("短期记忆初始化完成 max_turns=%d max_sessions=%d",
                     max_turns, self._max_sessions)

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    def get_or_create_session(self, session_id: str) -> SessionContext:
        """获取或创建会话"""
        if session_id not in self._sessions:
            self._ensure_capacity()
            self._sessions[session_id] = SessionContext(session_id=session_id)
            logger.debug("创建新会话: %s", session_id)
        return self._sessions[session_id]

    def clear_session(self, session_id: str) -> None:
        """清除指定会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("会话已清除: %s", session_id)

    def session_exists(self, session_id: str) -> bool:
        return session_id in self._sessions

    # ------------------------------------------------------------------
    # 消息管理
    # ------------------------------------------------------------------

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加一条消息到会话"""
        session = self.get_or_create_session(session_id)
        msg = Message(role=role, content=content, metadata=metadata or {})
        session.messages.append(msg)
        session.updated_at = time.time()

        # 按 max_turns 裁剪（1 turn = user + assistant）
        max_messages = self._max_turns * 2 + 1  # +1 保留 system prompt
        if len(session.messages) > max_messages:
            # 保留 system 消息 + 最近 N 轮
            system_msgs = [m for m in session.messages if m.role == "system"]
            other_msgs = [m for m in session.messages if m.role != "system"]
            trimmed = other_msgs[-max_messages + len(system_msgs):]
            session.messages = system_msgs + trimmed
            logger.debug("会话 %s 消息已裁剪: %d → %d",
                         session_id, len(session.messages) + len(trimmed), len(session.messages))

        logger.debug("添加消息 session=%s role=%s content_len=%d",
                     session_id, role, len(content))

    def get_history(self, session_id: str, last_n: int = 0) -> List[Message]:
        """获取会话对话历史"""
        session = self._sessions.get(session_id)
        if session is None:
            return []
        if last_n > 0:
            return session.messages[-last_n:]
        return list(session.messages)

    def get_history_as_dicts(self, session_id: str, last_n: int = 0) -> List[Dict[str, Any]]:
        """获取对话历史（dict 形式，方便序列化）"""
        return [m.to_dict() for m in self.get_history(session_id, last_n)]

    # ------------------------------------------------------------------
    # 票据上下文
    # ------------------------------------------------------------------

    def set_invoice_context(self, session_id: str, invoice_data: Dict[str, Any]) -> None:
        """设置当前票据上下文"""
        session = self.get_or_create_session(session_id)
        session.current_invoice = invoice_data
        session.updated_at = time.time()
        logger.info("会话 %s 票据上下文已更新", session_id)

    def get_invoice_context(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取当前票据上下文"""
        session = self._sessions.get(session_id)
        return session.current_invoice if session else None

    # ------------------------------------------------------------------
    # 中间结果
    # ------------------------------------------------------------------

    def set_intermediate(
        self, session_id: str, key: str, value: Any
    ) -> None:
        """存储推理中间结果"""
        session = self.get_or_create_session(session_id)
        session.intermediate_results[key] = value
        session.updated_at = time.time()

    def get_intermediate(self, session_id: str, key: str) -> Optional[Any]:
        """获取推理中间结果"""
        session = self._sessions.get(session_id)
        return session.intermediate_results.get(key) if session else None

    def clear_intermediate(self, session_id: str) -> None:
        """清空中间结果"""
        session = self._sessions.get(session_id)
        if session:
            session.intermediate_results.clear()

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------

    def _ensure_capacity(self) -> None:
        """确保不会超出最大会话数"""
        while len(self._sessions) >= self._max_sessions:
            oldest_key, _ = self._sessions.popitem(last=False)
            logger.debug("淘汰最旧会话: %s", oldest_key)

    def get_session_count(self) -> int:
        return len(self._sessions)

    def get_message_count(self, session_id: str) -> int:
        session = self._sessions.get(session_id)
        return len(session.messages) if session else 0
