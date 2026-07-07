---
name: agent-memory-recorder
description: 跨 Agent 任务记忆记录器。当用户开始一个新任务、完成任务、或需要在另一个 agent 上继续任务时，自动调用 memory tools 记录和查询任务进度。触发词：记录任务、任务进度、之前哪个agent做过、交接任务、任务历史、跨agent、agent记忆、task context。
version: 0.1.0
---

# Agent Memory Recorder

跨 Agent 统一记忆系统的 WorkBuddy 接入 Skill。

## 核心能力

通过 MCP 连接 `agent-memory` Server，提供6个核心工具：

1. **create_task** — 创建新任务
2. **update_progress** — 更新任务进度
3. **search_tasks** — 搜索任务历史
4. **get_task_context** — 获取任务完整上下文
5. **handoff_task** — 交接任务给另一个 agent
6. **list_active_tasks** — 列出活跃任务

## 使用场景

### 场景1：开始新任务

当用户开始一个新任务时，调用 `create_task` 记录：

```
create_task(
    title="重构用户认证模块",
    created_by="workbuddy",
    description="将 session 认证迁移到 JWT",
    tags="coding,refactor"
)
```

### 场景2：完成任务

任务完成后，调用 `update_progress`：

```
update_progress(
    task_id="<之前创建的task_id>",
    agent_id="workbuddy",
    action="completed",
    summary="完成了 JWT 迁移，所有测试通过"
)
```

### 场景3：查询之前哪个 agent 做过

用户问"这个任务之前谁做过"时，调用 `search_tasks`：

```
search_tasks(query="用户认证", limit=10)
```

### 场景4：从其他 agent 接手任务

用户说"之前在 Codex 上做的，现在在 WorkBuddy 继续"时：

1. 先搜索：`search_tasks(query="关键词")`
2. 获取上下文：`get_task_context(task_id="<找到的task_id>")`
3. 正式接手：`handoff_task(task_id="...", from_agent="codex", to_agent="workbuddy", note="codex抽风了，在wb继续")`

## 自动化规则（全自动模式）

本系统是 Summer 的个人任务记忆池，5 个 agent 共享同一存储（~/.agent-memory/）。记录是**默认行为，无需用户确认**。agent_id 填自己的（workbuddy），不用问 Summer。

### 实质性任务边界（什么才值得记）
- ✅ 记：多步骤、有明确产出的任务（搭建系统 / 调试 bug / 写报告 / 调研课题 / 重构模块 / 部署服务）
- ❌ 不记：查个资料、闲聊、改 typo、单步小操作、纯问答、格式调整
- 拿不准时**宁可不记**，避免噪音污染记忆池

### 默认行为（不用等 Summer 提醒）
1. **会话开始** → 先调 `list_active_tasks`。若有未完成任务，主动告知：「你有 N 个任务没做完：…，要继续哪个吗」
2. **识别到实质性新任务开始** → 默认调 `create_task`（不用问），task_id 暂存本会话上下文
3. **任务完成** → 默认调 `update_progress(action="completed", summary="关键产出摘要")`
4. **Summer 提到切换工具 / 在 XX 上继续** → 默认调 `handoff_task`
5. **Summer 问"之前做过 / 上次谁搞的 / 任务历史"** → 默认调 `search_tasks`

### 记录纪律
- 同一会话同一任务只 create 一次，后续用 update_progress
- title 一句话讲清目标，description 写目标+预期产出，progress 写关键节点不写流水账

## Agent ID 对照

| Agent | agent_id |
|-------|----------|
| WorkBuddy | workbuddy |
| Codex | codex |
| Hermes | hermes |
| Hanako | hanako |
| ZCode | zcode |

## MCP 配置

确保 `~/.workbuddy/mcp.json` 中已配置 agent-memory Server：

```json
{
  "mcpServers": {
    "agent-memory": {
      "command": "/Users/mumu/.workbuddy/binaries/python/envs/default/bin/python",
      "args": ["/Users/mumu/Library/CloudStorage/OneDrive-个人/02-领域/02-Research/agent-memory/src/agent_memory/server.py"]
    }
  }
}
```
