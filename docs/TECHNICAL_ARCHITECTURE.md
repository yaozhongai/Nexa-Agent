# Nexa Agent V0 — 技术架构文档

> 版本：V3.3 | 日期：2026-06-09 | 架构：LangGraph 原生 + 两层路由 + Trace

---

## 1. 项目概览

Nexa Agent V0 是一个 **LangGraph 原生、两层路由驱动、带完整 Trace 的多路径 Agent 系统**。

**Direct First, Agent When Needed。** VLM 直答不走 LLM，简单问答不反思，临时图片不写记忆。

---

## 2. 目录结构

```
app/
├── agent/                      # LangGraph 原生架构
│   ├── state.py                # AgentState TypedDict + Reducer + Sub-Schema
│   ├── graph.py                # build_agent_graph() → compiled StateGraph
│   ├── routers.py              # conditional edge
│   └── nodes/
│       ├── normalize.py        # 归一化 (Observation + 状态推进)
│       ├── route.py            # L1 规则 + L2 DeepSeek V4 Flash
│       ├── vision.py           # VLM 直答 / 结构化 / 感知
│       ├── retrieve.py         # 记忆检索
│       ├── reason.py           # LLM 推理
│       ├── verify.py           # L1 规则校验 + L2 LLM Verifier
│       ├── respond.py          # 最终响应
│       ├── memory.py           # 记忆持久化 (门控)
│       └── fallback.py         # 兜底
├── trace/                      # Trace 事件系统
│   ├── schema.py               # Trace 枚举 + 模型 + Payload
│   ├── store.py                # SQLAlchemy 存储 (agent_trace_runs / agent_trace_events)
│   ├── service.py              # create / emit / complete / fail / get / timeline
│   └── sse.py                  # SSE 流式推送 + after_seq 重连
├── storage/                    # 持久化层 (SQLAlchemy)
│   ├── database.py             # Engine + Session
│   └── models.py               # ORM 模型 (7表)
├── llm/                        # LLM 客户端
│   └── client.py               # DeepSeek / Kimi / GLM
├── api/
│   ├── schemas.py              # Pydantic API 契约
│   ├── deps.py                 # 依赖注入
│   └── routes/
│       ├── chat.py             # POST /api/v0/chat (Trace 集成)
│       ├── upload.py           # POST /api/v0/upload
│       ├── memory.py           # GET /api/v0/memory/*
│       └── trace.py            # GET /api/v0/trace/* (SSE + Timeline)
├── memory/                     # 短期 (LRU) + 长期 (SQLAlchemy)
├── pipeline/                   # VLM 引擎 + 提取管线
├── utils/                      # 日志 + 路由规则 + 校验
├── main.py / cli.py / streamlit_app.py
└── .env / Makefile / .env.example
```

---

## 3. 两层路由 + 5 条路径

```
normalize_input → route_task (L1规则 + L2 DeepSeek V4 Flash)
                      │
        ┌─────────────┼─────────────┬──────────────┐
        ▼             ▼             ▼              ▼
  VISION_DIRECT  VISION_SCHEMA    RAG_QA       TOOL_ACT
        │             │             │              │
   vlm_direct    vlm_schema    vision_perceive   占位
        │             │        (有图时)            │
   validate_dir  validate_sch     │               │
        │             │        retrieve            │
        └─────┬───────┘           │               │
              │                reason              │
              │               ┌──┴──┐              │
              ▼               │verify│(need_verify)│
           respond ←──────────┴─────┘              │
              │                                    │
         update_memory ←───────────────────────────┘
              │
            END
```

| 路径 | LLM | VLM | Verify | Memory |
|------|-----|-----|--------|--------|
| VISION_DIRECT | 0 | 1 | ❌ | ❌ |
| VISION_SCHEMA | 0 | 1 | ❌ | ✅ |
| RAG_QA (纯文本) | 1 | 0 | ❌ | ❌ |
| RAG_QA (有图+推理) | 1-2 | 1 | ✅ | ❌ |
| TOOL_ACT | — | — | — | V1 |

---

## 4. AgentState (对齐 Schema V2)

- **TypedDict** + Reducer (追加型字段: `action_trace` / `observations` / `errors` / `model_calls` / `validation_results`)
- 节点返回 `dict` partial update，不返回下一节点名
- 路由由 `routers.py` conditional edge 完成
- `ModelCallRecord` 含 `prompt_tokens` / `completion_tokens` / `total_tokens`

---

## 5. Trace 系统 (对齐 AgentTrace_Schema)

| 表 | 用途 |
|----|------|
| `agent_trace_runs` | 一次请求的 Trace 总览 (trace_id / status / 耗时 / 调用计数) |
| `agent_trace_events` | 事件明细 (node_started / model_call_completed / route_decided ...) |

| API | 说明 |
|-----|------|
| `GET /api/v0/trace/{id}/events?after_seq=` | 事件列表 (支持断线重连) |
| `GET /api/v0/trace/{id}/timeline` | 前端时间线 |
| `GET /api/v0/trace/{id}/stream` | SSE 实时推送 |

每请求自动 `create_trace_run` → `complete_trace_run`，CLI / Streamlit 同步展示。

---

## 6. LLM / VLM

| Provider | 模型 | 用途 |
|----------|------|------|
| DeepSeek V4 | v4-flash | L2 路由 + 推理 |
| DeepSeek V4 | v4-pro | 高精度推理 |
| Kimi K2.6 | kimi-k2.6 | 推理 (temp=0.6, thinking=disabled) |
| GLM-5.1 | glm-5.1 | 推理 |
| llama.cpp | MiniCPM-V | VLM 图像理解 (127.0.0.1:8080/v1, ctx=4096) |

---

## 7. API 总览

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/v0/chat` | 多轮对话 |
| `POST` | `/api/v0/upload` | 图片上传 |
| `GET/DELETE` | `/api/v0/memory/session/{id}` | 会话记忆 |
| `GET` | `/api/v0/memory/invoices` | 历史票据 |
| `GET/POST` | `/api/v0/memory/preferences` | 偏好 |
| `GET` | `/api/v0/health` | 健康检查 |
| `GET` | `/api/v0/trace/{id}/events` | Trace 事件 |
| `GET` | `/api/v0/trace/{id}/timeline` | Trace 时间线 |
| `GET` | `/api/v0/trace/{id}/stream` | Trace SSE |
| `POST` | `/api/v0/reset` | 重置 |

---

## 8. 启动

```bash
make          # 一键前后端
make backend  # :8000
make frontend # :8501
```
