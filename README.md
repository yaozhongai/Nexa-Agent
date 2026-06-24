# Nexa Agent

> ReAct + Reflexion 自进化智能体系统 — Agent Harness Engineering 实践

---

## 简介

Nexa Agent 是一个 **ReAct + Reflexion 架构的智能体系统**：

- **`app/`** — LangGraph + FastAPI 生产服务，多模态识别与问答（主系统）
- **`react_exp/`** — ReAct + Reflexion 实验环境，验证通过后整合到 `app/`

```
react_exp/ 核心循环：
  ReflexionReActAgent.execute()
    ├─ Trial 1~3 (Reflexion 外循环)
    │   ├─ Scratchpad 事实注入 + 教训注入
    │   ├─ react_loop() — 原生 tool calling (DeepSeek V4)
    │   │   ├─ 10 个工具: web_search / read_pdf / calculator / ...
    │   │   ├─ 中途纠偏: URL 去重 + loop 检测
    │   │   └─ 分档 Observation 截断 (≤15K 零截断)
    │   ├─ Evaluator: 结果优先两阶段评估
    │   ├─ Verifier: 事实核查网关
    │   └─ 失败 → 反思 + 教训提取 + Scratchpad 事实提取
    └─ 返回最佳答案
```

### 核心能力

**Agent 引擎 (`react_exp/`)**
- ReAct + Reflexion 双循环：局内 tool calling + 局外自我反思
- 原生 Function Calling：DeepSeek V4 tool calling API，消灭正则解析失败
- 10 个工具：web_search / wikipedia / web_fetch / tavily_extract / read_pdf / calculator / analyze_image / analyze_image_cloud / save_content / get_current_time
- 模型分层路由：strong (Pro) 首步规划 + fast (Flash) 后续执行，节省 ~60% token
- 中途纠偏：URL 级跨工具去重 + loop 早期检测 + 策略切换
- Scratchpad 跨 Trial 事实传递：已确认数据点不丢失
- Evaluator 结果优先：过程有问题不否决正确答案
- Eval Harness：回归评测流水线 + failure mode 归因 + 运行对比
- GAIA Benchmark Level 1：64.2% 基线

**生产服务 (`app/`)**
- LangGraph 原生 ReAct Agent + FastAPI
- 多模态：文本 + 图片（JPG / PNG / PDF）
- STM 会话上下文 + LTM 长期记忆 + KB 分层检索
- Trace 可视化：Events / Timeline / SSE
- Streamlit Chat UI

---

## 快速开始

要求：Python `3.9+`

```bash
git clone <repo-url> && cd Nexa_Agent
cp .env.example .env   # 编辑填入 DEEPSEEK_API_KEY, TAVILY_API_KEY
pip install -r requirements.txt
```

### ReAct + Reflexion Agent (`react_exp/`)

```bash
# 直接提问
python -m react_exp.reflexion_agent "北京到上海的直线距离是多少？"

# 从文件读取问题
python -m react_exp.reflexion_agent --file react_exp_jd/prompts/question_tizin.txt

# 运行 Eval Harness
python -m react_exp.eval_harness run --suite gaia_l1 --limit 5

# 分析评测结果
python -m react_exp.eval_harness analyze --input react_exp/results/eval_xxx.jsonl

# 对比两次运行
python -m react_exp.eval_harness compare --baseline run_A.jsonl --current run_B.jsonl
```

### 生产服务 (`app/`)

```bash
make                   # 一键启动前后端
# 后端 → http://localhost:8000/docs
# 前端 → http://localhost:8501

python -m app.cli -m "你好"
python -m app.cli -i invoice.jpg -m "金额多少"
```

---

## 架构

```
react_exp/                     实验环境 (验证后整合到 app/)
├── react_agent.py             ReAct 主循环 (原生 tool calling)
├── reflexion_agent.py         Reflexion 外循环 (Trial → Evaluate → Reflect)
├── evaluator.py               结果优先混合评估器 (启发式 + LLM Judge)
├── verifier.py                事实核查网关 (Verifier Agent)
├── tools.py                   10 个工具 (web_search / read_pdf / calculator / ...)
├── memory.py                  Reflexion 情景记忆 (教训提取 + Jaccard 去重)
├── eval_harness.py            系统化评测流水线 (多维评分 + 回归对比)
├── config.py                  模型分层路由 + 超参数管理
├── logger_config.py           per-run 独立日志
├── prompts/                   System Prompt + Reflection Prompt
└── eval_suites/               评测套件 (回归子集 ID)

app/                           LangGraph + FastAPI 生产服务
├── agent/                     LangGraph ReAct Agent
├── tools/                     工具集
├── trace/                     Trace 事件系统
├── storage/                   持久化层 (SQLAlchemy)
├── llm/                       DeepSeek V4 / Kimi K2.6 / GLM-5.1
├── pipeline/                  llama.cpp VLM (MiniCPM-V)
├── api/                       FastAPI 路由
└── memory/                    STM + LTM
```

### 执行路径

| 路径 | 场景 | LLM | VLM | 工具 |
|------|------|-----|-----|------|
| TOOL_ACT | 全部请求 (ReAct Agent) | 1-6 | 0-1 | 0-5 |
| FALLBACK | 异常兜底 | 0 | 0 | 0 |
> ReAct 循环最多 6 步，LLM 自行判断是否需要调工具

### API

| 路由 | 说明 |
|------|------|
| `POST /api/v0/chat` | 多轮对话，创建 AgentState 并执行 LangGraph |
| `POST /api/v0/upload` | 上传图片/PDF，返回 `file_id`、`file_sha256`、服务端路径 |
| `POST /api/v0/files/analyze` | 上传后图片预识别，写入/命中 `image_analysis_cache` |
| `GET /api/v0/trace/{id}/events` | Trace 事件明细 |
| `GET /api/v0/trace/{id}/timeline` | 前端时间线 |
| `GET /api/v0/trace/{id}/stream` | Trace SSE |
| `GET/DELETE/PATCH /api/v0/memory/ltm` | LTM 记忆管理（查看/遗忘/修改） |
| `GET /api/v0/health` | 后端、LLM、VLM 健康状态 |

### LLM / VLM 支持

| Provider | 模型 |
|----------|------|
| DeepSeek V4 | deepseek-v4-flash / deepseek-v4-pro |
| Kimi K2.6 | kimi-k2.6 |
| GLM-5.1 | glm-5.1 |
| VLM | llama.cpp / MiniCPM-V（OpenAI 兼容 API） |

### Trace

每请求自动记录 `agent_trace_runs` / `agent_trace_events`，CLI / Streamlit 展示节点路径、状态、耗时和模型调用摘要。

图片预识别与缓存复用不新增协议外 TraceEventType：

- 上传后预识别：`model_call_completed`，`payload.purpose="image_analysis_precompute"`
- Agent 节点复用缓存：`ActionTraceItem.action="use_cached_image_analysis"`，由 `chat.py` 派生为 `node_completed`

### Streamlit UI

- 主 Chat Panel 支持真实点击上传和拖拽上传
- 上传成功后自动触发图片预识别
- active file 在当前会话内持续作为图片上下文
- 用户消息中的图片缩略图会保留在历史消息里
- 助手回答正文使用 Streamlit 原生 `st.markdown()` 渲染，支持加粗、列表、代码和段落

---

## 文档

| 文档 | 说明 |
|------|------|
| [DEVELOPMENT_PLAN.md](docs/DEVELOPMENT_PLAN.md) | 三阶段开发规划 |
| [TECHNICAL_ARCHITECTURE.md](docs/TECHNICAL_ARCHITECTURE.md) | 技术架构 |
| [AgentState_SchemaV2.md](docs/AgentState_SchemaV2.md) | 状态协议 |
| [AgentTrace_Schema.md](docs/AgentTrace_Schema.md) | Trace 协议 |
| [Short-Term_Memory_Schema.md](docs/Short-Term_Memory_Schema.md) | 短期记忆协议 |
| [Long-Term_Memory_Schema.md](docs/Long-Term_Memory_Schema.md) | 长期记忆协议 |
| [SPEC.md](SPEC.md) | 项目规范与当前实现约束 |
