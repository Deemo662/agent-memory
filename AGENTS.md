# AGENTS.md — 跨 Agent 统一记忆系统协作约定

本文件记录各 agent 在使用 agent-memory 时的行为约定，确保协作一致。所有 agent 在接入系统时应遵守。

---

## 通用约定

### 元规则：公告描述目的，不约束实现

各 agent 的技术架构不同——Codex 读 AGENTS.md、Hanako 用 pin_memory、WorkBuddy 用 skill 文件、Hermes 有自己的配置层。跨 agent 公告和协作要求应描述**要达到什么目的**，而非**用什么方式实现**。

- ❌ "将约定写入 AGENTS.md"
- ✅ "确保后续会话能自动遵守以下协作约定"

目的统一，实现方式由各 agent 自主选择。

### 会话启动
- 每次会话开始先执行 `poll_events --agent_id {self} --timeout 30`，拉取未读事件
- 发现 task_reopened 事件时，检查对应任务上下文判断是否需要介入

### 任务创建
- 开始任何需要跨 session 或跨 agent 的任务时，调用 `create_task`
- `tags` 至少包含一个分类标签（coding/research/writing/messaging/ops）
- `description` 写清楚目标和验收标准，不要只写标题

### 进度更新
- 任务完成时调用 `update_progress --action completed`
- 中途有重要发现或阶段性产出时调用 `update_progress --action updated`
- 仅做注释/讨论时调用 `add_comment --comment_type discussion`，不污染进度历史

### 任务交接
- 遇到自身能力不匹配的任务，先 `suggest_agent` 再 `handoff_task`
- handoff 时 `--note` 写清当前进度和接手者需要知道的关键上下文

### 群聊协作
- 审查他人产出用 `review_artifact`（独立 tool + verdict），不要用普通 comment
- review_artifact 自动创建关联 comment 并推送 review_verdict 事件，无需额外 add_comment
- 推翻重做用 `reopen_task --reason`（≥10字符 + 上限3次），不要直接 create_task 新任务
- 提交产物用 `add_artifact`，更新用 `update_artifact --expected_version`（乐观锁）

### 事件消费
- poll_events 拿到事件后，处理完必须 `ack_event` 确认消费
- 不 ack 的事件会在下次 poll 时重复推送

---

## Hanako 专项约定

- **接入方式**：CLI 直连 storage 层，不走 MCP transport
- **CLI 路径**：`/Users/mumu/Library/CloudStorage/OneDrive-个人/02-领域/02-Research/agent-memory/src/agent_memory/cli.py`
- **Python**：`/Users/mumu/.workbuddy/binaries/python/envs/default/bin/python`
- **19 个子命令全部可用**，包括群聊协作层 11 个
- **持久化记忆**：CLI 调用规范已写入 Hanako 自身记忆系统，后续自动调用
- **建议分配**：suggest_agent 时 Hanako 优先承担 research/查找/诊断 类任务

---

## WorkBuddy 专项约定

- **接入方式**：MCP 直连 + agent-memory-recorder skill
- 对话开始时通过 hook 自动检查相关任务
- 任务完成时自动调用 update_progress
- 擅长：综合调研、文字产物、设计审查

## Codex 专项约定

- **接入方式**：MCP 直连（~/.codex/config.toml）
- 编码任务完成后自动提交 artifact 并标记 completed
- 擅长：编码实现、调试

## Hermes 专项约定

- **接入方式**：MCP 直连（同 Hanako 生态）
- 消息通知类任务优先路由
- 擅长：消息平台集成、通知推送

## ZCode 专项约定

- **接入方式**：MCP 直连（~/.zcode/cli/config.json）
- 编码任务与 Codex 协同，suggest_agent 按任务负载分配
- 擅长：编码实现（智谱 GLM）

---

## suggest_agent 路由参考

| 任务类型 | 建议 agent | 备选 |
|---------|-----------|------|
| 编码/调试/实现 | codex / zcode | 按活跃任务数少的分配 |
| 调研/搜索/诊断 | hanako | workbuddy |
| 文档/报告/写作 | workbuddy | — |
| 消息/通知/集成 | hermes | — |
| 协调/仲裁/公告 | workbuddy | — |

---

_最后更新：2026-07-07 by Hanako_
