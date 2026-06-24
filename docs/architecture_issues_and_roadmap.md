# ReAct + Reflexion Agent 系统：问题诊断与改进路线图

> 文档版本: v2.0 | 最后更新: 2026-06-16
> 基于 GAIA Benchmark Level 1 评测数据 (53题, 准确率 64.2%)
> v2.0 新增：产业级 Agentic Loop 对标分析 + Harness Agent 改进路线

---

## 一、当前系统面临的核心问题

### 1.1 上下文滚雪球 — Append-Only 消息累积

**现象**: ReAct 主循环 (`react_agent.py` L190/L249) 采用纯追加模式，每轮 Observation 直接拼入 messages 列表，无任何压缩或裁剪机制。

**实际影响**:
- 在长链路任务（如法规检索、多源信息融合）中，12-16 步后上下文可达 80K+ tokens
- 导致 LLM "Lost in the Middle"，早期关键信息被中间噪声淹没
- 评测数据：3-trial 全部失败的 6 个任务平均耗时 **483.7s**，平均步数触及上限 16 步

**日志证据**:
```
task_id: 72e110e7 (DDC 633 检索任务)
elapsed: 570.5s, trials_used: 3, correct: false
reflections[0]: "我在第 16 步继续用 web_search 搜索直接答案...陷入了无效搜索循环"
reflections[2]: "未识别出 base-search.net 才是关键信息源"
```

```
task_id: c365c1c7 (总统出生地经纬度比较)
elapsed: 381.1s, trials_used: 3, correct: false
reflections[2]: "我在第 16 步仍按总统顺序逐个解析出生地...陷入低效遍历循环导致步数耗尽"
```

### 1.2 网页抓取噪声污染 BM25 检索

**现象**: 原先 `web_fetch_focused` 优先使用 Jina Reader API，其返回内容常混入导航栏、页脚、广告等 HTML 模板文本。当文档进入 BM25 切片检索时，这些噪声稀释了关键词密度，导致真正相关的段落被排到低位。

**实际影响**:
- 对政府网站、学术数据库（如 BASE、Cornell LII）尤其严重
- BM25 返回的 top-8 chunks 中有大量导航文本，真正答案被排除

**日志证据**:
```
task_id: 7673d772 (Cornell Law 联邦规则修订)
elapsed: 450.3s, trials_used: 3, correct: false
reflections[1]: "我在第 16 步错误地使用 web_search...未直接访问康奈尔 LII 的具体规则页面查看 Amendments 注释"
```

### 1.3 模型配额冲突 — Qwen3.5 TPM 限流

**现象**: react_main、reflection、evaluator_llm、verifier 四个角色全部路由到同一模型 Qwen3.5-397B-A17B，多步骤密集调用时极易触发 TPM (Tokens Per Minute) 速率限制。

**实际影响**:
- 在 Test Set 全量评测中，12 分钟内 46 次 API 调用后触发 429 RateLimitError
- 进程直接崩溃，无重试机制兜底

### 1.4 工具能力缺口 — 本地文件处理

**现象**: 当前工具集不支持本地文件解析（.docx, .xlsx, .pptx, .mp3, .py），Agent 在遇到附件任务时直接放弃。

**实际影响**: 评测中 **6 个任务** (11.3%) 因工具缺口直接输出"无法处理"而失败。

**日志证据**:
```
task_id: cffe0e32 (Secret Santa .docx 逻辑推理)
prediction: "抱歉，我无法直接读取这个.docx文件..."
elapsed: 18.2s, trials_used: 1

task_id: 1f975693 (音频转录 .mp3)
prediction: "很抱歉，我无法帮助您提取音频文件中的页码信息..."
elapsed: 7.8s, trials_used: 1
```

### 1.5 Reflexion 内省幻觉

**现象**: 反思生成依赖 LLM 自我回顾失败原因（`reflexion_agent.py` L94-150），无外部验证。模型可能编造合理但不正确的失败原因，导致下一轮 Trial 重蹈覆辙。

**日志证据**:
```
task_id: d0633230 (Scikit-Learn changelog)
reflection[0]: "根因是我依赖搜索片段而非访问具体规则页面"
reflection[1]: "根因是我未直接访问...而是依赖通用搜索"  
reflection[2]: "根因是我忽略...而是猜测了错误的 URL 路径"
→ 三轮反思诊断了相似原因，但 Agent 仍然无法纠正行为，说明反思未产生有效行动指导
```

---

## 二、已实施的改进措施

### 2.1 模型路由重构 — DeepSeek-V4-Flash 替代 Qwen3.5

**改动文件**: `config.py`

**具体变更**:
- 新增 `flash` tier → DeepSeek-V4-Flash (284B/13B激活, 1M上下文, CSA+HCA混合注意力)
- 新增 `verify` tier → Qwen3.5-397B-A17B (保留给 Verifier，事实验证需低幻觉率)
- `react_main` / `reflection` / `evaluator_llm` 路由至 V4-Flash

**预期收益**:
- TPM 配额隔离：V4-Flash 与 V4-Pro 共享 DeepSeek 系配额池，与 Qwen 彻底解耦
- 1M 上下文窗口：根治长链路任务的 Lost-in-Middle 问题
- 同价格同生态：API 兼容，无额外工程成本

### 2.2 trafilatura 升为首选抓取引擎

**改动文件**: `tools.py`

**具体变更**:
- `web_fetch`: 抓取顺序从 Jina→trafilatura 改为 **trafilatura→Jina**
- `web_fetch_focused`: 同上

**预期收益**:
- trafilatura 本地解析，产出纯净正文（无导航栏/页脚/广告）
- BM25 检索的信噪比大幅提升
- Jina 保留为兜底（trafilatura 抓取失败时使用其代理能力）

### 2.3 免切片直投 — 提高 _FOCUSED_MAX_CHARS

**改动文件**: `tools.py`

**具体变更**:
- `_FOCUSED_MAX_CHARS` 从 8000 提升至 **16000**

**预期收益**:
- 16K 以内的中等文档直接返回全文，不经 BM25 切片（避免切片导致的上下文断裂）
- 配合 V4-Flash 的 1M 上下文，模型有能力消化完整文档并定位答案
- 仅超长文档（>16K）才走 BM25 检索路径

---

## 三、下一步可落地的改进方向（按投入产出比排序）

### 3.1 上下文压缩 — 首尾锚定 + 中间摘要

**启发来源**: Plan-and-Execute 范式的"上下文隔离"思想 (BabyAGI; HuggingGPT, 2023)

**方案**: 当 messages 总 token 数超过阈值时，对中间步骤的 Observation 进行压缩——保留首段（页面标题/摘要）和尾段（结论/数据表），中间替换为一句话概述。

**实施位置**: `react_agent.py` 主循环，在 `messages.append(observation)` 前增加压缩逻辑。

**预期收益**: 将 16 步任务的总上下文从 80K+ 压缩到 30K 以内，显著降低 Lost-in-Middle 风险。

### 3.2 外部验证增强反思 — CRITIC 模式

**启发来源**: *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing* (Gou et al., ICLR 2024)

**方案**: 在 Reflexion 的反思生成阶段，将 Verifier Agent 前置。当 evaluator 判定失败后：
1. 先让 Verifier 用工具（搜索/计算器）验证"失败的具体原因是什么"
2. 将验证结果作为硬约束注入反思 prompt
3. 生成的反思必须基于外部事实，而非模型内省

**实施位置**: `reflexion_agent.py` 反思生成流程 (L94-150)，在生成反思前插入 Verifier 验证步骤。

**预期收益**: 消灭"三轮反思诊断相似原因但无法纠正行为"的死循环。

### 3.3 步数效率惩罚 — 鼓励简洁解题

**启发来源**: RL for Agent 中的 Reward Shaping 思想；*Rejection Sampling Fine-Tuning* 中对 step count 的惩罚项 (Meta, 2024)

**方案**:
- 在 evaluator 的综合打分中加入 `step_penalty = -0.05 * steps_used`
- 当 Agent 在 5 步内给出正确答案时，evaluator 直接判定 High confidence 跳过 Reflexion
- 超过 12 步仍未给出答案时，触发 early-stop + 强制总结

**实施位置**: `evaluator.py` 评分逻辑 + `react_agent.py` 主循环退出条件。

**预期收益**: 平均耗时从 172.8s 降低 30%+；避免 Agent 在无效搜索循环中耗尽步数。

### 3.4 轻量路径回溯 — 受限 MCTS

**启发来源**: *LATS: Language Agent Tree Search Unifies Reasoning Acting and Planning* (Zhou et al., 2024)

**方案**: 在关键决策点（如选择搜索词、选择抓取目标 URL）fork 出 2-3 条候选路径，用规则化 Value 函数快速剪枝：
- Observation 以 "Error" 开头 → 路径价值归零，立即回溯
- Observation 字符数 < 50 → 可能是空页面，降权
- 最小实现：不需完整 MCTS，只在 `web_fetch` 失败时自动尝试备选 URL

**实施位置**: `react_agent.py` 工具执行后的分支逻辑。

**预期收益**: 减少因单点失败（403/反爬/空页面）导致的链路崩溃。

---

## 四、产业级 Agentic Loop 对标分析

### 4.1 当前系统 vs. 产业级 Loop 的本质差距

| 维度 | 当前 react_exp (传统 ReAct) | 产业级 (Codex/Claude Code/Hermes) |
|------|------|------|
| **推理承载** | 显式 Thought 文本输出，消耗生成 Token | 隐式扩展推理 (Extended Thinking)，不占输出带宽 |
| **工具调用** | 正则匹配 `Action: tool(args)` 字符串 | 原�� Function Calling API，强类型 JSON Schema |
| **上下文管理** | Append-Only，无压缩 | 动态截断/摘要 + Prompt Caching + 分页感知 |
| **失败处理** | 无 try-except，崩溃即终止 | 断路器 (Circuit Breaker) + Fallback 策略 + 最大轮数硬限 |
| **验证闭环** | 开环探索，生成即结束 | 闭环验证 (修改→执行测试→捕获报错→再修改) |
| **记忆系统** | 情景记忆注入 (被动) | 自主 Skill 创建 + FTS5 记忆固化 + 按需剪枝 (主动进化) |
| **项目知识** | 无冷启动机制 | AGENTS.md 规约文件 + 本地文件隔离 |

**启发来源**:
- OpenAI, *Unrolling the Codex agent loop*, 2026
- Anthropic, Claude Code Agentic Architecture, 2026
- Nous Research, *Hermes Agent: Closed Learning Loop*, 2025

### 4.2 三大产业级 Loop 的核心创新点

#### Codex Harness: 确定性工程控制流

1. **结构化 Prompt 树**: `system → developer → user → assistant` 严格分层，历史 Observation 动态摘要后再投喂
2. **项目知识固化**: 通过 `AGENTS.md` 消除冷启动失忆，Agent 运行前强制读取项目规约
3. **Git Worktrees 并行**: 多 Agent 在独立分支并发工作，消除代码冲突

#### Claude Code: 原生工具驱动的闭环

1. **原生 Tool Use**: 模型经 RL 微调，以接近 100% 准确率遵循工具 Schema，消灭格式重试
2. **智能环境感知**: 长输出自动截断/分页，提示模型使用更精确搜索词
3. **Test-Driven Loop**: 修改→执行测试→捕获终端报错→定位错误行→再次修改

#### Hermes Agent: 自进化闭环学习

1. **自主 Skill 创建**: 成功解决新问题后，自动编写可复用 Skill 文档 (agentskills.io 标准)
2. **FTS5 记忆固化**: Session 结束后 LLM 摘要 + 全文索引，剔除噪声只留纯金线索
3. **Honcho 用户建模**: 跨 Session 的对话上下文建模，越用越懂工作流

---

## 五、Harness Agent 改进路线（分阶段实施）

基于产业级 Agentic Loop 的启发，以下是将当前 react_exp 升级为 Harness Agent 的分阶段路线：

### Phase 1: 工程硬化（1-2天，不改架构）

**目标**: 消灭当前系统最致命的工程缺陷，不触及核心推理逻辑。

| 改动 | 对标 | 实施位置 |
|------|------|---------|
| **指数退避重试** | Codex断路器 | `react_agent.py` L175，wrap with tenacity |
| **Observation 动态截断** | Claude Code 智能环境感知 | `react_agent.py` L249，超阈值自动摘要 |
| **工具调用格式校验** | Claude Code 原生 Tool Use | `react_agent.py` 解析层，JSON Schema 预校验 |
| **最大轮数硬限 + early-stop** | Codex `--max-turns` | `react_agent.py` 主循环 + evaluator |

### Phase 2: 闭环验证（3-5天，局部重构）

**目标**: 从"开环探索"升级为"闭环验证"，核心思想来自 Claude Code 的 Test-Driven Loop。

| 改动 | 对标 | 实施细节 |
|------|------|---------|
| **执行反馈替代观察反馈** | Claude Code Test-Driven Loop | 对于计算/代码题，执行 Python 代码验证答案正确性 |
| **Verifier 前置到反思** | CRITIC + Claude Code 闭环 | evaluator 判定失败后，Verifier 用工具验证失败原因 |
| **Fallback 策略引擎** | Codex/Claude 断路器 | 同一工具连续失败 2 次→强制切换策略（换搜索词/换 URL） |
| **步数效率惩罚** | Codex Reward Shaping | evaluator 加入 step_penalty，5步内正确→跳过 Reflexion |

### Phase 3: 记忆进化（1周，架构升级）

**目标**: 从"被动记忆注入"升级为"主动 Skill 创建 + 记忆固化"，对标 Hermes Agent。

| 改动 | 对标 | 实施细节 |
|------|------|---------|
| **自主 Skill 提炼** | Hermes Skill Creation | 成功 trace → 自动提炼为结构化 Skill 文档（问题模式→解法模板） |
| **记忆合并与剪枝** | Hermes FTS5 + 摘要 | Session 结束后 LLM 摘要，剔除报错噪声，只留核心教训 |
| **项目规约文件** | Codex AGENTS.md | 创建 `react_exp/AGENT_RULES.md`，冷启动时强制加载 |
| **Skill 优先检索** | Hermes Closed Loop | 新任务到来→先检索 Skill 索引→有匹配则直接执行，跳过探索 |

### Phase 4: 原生工具升级（1-2周，工具链重构）

**目标**: 消灭工具能力缺口，实现本地文件沙盒执行能力。

| 改动 | 对标 | 实施细节 |
|------|------|---------|
| **本地文件解析工具** | Claude Code 文件系统访问 | 新增 docx/xlsx/pptx/pdf 解析工具 (python-docx, openpyxl) |
| **代码沙盒执行** | Codex 沙盒 | 新增 `code_execute` 工具，隔离执行 Python 代码 |
| **音频转文字** | 工具链完备性 | 新增 whisper/speech-to-text API 调用 |
| **强类型工具 Schema** | Claude Code Function Calling | 工具定义从字符串匹配升级为 JSON Schema + 参数校验 |

### 实施优先级总览

```
Phase 1 (工程硬化) ← 立即开始，ROI最高
    ↓
Phase 2 (闭环验证) ← 验证 Phase 1 效果后推进
    ↓
Phase 3 (记忆进化) ← 积累 50+ 成功 trace 后实施
    ↓
Phase 4 (工具链重构) ← 与 Phase 2 可并行
```

---

## 六、暂不建议实施的方向

| 方向 | 原因 |
|------|------|
| RL 后训练 (RSFT/DPO/PPO) | 成功轨迹不足（当前 34/53），需 100+ 高质量 trace 后再考虑 |
| 完整 Plan-and-Execute 重构 | GAIA 任务开放性强，纯计划易在第一步规划错误；增量补丁更务实 |
| 多 Agent SOP (MetaGPT 风格) | 当前单 Agent + Reflexion 尚未充分挖掘，过早引入多角色增加调试复杂度 |
| Self-RAG 微调 | 需要对基座模型进行训练，超出当前应用层优化的范畴 |

---

## 七、评测数据快照

| 指标 | 数值 |
|------|------|
| 数据集 | GAIA Validation Level 1 |
| 总题数 | 53 |
| 正确数 | 34 |
| 准确率 | 64.2% |
| 平均耗时 | 172.8s |
| 3-trial 耗尽仍失败 | 6 题 |
| 工具缺口导致失败 | 6 题 (11.3%) |
| 模型 | DeepSeek-V4-Pro (首步) + Qwen3.5 (后续步骤) |
| 评测日期 | 2026-06-15 |

---

## 八、参考文献

1. Yao et al. *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023.
2. Shinn et al. *Reflexion: Language Agents with Verbal Reinforcement Learning.* NeurIPS 2023.
3. Gou et al. *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing.* ICLR 2024.
4. Zhou et al. *Language Agent Tree Search Unifies Reasoning Acting and Planning in Language Models.* ICML 2024.
5. Asai et al. *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection.* ICLR 2024.
6. Hong et al. *MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework.* ICLR 2024.
7. Zelikman et al. *Quiet-STaR: Language Models Can Teach Themselves to Think Before Speaking.* 2024.
8. Yuan et al. *Self-Rewarding Language Models.* ICML 2024.
9. Lightman et al. *Let's Verify Step by Step.* ICLR 2024.
10. OpenAI. *Unrolling the Codex agent loop.* 2026.
11. Anthropic. *Claude Code: Agentic Architecture with Native Tool Use.* 2026.
12. Nous Research. *Hermes Agent: Closed Learning Loop with Autonomous Skill Creation.* 2025.