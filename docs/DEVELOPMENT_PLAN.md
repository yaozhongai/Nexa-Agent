# Nexa Agent 开发规划

> 版本：V1.1 | 日期：2026-06-09

---

## 一、V0 — 已完成

### 架构

```
LangGraph 原生 StateGraph + AgentState TypedDict + Reducer
  normalize_input → route_task (L1规则 + L2 DeepSeek V4 Flash)
    ├── VISION_DIRECT: VLM 直答 → 校验 → 返回 (0 LLM)
    ├── VISION_SCHEMA: VLM 提取 → 规则校验 → 返回 (0 LLM)
    ├── RAG_QA: 检索 → LLM → (按需 Verifier)
    └── TOOL_ACT: 占位 (V1)

Direct First, Agent When Needed
```

### 已完成

| 模块 | 状态 |
|------|------|
| LangGraph 原生状态机 (StateGraph + Reducer) | ✅ |
| AgentState TypedDict (对齐 AgentState_SchemaV2.md) | ✅ |
| 两层路由 (L1 规则 0ms + L2 DeepSeek V4 Flash) | ✅ |
| 4 条执行路径 (VISION_DIRECT / SCHEMA / RAG_QA / TOOL_ACT) | ✅ |
| VLM (llama.cpp + MiniCPM-V, OpenAI SDK) | ✅ |
| LLM (DeepSeek V4 / Kimi K2.6 / GLM-5.1) | ✅ |
| 校验器 (L1 规则 + L2 LLM Verifier, 仅复杂推理触发) | ✅ |
| 短期记忆 (内存 LRU) + 长期记忆 (SQLite + agent_runs/traces) | ✅ |
| 记忆门控写入 (VISION_DIRECT 不写, VISION_SCHEMA 仅写票据数据) | ✅ |
| FastAPI (:8000) + Streamlit (:8501) + CLI | ✅ |
| .env 配置 + Makefile | ✅ |
| 旧架构清理 (StateContext / Handler / AgentStateMachine 已删除) | ✅ |

### Verifier 触发条件

| 路径 | 触发条件 | LLM | Verify |
|------|----------|-----|--------|
| VISION_DIRECT | 有图片, 默认 | 0 | ❌ |
| VISION_SCHEMA | 有图片 + 提取/结构化/json/字段 | 0 | ❌ |
| RAG_QA (纯文本) | 无图片 | 1 | ❌ |
| **RAG_QA (复杂推理)** | **有图片 + 是否可以/原因/风险/建议/判断** | **1-2** | **✅** |
| TOOL_ACT | V1 预留 | — | — |

### V0 剩余

| 项目 | 优先级 |
|------|--------|
| 单元测试 | P2 |

---

## 二、V1 — 规划中

从"VLM 直答 + 文本问答"扩展到文档/截图多模态 + 模型路由 + 语义检索。

| 功能 | 说明 |
|------|------|
| 文档解析 | PDF / Word / Excel / Markdown / TXT |
| 截图理解 | VLM |
| 模型路由 | 按任务复杂度自动选模型 |
| 语义检索 | Milvus |
| Redis 短期记忆 | 替代内存 LRU |
| TOOL_ACT 实现 | react_subgraph |
| ReAct 子图 | Thought → Action → Observation 循环 |
| HITL 人工确认 | `interrupt()` + human_confirm |

## 三、V2 — 远期

端侧部署 (RDK X5 / 小米) + 摄像头 + 多 Agent 协同。
