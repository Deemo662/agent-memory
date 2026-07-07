# 跨 Agent 统一记忆系统

> 让5个 agent（WorkBuddy / Codex / Hermes / Hanako / ZCode）共享同一份任务记忆。

## 这是什么

一个 MCP Memory Server，通过 MCP 协议让所有 agent 共享任务记录、进度和上下文。解决 agent 抽风后切换时"不记得之前谁做了什么"的问题。

## 快速开始

### 1. 安装依赖

```bash
# 依赖已安装在 managed venv 中
# 如果需要重新安装：
/Users/mumu/.workbuddy/binaries/python/envs/default/bin/pip install -r requirements.txt
```

### 2. 配置 WorkBuddy MCP

在 `~/.workbuddy/mcp.json` 中添加：

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

### 3. 安装 WorkBuddy Skill

```bash
cp -r skills/agent-memory-recorder ~/.workbuddy/skills/
```

### 4. 使用 CLI

```bash
# 用 managed venv 的 python 运行 CLI
PYTHON="/Users/mumu/.workbuddy/binaries/python/envs/default/bin/python"
SERVER="/Users/mumu/Library/CloudStorage/OneDrive-个人/02-领域/02-Research/agent-memory/src/agent_memory"

# 创建任务
$PYTHON $SERVER/cli.py create "重构认证模块" --by workbuddy --desc "迁移到JWT" --tags "coding,refactor"

# 更新进度
$PYTHON $SERVER/cli.py update <task_id> --by workbuddy --action completed --summary "完成"

# 搜索任务
$PYTHON $SERVER/cli.py search "认证"

# 列出活跃任务
$PYTHON $SERVER/cli.py list

# 查看任务上下文
$PYTHON $SERVER/cli.py context <task_id>

# 交接任务
$PYTHON $SERVER/cli.py handoff <task_id> --from workbuddy --to codex --note "wb抽风了"

# 查看统计
$PYTHON $SERVER/cli.py stats
```

## 架构

```
WorkBuddy ─┐
Codex ─────┼──→  MCP Memory Server  ──→  SQLite + Markdown
Hanako ────┤     (6个 tools)              (~/.agent-memory/)
Hermes ────┤
ZCode ─────┘
```

## 数据存储

| 存储 | 用途 | 路径 |
|------|------|------|
| SQLite | 任务索引 + FTS5全文搜索 | `~/.agent-memory/memory.db` |
| Markdown | 人类可读上下文 | `~/.agent-memory/tasks/{task_id}/context.md` |

## MCP Tools

| Tool | 说明 |
|------|------|
| `create_task` | 创建新任务 |
| `update_progress` | 更新任务进度 |
| `search_tasks` | 搜索任务历史（FTS5） |
| `get_task_context` | 获取任务完整上下文 |
| `handoff_task` | 交接任务给另一个 agent |
| `list_active_tasks` | 列出活跃任务 |
| `register_agent` | 注册 agent |
| `list_agents` | 列出已注册 agent |

## 落地路线

- ✅ **Phase 1**（当前）：核心 MCP Server + WorkBuddy 接入 + CLI
- ⬜ Phase 2：Codex / Hermes 接入
- ⬜ Phase 3：ZCode / Hanako 接入
- ⬜ Phase 4：Web UI + 自动化优化

## 项目结构

```
agent-memory/
├── DESIGN.md                      # 顶层设计文档
├── README.md                      # 本文件
├── requirements.txt               # Python 依赖
├── src/agent_memory/
│   ├── __init__.py
│   ├── models.py                  # 数据模型
│   ├── storage.py                 # SQLite + Markdown 存储
│   ├── server.py                  # MCP Server（6+2 tools）
│   └── cli.py                     # CLI 工具
├── skills/
│   └── agent-memory-recorder/     # WorkBuddy skill
│       └── SKILL.md
└── tests/
```
