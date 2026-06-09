"""
SQLAlchemy ORM 模型

包含全部表的定义:
  invoices, conversations, messages, preferences, reflections
  agent_trace_runs, agent_trace_events
"""

import json
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Index,
)
from sqlalchemy.orm import relationship

from app.storage.database import Base


# ======================================================================
# 业务表
# ======================================================================

class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    filename = Column(String(512))
    invoice_code = Column(String(64))
    invoice_date = Column(String(32))
    amount = Column(Float)
    tax_number = Column(String(64))
    details_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def details(self) -> dict:
        return json.loads(self.details_json) if self.details_json else {}

    @details.setter
    def details(self, value: dict):
        self.details_json = json.dumps(value, ensure_ascii=False)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), unique=True, nullable=False, index=True)
    title = Column(String(256))
    summary = Column(Text)
    message_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    role = Column(String(32), nullable=False)
    content = Column(Text, nullable=False)
    metadata_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    @property
    def meta(self) -> dict:
        return json.loads(self.metadata_json) if self.metadata_json else {}

    @meta.setter
    def meta(self, value: dict):
        self.metadata_json = json.dumps(value, ensure_ascii=False)


class ImageAnalysisCache(Base):
    __tablename__ = "image_analysis_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(String(128), unique=True, nullable=False, index=True)
    file_sha256 = Column(String(128), unique=True, nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    image_path = Column(String(1024), nullable=False)
    filename = Column(String(512))
    content_type = Column(String(128))
    model_name = Column(String(256))
    vlm_text = Column(Text)
    structured_data_json = Column(Text, default="{}")
    status = Column(String(32), nullable=False, default="success")
    latency_ms = Column(Integer)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def structured_data(self) -> dict:
        return json.loads(self.structured_data_json) if self.structured_data_json else {}

    @structured_data.setter
    def structured_data(self, value: dict):
        self.structured_data_json = json.dumps(value or {}, ensure_ascii=False)


class Preference(Base):
    __tablename__ = "preferences"

    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Reflection(Base):
    __tablename__ = "reflections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), nullable=False, index=True)
    message_id = Column(Integer)
    is_qualified = Column(Boolean, default=True)
    score = Column(Float, default=0.0)
    issues_json = Column(Text, default="[]")
    suggestions = Column(Text)
    raw_output = Column(Text)
    elapsed_ms = Column(Float)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def issues(self) -> list:
        return json.loads(self.issues_json) if self.issues_json else []

    @issues.setter
    def issues(self, value: list):
        self.issues_json = json.dumps(value, ensure_ascii=False)


# ======================================================================
# Trace 表
# ======================================================================

class AgentTraceRun(Base):
    __tablename__ = "agent_trace_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(128), unique=True, nullable=False, index=True)
    request_id = Column(String(128), nullable=False, index=True)
    session_id = Column(String(128), nullable=False, index=True)
    user_id = Column(String(128))
    route_type = Column(String(64))
    status = Column(String(32), nullable=False, default="running")
    current_node = Column(String(64))
    started_at = Column(Float, nullable=False)
    finished_at = Column(Float)
    duration_ms = Column(Integer)
    event_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    model_call_count = Column(Integer, default=0)
    tool_call_count = Column(Integer, default=0)
    final_answer_summary = Column(Text)
    created_at = Column(Float, nullable=False)
    updated_at = Column(Float, nullable=False)


class AgentTraceEvent(Base):
    __tablename__ = "agent_trace_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), unique=True, nullable=False)
    trace_id = Column(String(128), nullable=False, index=True)
    request_id = Column(String(128), nullable=False)
    session_id = Column(String(128), nullable=False)
    seq = Column(Integer, nullable=False)
    event_type = Column(String(64), nullable=False)
    event_status = Column(String(32), nullable=False, default="success")
    event_level = Column(String(32), nullable=False, default="info")
    visibility = Column(String(32), nullable=False, default="user")
    node_name = Column(String(64))
    title = Column(String(256), nullable=False)
    message = Column(Text)
    input_summary = Column(Text)
    output_summary = Column(Text)
    payload_json = Column(Text)
    duration_ms = Column(Integer)
    error_type = Column(String(64))
    error_message = Column(Text)
    created_at = Column(Float, nullable=False)

    __table_args__ = (
        Index("idx_trace_events_seq", "trace_id", "seq"),
    )
