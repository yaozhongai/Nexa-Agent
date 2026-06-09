# Short-Term Memory Schema 设计文档

> 版本：V0.2 | 日期：2026-06-10
> 目标：为 Nexa Agent 提供会话级短期上下文缓存能力
> 原则：Short-Term Memory 负责当前会话上下文，AgentState 负责运行时状态协议，AgentTrace 负责执行轨迹事件流，三者边界清晰、不互相替代。
> 实现状态：已完成。STM 每轮对话始终写入（不受 need_memory_write 门控），LTM 由门控独立控制。

---

## 1. 模块概述

### 1.1 做什么

`Short-Term Memory` 是 Nexa Agent 的会话级上下文缓存模块。

它主要负责：

1. 记录当前会话内的用户输入、助手回答、工具观察、视觉观察、文件引用等上下文信息；
2. 为多轮对话提供最近上下文；
3. 为 ReAct 子图提供可回溯的 Action / Observation 摘要；
4. 为 `AgentState.short_term_context` 提供结构化上下文；
5. 支持图片、文件等多模态引用在多轮对话中的复用；
6. 支持根据 token budget 构建 LLM 上下文窗口（Turn 级别裁剪，保证 QA 完整性）；
7. 支持会话超时、挂起、归档和清理；
8. **每轮对话始终写入 STM**（不受 `need_memory_write` 门控），保证多轮上下文连续。

### 1.2 不做什么

`Short-Term Memory` 不负责：

1. 不决定 LangGraph 节点流转；
2. 不替代 `AgentState`；
3. 不替代 `AgentTrace`；
4. 不保存完整 Chain-of-Thought；
5. 不保存完整 prompt；
6. 不保存完整 raw model output；
7. 不作为长期记忆；
8. 不做语义压缩和反思总结；
9. 不做跨 session 的用户画像沉淀；
10. 不保存图片、文件二进制本体，只保存引用。

---

## 2. 与 AgentState / AgentTrace 的边界

### 2.1 与 AgentState 的关系

`AgentState` 是一次请求在 LangGraph 节点之间传递的运行时状态。

`Short-Term Memory` 是当前会话的上下文缓存。

关系如下：

```text
Short-Term Memory
    ↓ get_recent_context()
AgentState.short_term_context
    ↓
LangGraph Nodes / ReAct Subgraph
```

约束：

1. `Short-Term Memory` 不修改 LangGraph 流程；
2. LangGraph 节点只通过 memory service 读取或写入短期记忆；
3. `AgentState.short_term_context` 只是一次请求中的上下文快照；
4. 短期记忆的真实数据不直接塞进 `AgentState`；
5. `AgentState.messages` 仍由 LangGraph / LangChain 消息机制管理；
6. `Short-Term Memory` 只向 `AgentState.short_term_context` 提供可控、裁剪后的上下文。

---

### 2.2 与 AgentTrace 的关系

`AgentTrace` 是一次请求的执行轨迹事件流。

`Short-Term Memory` 是会话上下文缓存。

关系如下：

```text
memory_read / memory_write
        ↓
Short-Term Memory Store
        ↓
emit AgentTraceEvent:
  - memory_read_started
  - memory_read_completed
  - memory_write_started
  - memory_write_completed
  - memory_write_skipped
  - memory_write_failed
```

约束：

1. 不创建 `agent_trace_runs`；
2. 不创建 `agent_trace_events`；
3. 不保存 `AgentTraceEvent` 列表；
4. 只允许保存 `trace_id` / `request_id` 作为可选关联字段；
5. Trace 可记录短期记忆读写事件，但短期记忆不是 Trace Store；
6. 前端 Timeline 仍由 `AgentTraceEvent` 派生，不直接解析短期记忆表。

---

### 2.3 三者职责分工

| 模块 | 职责 | 是否持久化 | 是否参与图执行 |
|------|------|-----------|--------------|
| `AgentState` | 单次请求运行时状态协议 | 可落摘要，不负责完整持久化 | 是 |
| `AgentTrace` | 执行轨迹、SSE、前端 Timeline、调试回放 | 是 | 否 |
| Short-Term Memory **Store** | 当前 session 的上下文缓存数据层 | 临时存储 / TTL 存储 | **否**（纯数据层） |
| `load_short_term_context` / `update_memory` **Nodes** | LangGraph 图节点，读写 STM Store | — | **是**（图节点） |

> 类比：SQLite 不参与图执行，但节点可以调用 `LongTermMemory` 的 CRUD 方法。Store 是数据层，Node 是执行层。

---

## 3. 数据流

### 3.1 整体数据流

```text
FastAPI 接收请求
    ↓
create_initial_state()
    ↓
load_short_term_context()
    ↓
写入 AgentState.short_term_context
    ↓
compiled_graph.invoke() / stream()
    ↓
LangGraph 主流程 / ReAct 子图
    ↓
respond
    ↓
update_short_term_memory()
    ↓
短期记忆写入
    ↓
emit memory_write_completed / memory_write_skipped
```

---

### 3.2 多轮对话数据流

```text
第 1 轮：
用户输入 + 图片
    ↓
写入 stm_turns / stm_entries
    ↓
回答完成后写入 assistant_answer
    ↓
图片引用保留在 stm_entries.asset_refs

第 2 轮：
用户追问：“这张图里还有什么？”
    ↓
读取最近 N 轮上下文
    ↓
取回上一轮 image_refs
    ↓
写入 AgentState.short_term_context
    ↓
VLM / LLM 节点可复用图片引用
```

---

### 3.3 ReAct 数据流

```text
react_decide
    ↓
tool_call_planned
    ↓
tool_call_completed
    ↓
observation_recorded
    ↓
append_memory_entry(entry_type="tool_observation")
    ↓
get_recent_context()
    ↓
react_decide 下一轮
```

注意：

`Short-Term Memory` 只保存可审计摘要，例如：

```text
action_summary
observation_summary
tool_result_summary
decision_summary
```

不保存完整隐藏推理过程。

---

## 4. 枚举定义

```python
from enum import Enum


class STMSessionStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"
    EXPIRED = "expired"


class STMTurnStatus(str, Enum):
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class STMEntryRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
    OBSERVER = "observer"


class STMEntryType(str, Enum):
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    FINAL_ANSWER = "final_answer"

    ROUTE_SUMMARY = "route_summary"
    DECISION_SUMMARY = "decision_summary"
    ACTION_SUMMARY = "action_summary"
    OBSERVATION_SUMMARY = "observation_summary"

    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_OBSERVATION = "tool_observation"

    VISION_OBSERVATION = "vision_observation"
    DOCUMENT_CONTEXT = "document_context"

    USER_CLARIFICATION = "user_clarification"
    HUMAN_CONFIRM_RESULT = "human_confirm_result"

    ERROR_SUMMARY = "error_summary"


class STMAssetType(str, Enum):
    IMAGE = "image"
    FILE = "file"
    URL = "url"


class STMSourceModule(str, Enum):
    FASTAPI = "fastapi"
    AGENT_NODE = "agent_node"
    REACT_SUBGRAPH = "react_subgraph"
    TOOL = "tool"
    VLM = "vlm"
    LLM = "llm"
    MEMORY = "memory"
    SYSTEM = "system"
```

#### ObservationSource → STMSourceModule 映射

`ObservationSource`（AgentState 内部视角）和 `STMSourceModule`（记忆存储视角）
服务于不同层次，不强行合并。写入短期记忆时按以下映射转换：

| ObservationSource | STMSourceModule | 说明 |
|-------------------|-----------------|------|
| `USER` | `FASTAPI` | 用户输入由 API 层写入 |
| `VLM` | `VLM` | 直通 |
| `LLM` | `LLM` | 直通 |
| `MEMORY` | `MEMORY` | 直通 |
| `TOOL` | `TOOL` | 直通 |
| `VERIFIER` | `SYSTEM` | 校验器归类为系统模块 |
| `DOCUMENT` | `MEMORY` | 文档上下文归类为记忆 |
| `SYSTEM` | `SYSTEM` | 直通 |

---

## 5. 表 / 集合设计

V0 阶段建议使用以下逻辑集合：

```text
stm_sessions
stm_turns
stm_entries
stm_context_snapshots
```

说明：

1. `stm_` 前缀用于避免与 `agent_trace_*`、`AgentState` 字段名冲突；
2. V0 可用 Redis / SQLite / 内存 Store 实现；
3. 生产建议使用 Redis TTL 作为主实现；
4. SQLite / PostgreSQL 仅作为开发调试或可选降级方案；
5. 这些集合不是长期记忆表，不进入长期画像系统。

---

### 5.1 `stm_sessions`

记录一个短期记忆会话。

| 字段名                | 类型                                              | 必填 | 设计理由                                 |
| ------------------ | ----------------------------------------------- | -- | ------------------------------------ |
| `session_id`       | String / UUID                                   | ✅  | 会话唯一 ID，与 `AgentState.session_id` 对齐 |
| `user_id`          | String nullable                                 |    | 用户 ID，用于隔离不同用户的会话                    |
| `status`           | Enum: `active / suspended / archived / expired` | ✅  | 控制会话生命周期                             |
| `started_at`       | Timestamp                                       | ✅  | 会话开始时间                               |
| `last_accessed_at` | Timestamp                                       | ✅  | 最近一次读写时间，用于 TTL 刷新                   |
| `suspended_at`     | Timestamp nullable                              |    | 会话被挂起时间                              |
| `archived_at`      | Timestamp nullable                              |    | 会话归档时间                               |
| `expires_at`       | Timestamp nullable                              |    | TTL 到期时间                             |
| `turn_count`       | Integer                                         | ✅  | 已完成或进行中的对话轮数                         |
| `entry_count`      | Integer                                         | ✅  | 当前 session 下的 entry 数量               |
| `last_request_id`  | String nullable                                 |    | 最近一次请求 ID                            |
| `last_trace_id`    | String nullable                                 |    | 最近一次 Trace ID，仅用于关联，不替代 Trace        |
| `metadata`         | JSON                                            | ✅  | 客户端、入口、调试标记等扩展信息                     |

---

### 5.2 `stm_turns`

记录一次用户请求到助手响应的完整轮次。

一轮通常对应一个 `request_id`。

| 字段名                    | 类型                                                         | 必填 | 设计理由                             |
| ---------------------- | ---------------------------------------------------------- | -- | -------------------------------- |
| `turn_id`              | String / UUID                                              | ✅  | 单轮对话唯一 ID                        |
| `session_id`           | String / UUID                                              | ✅  | 关联 `stm_sessions.session_id`     |
| `request_id`           | String / UUID                                              | ✅  | 对应 `AgentState.request_id`       |
| `trace_id`             | String / UUID nullable                                     |    | 可选关联 AgentTraceRun               |
| `turn_index`           | Integer                                                    | ✅  | session 内单调递增，用于稳定回溯             |
| `status`               | Enum: `started / running / completed / failed / cancelled` | ✅  | 当前轮次状态                           |
| `input_type`           | String                                                     | ✅  | text / image / multimodal / file |
| `user_input_summary`   | Text nullable                                              |    | 用户输入摘要，避免超长文本直接进入上下文             |
| `route_type`           | String nullable                                            |    | 路由结果摘要                           |
| `final_answer_summary` | Text nullable                                              |    | 最终回答摘要                           |
| `asset_refs`           | JSON                                                       | ✅  | 当前轮涉及的图片 / 文件引用                  |
| `token_estimate`       | Integer nullable                                           |    | 本轮上下文 token 估算                   |
| `started_at`           | Timestamp                                                  | ✅  | 轮次开始时间                           |
| `completed_at`         | Timestamp nullable                                         |    | 轮次完成时间                           |
| `metadata`             | JSON                                                       | ✅  | 扩展信息                             |

约束：

1. `turn_index` 只在同一个 `session_id` 内递增；
2. 不依赖 `created_at` 排序；
3. `trace_id` 只能作为关联字段，不能反向读取 Trace 事件作为短期记忆；
4. `final_answer_summary` 不保存完整长回答，完整回答如需展示应由响应层或消息层管理。

---

### 5.3 `stm_entries`

记录会话中的细粒度上下文条目。

| 字段名               | 类型                                                  | 必填 | 设计理由                          |
| ----------------- | --------------------------------------------------- | -- | ----------------------------- |
| `entry_id`        | String / UUID                                       | ✅  | 单条记忆唯一 ID                     |
| `session_id`      | String / UUID                                       | ✅  | 关联 session                    |
| `turn_id`         | String / UUID                                       | ✅  | 关联 turn                       |
| `request_id`      | String / UUID                                       | ✅  | 对应单次请求                        |
| `trace_id`        | String / UUID nullable                              |    | 可选关联 Trace                    |
| `entry_index`     | Integer                                             | ✅  | session 内单调递增，用于稳定排序          |
| `role`            | Enum: `user / assistant / tool / system / observer` | ✅  | 条目来源角色                        |
| `entry_type`      | Enum                                                | ✅  | 条目类型                          |
| `source_module`   | Enum nullable                                       |    | 来源模块，如 VLM / LLM / Tool |
| `node_name`       | String nullable                                     |    | 可选关联 LangGraph node           |
| `tool_call_id`    | String nullable                                     |    | 工具调用 ID，兼容 ReAct / AgentTrace |
| `tool_name`       | String nullable                                     |    | 工具名称                          |
| `content`         | Text                                                | ✅  | 可进入上下文的文本内容，必须是摘要或用户可见内容      |
| `structured_data` | JSON nullable                                       |    | 结构化结果，如 VLM 提取字段、工具返回摘要         |
| `asset_refs`      | JSON                                                | ✅  | 图片、文件、URL 引用                  |
| `importance`      | Float nullable                                      |    | 0-1，可用于上下文裁剪                  |
| `confidence`      | Float nullable                                      |    | 0-1，来源模块置信度                   |
| `token_estimate`  | Integer nullable                                    |    | 当前条目 token 估算                 |
| `visible_to_llm`  | Boolean                                             | ✅  | 是否允许进入 LLM 上下文                |
| `visible_to_user` | Boolean                                             | ✅  | 是否允许前端展示                      |
| `created_at`      | Timestamp                                           | ✅  | 创建时间                          |
| `metadata`        | JSON                                                | ✅  | 扩展信息                          |

约束：

1. `content` 不允许保存完整 CoT；
2. `content` 不允许保存完整 prompt；
3. `structured_data` 可保存工具结果的裁剪版；
4. `asset_refs` 只保存引用，不保存二进制；
5. `entry_index` 必须在同一个 session 内单调递增；
6. `visible_to_llm = False` 的条目不能进入 `AgentState.short_term_context`。

---

### 5.4 `stm_context_snapshots`

记录某次请求实际注入到 `AgentState.short_term_context` 的上下文快照。

该集合是可选集合，V0 可先不实现；如果要调试上下文窗口裁剪，建议实现。

| 字段名              | 类型                     | 必填 | 设计理由                                     |
| ---------------- | ---------------------- | -- | ---------------------------------------- |
| `snapshot_id`    | String / UUID          | ✅  | 快照唯一 ID                                  |
| `session_id`     | String / UUID          | ✅  | 关联 session                               |
| `request_id`     | String / UUID          | ✅  | 当前请求 ID                                  |
| `trace_id`       | String / UUID nullable |    | 可选关联 Trace                               |
| `entry_ids`      | JSON Array             | ✅  | 本次上下文使用了哪些 stm_entries                   |
| `context_items`  | JSON Array             | ✅  | 实际写入 `AgentState.short_term_context` 的内容 |
| `token_budget`   | Integer                | ✅  | 上下文预算                                    |
| `token_estimate` | Integer                | ✅  | 实际估算 token                               |
| `strategy`       | String                 | ✅  | 裁剪策略，如 recent_first / importance_first   |
| `created_at`     | Timestamp              | ✅  | 创建时间                                     |
| `metadata`       | JSON                   | ✅  | 扩展信息                                     |

约束：

1. 快照只用于调试与复现；
2. 不作为 AgentTrace Timeline 数据源；
3. 不保存完整模型输入 prompt；
4. 不保存敏感 debug 信息；
5. 默认只保存摘要化后的 `context_items`。

---

## 6. Schema 定义

### 6.1 资产引用

```python
from typing import Any
from pydantic import BaseModel, Field
from datetime import datetime


class STMAssetRef(BaseModel):
    asset_id: str
    asset_type: STMAssetType

    image_id: str | None = None
    file_id: str | None = None

    path: str | None = None
    url: str | None = None
    mime_type: str | None = None
    filename: str | None = None

    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None

    source: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 6.2 短期记忆会话

```python
class STMSession(BaseModel):
    session_id: str
    user_id: str | None = None

    status: STMSessionStatus = STMSessionStatus.ACTIVE

    started_at: datetime = Field(default_factory=datetime.utcnow)
    last_accessed_at: datetime = Field(default_factory=datetime.utcnow)

    suspended_at: datetime | None = None
    archived_at: datetime | None = None
    expires_at: datetime | None = None

    turn_count: int = 0
    entry_count: int = 0

    last_request_id: str | None = None
    last_trace_id: str | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 6.3 对话轮次

```python
class STMTurn(BaseModel):
    turn_id: str
    session_id: str
    request_id: str
    trace_id: str | None = None

    turn_index: int
    status: STMTurnStatus = STMTurnStatus.STARTED

    input_type: str
    user_input_summary: str | None = None

    route_type: str | None = None
    final_answer_summary: str | None = None

    asset_refs: list[STMAssetRef] = Field(default_factory=list)

    token_estimate: int | None = None

    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 6.4 记忆条目

```python
class STMEntry(BaseModel):
    entry_id: str
    session_id: str
    turn_id: str
    request_id: str
    trace_id: str | None = None

    entry_index: int

    role: STMEntryRole
    entry_type: STMEntryType

    source_module: STMSourceModule | None = None
    node_name: str | None = None

    tool_call_id: str | None = None
    tool_name: str | None = None

    content: str
    structured_data: dict[str, Any] | None = None

    asset_refs: list[STMAssetRef] = Field(default_factory=list)

    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    token_estimate: int | None = None

    visible_to_llm: bool = True
    visible_to_user: bool = False

    created_at: datetime = Field(default_factory=datetime.utcnow)

    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 6.5 上下文快照

```python
class STMContextSnapshot(BaseModel):
    snapshot_id: str
    session_id: str
    request_id: str
    trace_id: str | None = None

    entry_ids: list[str] = Field(default_factory=list)
    context_items: list[dict[str, Any]] = Field(default_factory=list)

    token_budget: int
    token_estimate: int

    strategy: str = "recent_first"

    created_at: datetime = Field(default_factory=datetime.utcnow)

    metadata: dict[str, Any] = Field(default_factory=dict)
```

---

### 6.6 注入 AgentState 的上下文 DTO

`STMContextItem` 是写入 `AgentState.short_term_context` 的结构。
V0 阶段只要求以下 **5 个核心字段**，其余为后续扩展。

```python
# ── V0 必填（5 字段）──
{
    "role": "user",                    # str — user / assistant / system
    "content": "...",                  # str — 消息内容（截断到 500 字符）
    "entry_type": "user_message",      # str — user_message / assistant_message / system
    "created_at": 1718000000.0,        # float — Unix 时间戳
    "asset_refs": []                   # list[dict] — 当前消息关联的图片/文件引用
}

# ── 后续扩展（可选）──
# "entry_id": str | None
# "turn_id": str | None
# "request_id": str | None
# "structured_data": dict | None
# "source_module": str | None
# "node_name": str | None
# "importance": float | None
# "confidence": float | None
```

约束：

1. `STMContextItem` 是给 AgentState 使用的轻量 DTO；
2. `AgentState.short_term_context` 保持 `list[dict[str, Any]]` 泛型，不强约束内部结构；
3. 不包含 debug 信息、完整 prompt、完整 raw output、完整 Chain-of-Thought；
4. `asset_refs` 只包含必要引用字段（asset_type, image_id, path, mime_type）。

---

## 7. API 接口设计

### 7.1 创建或获取 Session

```python
def get_or_create_session(
    session_id: str,
    user_id: str | None = None,
    metadata: dict | None = None,
) -> STMSession:
    """
    获取或创建短期记忆 session。
    如果 session 不存在，则创建 active session。
    如果 session 已 archived / expired，不允许继续写入，应创建新 session。
    """
```

---

### 7.2 开始一轮对话

```python
def start_turn(
    session_id: str,
    request_id: str,
    trace_id: str | None = None,
    input_type: str = "text",
    user_input: str | None = None,
    asset_refs: list[dict] | None = None,
    metadata: dict | None = None,
) -> STMTurn:
    """
    创建一轮对话记录。
    自动生成 turn_id。
    自动递增 turn_index。
    自动写入 user_message 类型的 STMEntry。
    """
```

---

### 7.3 追加记忆条目

```python
def append_entry(
    session_id: str,
    turn_id: str,
    request_id: str,
    role: STMEntryRole,
    entry_type: STMEntryType,
    content: str,
    trace_id: str | None = None,
    source_module: STMSourceModule | None = None,
    node_name: str | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    structured_data: dict | None = None,
    asset_refs: list[dict] | None = None,
    importance: float | None = None,
    confidence: float | None = None,
    visible_to_llm: bool = True,
    visible_to_user: bool = False,
    metadata: dict | None = None,
) -> STMEntry:
    """
    向当前 session / turn 追加一条短期记忆。
    自动递增 entry_index。
    content 必须是用户可见内容或可审计摘要，不允许保存完整 CoT。
    """
```

---

### 7.4 完成一轮对话

```python
def complete_turn(
    session_id: str,
    turn_id: str,
    request_id: str,
    final_answer: str | None = None,
    route_type: str | None = None,
    status: STMTurnStatus = STMTurnStatus.COMPLETED,
    metadata: dict | None = None,
) -> STMTurn:
    """
    标记一轮对话完成。
    自动写入 final_answer 摘要。
    自动更新 stm_sessions.turn_count、last_accessed_at、last_request_id。
    """
```

---

### 7.5 读取最近上下文

```python
def get_recent_context(
    session_id: str,
    limit_turns: int = 6,
    limit_entries: int = 30,
    token_budget: int = 3000,
    include_tools: bool = True,
    include_assets: bool = True,
    strategy: str = "recent_first",
) -> list[STMContextItem]:
    """
    获取最近上下文，用于构建 AgentState.short_term_context。
    只返回 visible_to_llm=True 的条目。
    根据 token_budget 自动裁剪。
    默认优先保留最近轮次和最近图片 / 文件引用。
    """
```

---

### 7.6 构建 AgentState Patch

```python
def short_term_context_patch(
    session_id: str,
    request_id: str,
    trace_id: str | None = None,
    limit_turns: int = 6,
    token_budget: int = 3000,
) -> dict:
    """
    返回可直接 merge 到 AgentState 的 patch。

    返回格式：
    {
        "short_term_context": [...]
    }
    """
```

---

### 7.7 从 AgentState 写入短期记忆

```python
def write_from_state(
    state: dict,
    trace_id: str | None = None,
) -> None:
    """
    从 AgentState 中提取可写入短期记忆的字段。
    只写入摘要化字段：
    - user_input
    - image_refs / file_refs
    - route_result 摘要
    - observations 摘要
    - tool_calls / tool_results 摘要
    - final_answer 摘要
    - errors 摘要

    不写入：
    - debug_info
    - 完整 prompt
    - 完整 raw output
    - 完整 Chain-of-Thought
    - 内部异常堆栈
    """
```

---

### 7.8 挂起 Session

```python
def suspend_session(
    session_id: str,
    reason: str | None = None,
) -> STMSession:
    """
    将 session 状态改为 suspended。
    不物理删除数据。
    一般由超时任务触发。
    """
```

---

### 7.9 归档 Session

```python
def archive_session(
    session_id: str,
    reason: str | None = None,
) -> STMSession:
    """
    将 session 状态改为 archived。
    archived 后不允许继续写入。
    实际清理由定时任务或 TTL 完成。
    """
```

---

### 7.10 清理过期 Session

```python
def cleanup_expired_sessions(
    before_ts: datetime | None = None,
    hard_delete: bool = False,
) -> int:
    """
    清理过期短期记忆。
    默认只标记 expired，不做物理删除。
    hard_delete=True 时才物理删除，且只允许清理 archived / expired session。
    返回处理的 session 数量。
    """
```

---

## 8. 与 LangGraph 节点的集成约定

### 8.1 节点位置（已实现）

`load_short_term_context` 已作为独立节点加入主图，位于 `normalize_input` 之后、`route_task` 之前：

```text
START
  ↓
normalize_input
  ↓
load_short_term_context   ← 已实现: app/agent/nodes/load_context.py
  ↓
route_task
  ↓
conditional edge
  ↓
vision_direct / vision_schema / retrieve / react_subgraph / fallback
  ↓
respond
  ↓
update_memory
  ↓
END
```

如果暂不新增节点，也可以在 `normalize_input` 内调用 `short_term_context_patch()`。

但推荐拆成独立节点，原因是：

1. 便于 Trace 记录 `memory_read_started / memory_read_completed`；
2. 便于前端展示“读取上下文”；
3. 便于后续单独调试记忆窗口裁剪。

---

### 8.2 `load_short_term_context` 节点契约

```python
def load_short_term_context(state: AgentState) -> dict:
    """
    读取当前 session 的短期记忆，并返回 AgentState patch。
    节点只返回 partial update，不直接修改 state。
    """
```

返回示例：

```python
{
    "short_term_context": [
        {
            "entry_id": "...",
            "turn_id": "...",
            "request_id": "...",
            "role": "user",
            "entry_type": "user_message",
            "content": "用户上一轮上传了一张发票图片，并询问金额。",
            "asset_refs": [
                {
                    "asset_type": "image",
                    "image_id": "img_xxx",
                    "path": "/uploads/img_xxx.png",
                    "mime_type": "image/png"
                }
            ],
            "created_at": "..."
        }
    ]
}
```

---

### 8.3 `update_memory` 节点契约

```python
def update_memory(state: AgentState) -> dict:
    """
    从 AgentState 中提取可写入短期记忆的内容。
    短期记忆写入成功或跳过后，只返回 action_trace / errors 等轻量 patch。
    不把完整 memory store 塞回 AgentState。
    """
```

约束：

1. 写入成功可追加 `ActionTraceItem`；
2. 写入失败不应阻断主流程；
3. 写入失败应追加 `errors`；
4. Trace 层应 emit `memory_write_failed`；
5. 节点不返回下一个节点名。

---

## 9. 与 AgentTrace 的集成约定

> **V0 限制**：Trace 事件在 `graph.invoke()` 完成后统一批量发射，非节点执行期间实时推送。
> SSE 订阅者在 invoke 完成前无法收到事件。实时流式 Trace 将后续通过 `graph.astream_events()` 实现。

### 9.1 读取短期记忆时的 Trace 事件

读取短期记忆的 Trace 事件由 `load_short_term_context` 节点发射（`retrieve` 节点负责长期记忆检索，不再发射 memory_read 事件）。

读取前：

```text
memory_read_started
```

读取后：

```text
memory_read_completed
```

payload 建议：

```json
{
  "source_type": "short_term_memory",
  "source_name": "stm_entries",
  "result_count": 8,
  "used_short_term_memory": true,
  "used_long_term_memory": false,
  "used_document_context": false
}
```

---

### 9.2 写入短期记忆时的 Trace 事件

写入操作由 `update_memory` 节点完成。写入成功 emit `memory_write_completed`，门控跳过 emit `memory_write_skipped`，失败 emit `memory_write_failed`（写入失败不阻断主流程）。

写入前：

```text
memory_write_started
```

写入成功：

```text
memory_write_completed
```

跳过写入：

```text
memory_write_skipped
```

写入失败：

```text
memory_write_failed
```

payload 建议：

```json
{
  "need_memory_write": true,
  "target": "short_term_memory",
  "written": true,
  "skipped_reason": null,
  "memory_item_count": 4
}
```

---

### 9.3 禁止事项

1. 不要把 `STMEntry` 转换成 `AgentTraceEvent` 存储；
2. 不要从 `agent_trace_events` 反推短期记忆；
3. 不要让前端 Timeline 直接读取 `stm_entries`；
4. 不要在短期记忆中保存 Trace payload 全量内容；
5. `trace_id` 只是关联 ID，不是短期记忆主键。

---

## 10. 上下文裁剪策略

### 10.1 默认策略：recent_first

优先保留：

1. 当前轮用户输入；
2. 最近一轮完整 User → Assistant；
3. 最近涉及的图片 / 文件引用；
4. 最近工具观察结果；
5. 最近澄清问题和用户补充；
6. 最近错误摘要。

---

### 10.2 可选策略：importance_first

用于复杂 ReAct 或多轮任务。

优先保留：

1. `importance` 高的条目；
2. 与当前输入存在同一 asset_ref 的条目；
3. 包含 tool_result / observation 的条目；
4. 最近的 user_message；
5. 最近的 final_answer。

---

### 10.3 token budget 约束

默认建议：

```text
token_budget = 3000
limit_turns = 6
limit_entries = 30
single_entry_max_chars = 2000
single_tool_result_max_chars = 4000
total_structured_data_max_bytes = 10KB
```

超出限制时（已实现 Turn 级别裁剪）：

1. 按 Turn 分组，**整轮丢弃旧 Turn**（保证 QA 对完整）；
2. **当前轮永不丢弃**；
3. Turn 内部条目过多时，优先保留 user_message > final_answer，其余截断；
4. 保留 asset_refs；
5. 保留必要 tool_call_id / source_module / confidence；
6. 不删除当前轮输入。

---

## 11. 边界与约束

| 边界情况                           | 处理方式                                      |
| ------------------------------ | ----------------------------------------- |
| `session_id` 不存在               | `get_or_create_session()` 自动创建            |
| session 已 `archived / expired` | 不允许继续写入，创建新 session 或返回错误                 |
| 同一 session 并发写入                | `turn_index` 和 `entry_index` 必须使用乐观锁或原子自增 |
| 上下文超过 token budget             | `get_recent_context()` 按策略裁剪              |
| 工具结果过大                         | 只保存摘要，结构化数据超过 10KB 必须截断                   |
| 图片 / 文件多轮复用                    | 只保存 `asset_refs`，不保存二进制                   |
| VLM 输出过长                     | 保存 observation summary，不保存完整 raw output   |
| 模型输出完整 CoT                     | 禁止写入                                      |
| prompt 或 raw output 被传入        | 拒绝写入或强制摘要化                                |
| 短期记忆写入失败                       | 不阻断主流程，写入 errors 并 emit Trace 失败事件        |
| Trace 写入失败                     | 不影响短期记忆读写                                 |
| SSE 推送失败                       | 不影响短期记忆读写                                 |
| 用户清空会话                         | `archive_session()`，不直接物理删除               |
| 超时未交互                          | 定时任务将 session 标记为 `suspended`             |
| 长期记忆写入判断                       | 不由 Short-Term Memory 决定，由反思层 / 长期记忆层决定    |

---

## 12. 安全与隐私约束

短期记忆禁止保存：

```text
完整 Chain-of-Thought
完整隐藏推理草稿
完整 prompt
完整 raw model output
内部异常堆栈
工具密钥
数据库连接信息
未脱敏 token
用户敏感凭证
图片 / 文件二进制本体
```

短期记忆允许保存：

```text
用户原始可见输入
用户上传图片 / 文件引用
助手最终回答摘要
工具调用摘要
工具结果摘要
VLM 观察摘要
路由摘要
决策摘要
错误摘要
人工确认结果
```

---

## 13. V0 最小实现范围

V0 必须实现：

```text
STMSession
STMTurn
STMEntry
STMContextItem

get_or_create_session()
start_turn()
append_entry()
complete_turn()
get_recent_context()
short_term_context_patch()
write_from_state()
suspend_session()
archive_session()
cleanup_expired_sessions()
```

V0 可暂不实现：

```text
stm_context_snapshots
importance_first 策略
复杂 token 精确计算
长期记忆晋升
跨 session 检索
语义压缩
embedding 检索
```

---

## 14. 推荐文件位置

```text
app/
  memory/
    short_term.py              # 短期记忆：内存 LRU 实现

  agent/
    nodes/
      load_context.py          # 加载短期记忆上下文到 AgentState
      memory.py                # update_memory：持久化记忆（含异常保护）
```

文件职责：

| 文件                                     | 职责                                     |
| -------------------------------------- | -------------------------------------- |
| `memory/short_term.py`                 | 短期记忆：会话管理、消息存取、票据上下文、中间结果        |
| `agent/nodes/load_context.py`          | LangGraph node：读取短期记忆 → AgentState.short_term_context |
| `agent/nodes/memory.py`                | LangGraph node：门控写入短期 + 长期记忆（失败不阻断主流程） |
| `trace/service.py`                     | 记录 memory_read / memory_write Trace 事件 |

---

## 15. 验收标准

1. 同一 session 可以稳定写入多轮对话；
2. `turn_index` 在同一 session 内单调递增；
3. `entry_index` 在同一 session 内单调递增；
4. 多轮图片引用可以被下一轮读取；
5. `get_recent_context()` 只返回 `visible_to_llm=True` 的条目；
6. `short_term_context_patch()` 返回的数据可直接写入 `AgentState.short_term_context`；
7. 不保存完整 Chain-of-Thought；
8. 不保存完整 prompt；
9. 不保存完整 raw model output；
10. 不复用 `agent_trace_runs / agent_trace_events`；
11. memory read / write 可 emit AgentTrace 事件；
12. 短期记忆写入失败不阻断主流程；
13. session 超时后可被标记为 suspended；
14. archived session 不允许继续写入；
15. 上下文超长时可按 token budget 裁剪。

---

## 16. Vibe Coding 注意事项

```text
⚠️ 特别注意：

1. 不要新增 conversation_turns / session_meta 表，统一使用 stm_sessions / stm_turns / stm_entries，避免和旧模板及 Trace 表混淆。
2. 不要在 STMEntry 中添加 thought 字段；如需记录 ReAct 信息，只能使用 decision_summary / action_summary / observation_summary。
3. 不要把 AgentTraceEvent 列表塞进短期记忆，也不要让短期记忆替代 Trace Store。
4. 不要把短期记忆 Store 整体写入 AgentState，只允许写入裁剪后的 short_term_context。
5. 不要在短期记忆中保存完整 prompt、完整 raw output、完整 Chain-of-Thought。
6. 图片和文件只能保存引用，不保存二进制。
7. 所有写入必须带 session_id；能带 request_id 时必须带 request_id。
8. turn_index 和 entry_index 必须在同一个 session 内单调递增，不能只依赖 created_at 排序。
9. update_memory 节点失败不能阻断主链路，应写入 errors 并 emit memory_write_failed。
10. 后续如果新增字段，必须同步更新本 Schema，不允许在代码中临时乱加字段。
```

---

## 17. 最终原则

```text
Short-Term Memory 负责会话上下文缓存
AgentState 负责单次请求状态传递
AgentTrace 负责执行事件流和前端 Timeline
Long-Term Memory 负责跨会话沉淀
Reflection 负责语义压缩和记忆晋升判断
```

`Short-Term Memory` 不是新的状态机，不是 Trace 系统，也不是长期记忆。

它只是当前 session 内可控、可裁剪、可复用的上下文缓存层。
