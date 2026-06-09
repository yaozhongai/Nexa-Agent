"""
长期记忆模块 — V0 (SQLAlchemy)

持久化存储票据、会话、消息、偏好、反思记录。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from app.storage.database import get_session, init_db
from app.storage.models import Invoice, Conversation, Message, Preference, Reflection
from app.utils.logger_config import get_logger

logger = get_logger("long_term_memory")


class LongTermMemory:
    """长期记忆管理器 — SQLAlchemy 后端"""

    def __init__(self, db_path: str = ""):
        init_db()
        logger.info("长期记忆初始化完成 (SQLAlchemy)")

    # ------------------------------------------------------------------
    # 票据
    # ------------------------------------------------------------------

    def save_invoice(self, session_id: str, invoice_data: Dict[str, Any]) -> int:
        s = get_session()
        try:
            inv = Invoice(
                session_id=session_id,
                filename=invoice_data.get("filename"),
                invoice_code=invoice_data.get("details", {}).get("invoice_code"),
                invoice_date=invoice_data.get("details", {}).get("invoice_date"),
                amount=invoice_data.get("details", {}).get("amount"),
                tax_number=invoice_data.get("details", {}).get("tax_number"),
            )
            inv.details = invoice_data.get("details", {})
            s.add(inv)
            s.commit()
            inv_id = inv.id
            logger.debug("保存票据 id=%d session=%s", inv_id, session_id)
            return inv_id
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_invoice(self, invoice_id: int) -> Optional[Dict[str, Any]]:
        s = get_session()
        try:
            inv = s.query(Invoice).filter_by(id=invoice_id).first()
            return _to_dict(inv) if inv else None
        finally:
            s.close()

    def search_invoices(
        self, session_id: str = "", invoice_code: str = "",
        start_date: str = "", end_date: str = "", limit: int = 20, offset: int = 0,
    ) -> List[Dict[str, Any]]:
        s = get_session()
        try:
            q = s.query(Invoice)
            if session_id:
                q = q.filter(Invoice.session_id == session_id)
            if invoice_code:
                q = q.filter(Invoice.invoice_code.like(f"%{invoice_code}%"))
            if start_date:
                q = q.filter(Invoice.invoice_date >= start_date)
            if end_date:
                q = q.filter(Invoice.invoice_date <= end_date)
            rows = q.order_by(Invoice.created_at.desc()).offset(offset).limit(limit).all()
            return [_to_dict(r) for r in rows]
        finally:
            s.close()

    def list_invoices(self, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        s = get_session()
        try:
            rows = s.query(Invoice).order_by(Invoice.created_at.desc()).offset(offset).limit(limit).all()
            return [_to_dict(r) for r in rows]
        finally:
            s.close()

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------

    def upsert_conversation(self, session_id: str, title: str = "", summary: str = "") -> None:
        s = get_session()
        try:
            conv = s.query(Conversation).filter_by(session_id=session_id).first()
            if conv:
                conv.title = title or conv.title
                conv.summary = summary or conv.summary
            else:
                s.add(Conversation(session_id=session_id, title=title, summary=summary))
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_conversation(self, session_id: str) -> Optional[Dict[str, Any]]:
        s = get_session()
        try:
            conv = s.query(Conversation).filter_by(session_id=session_id).first()
            return _to_dict(conv) if conv else None
        finally:
            s.close()

    # ------------------------------------------------------------------
    # 消息
    # ------------------------------------------------------------------

    def save_message(self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        s = get_session()
        try:
            msg = Message(session_id=session_id, role=role, content=content)
            if metadata:
                msg.meta = metadata
            s.add(msg)
            # 更新会话计数
            conv = s.query(Conversation).filter_by(session_id=session_id).first()
            if conv:
                conv.message_count = (conv.message_count or 0) + 1
            s.commit()
            return msg.id
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_messages(self, session_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        s = get_session()
        try:
            rows = s.query(Message).filter_by(session_id=session_id).order_by(Message.created_at.asc()).limit(limit).all()
            return [_to_dict(r) for r in rows]
        finally:
            s.close()

    # ------------------------------------------------------------------
    # 偏好
    # ------------------------------------------------------------------

    def set_preference(self, key: str, value: str) -> None:
        s = get_session()
        try:
            pref = s.query(Preference).filter_by(key=key).first()
            if pref:
                pref.value = value
            else:
                s.add(Preference(key=key, value=value))
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_preference(self, key: str, default: str = "") -> str:
        s = get_session()
        try:
            pref = s.query(Preference).filter_by(key=key).first()
            return pref.value if pref else default
        finally:
            s.close()

    def get_all_preferences(self) -> Dict[str, str]:
        s = get_session()
        try:
            return {p.key: p.value for p in s.query(Preference).all()}
        finally:
            s.close()

    # ------------------------------------------------------------------
    # 反思
    # ------------------------------------------------------------------

    def save_reflection(self, session_id: str, message_id: Optional[int], result: Dict[str, Any]) -> int:
        s = get_session()
        try:
            ref = Reflection(
                session_id=session_id, message_id=message_id,
                is_qualified=result.get("is_qualified", True),
                score=result.get("score", 0.0),
                suggestions=result.get("suggestions", ""),
                raw_output=result.get("raw_output", ""),
                elapsed_ms=result.get("elapsed_ms", 0),
            )
            ref.issues = result.get("issues", [])
            s.add(ref)
            s.commit()
            return ref.id
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_reflections(self, session_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        s = get_session()
        try:
            rows = s.query(Reflection).filter_by(session_id=session_id).order_by(Reflection.created_at.desc()).limit(limit).all()
            return [_to_dict(r) for r in rows]
        finally:
            s.close()

    def close(self) -> None:
        pass  # SQLAlchemy session 每次用完即关


def _to_dict(obj) -> Dict[str, Any]:
    """ORM 对象 → dict"""
    if obj is None:
        return {}
    d = {}
    for c in obj.__table__.columns:
        val = getattr(obj, c.name)
        if isinstance(val, bytes):
            val = val.decode("utf-8")
        d[c.name] = val
    return d
