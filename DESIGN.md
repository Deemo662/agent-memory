# 跨 Agent 统一记忆系统 — 顶层设计

> 项目代号：agent-memory  
> 创建时间：2026-07-07  
> 状态：顶层设计阶段

---

## 1. 项目概述

### 1.1 问题背景

Summer 日常使用5个 agent 软件，分工不同但有时某个会抽风，需要切换到其他 agent 重跑任务。导致：
- **会话碎片化**：任务散落各 agent，无法统一查看
- **上下文断裂**：切换 agent 时上下文丢失，需手动复述前情
- **任务追踪盲区**：不记得"谁做了什么"，可能重复劳动
- **切换成本高**：每次 agent 切换都要手动搬运上下文

### 1.2 目标

建一个跨5个 agent 的统一记忆系统，实现：
1. 跨 agent 会话索引 — 统一记录所有 agent 的任务历史
2. 任务上下文调用 — 新 agent 接手时能读取旧 agent 的进度
3. 记忆兼容 — 不同 agent 的记忆格式互转/共用
4. 任务交接 — Agent A → Agent B 的平滑切换

### 1.3 设计原则

| 原则 | 说明 |
|------|------|
| **MCP 标准** | 所有 agent 通过 MCP 协议接入，无需改造 agent 本身 |
| **本地优先** | 数据纯本地存储（SQLite + Markdown），隐私安全 |
| **任务粒度** | 以"任务"为核心组织记忆，而非会话或知识点 |
| **全自动** | 通过 hook/插件实现自动写入，零维护 |

### 1.4 覆盖的 Agent

| Agent | 分工 | MCP 支持 | 接入方式 |
|-------|------|---------|---------|
| WorkBuddy | 综合，wiki，文字产物 | 原生 | hook + skill |
| Codex | 编码 | .toml 配置 | MCP 直连 |
| Hermes | 养龙虾，和 WB 冲突 | Stdio + HTTP | MCP 直连 |
| Hanako | 深度查东西，电脑问题 | 同 Hermes 生态 | MCP 直连 |
| ZCode | 编码（体验阶段） | 官方支持 | MCP 直连 |

---

## 2. 架构设计

### 2.1 三层架构

```
┌─────────────────────────────────────────────────────┐
│                    Agent 层                          │
│  WorkBuddy   Codex   Hermes   Hanako   ZCode       │
│  (hook自动)  (MCP)   (MCP)   (MCP)    (MCP)        │
└──────────────────────┬──────────────────────────────┘
                       │ MCP Protocol
┌──────────────────────┴──────────────────────────────┐
│              MCP Memory Server                       │
│  ┌─────────────────────────────────────────────┐    │
│  │  API 层 (MCP Tools)                          │    │
│  │  create_task | update_progress | search     │    │
│  │  get_context | handoff | list_active        │    │
│  └─────────────────────┬───────────────────────┘    │
│  ┌─────────────────────┴───────────────────────┐    │
│  │  存储层                                      │    │
│  │  SQLite (索引/搜索/FTS5)  │  Markdown (上下文)│   │
│  └─────────────────────────────────────────────┘    │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                  本地存储                            │
│  ~/.agent-memory/                                   │
│  ├── memory.db (SQLite)                             │
│  ├── tasks/{task_id}/context.md                     │
│  └── agents/registry.json                           │
└─────────────────────────────────────────────────────┘
```

### 2.2 核心组件

1. **MCP Memory Server** — 核心服务进程，实现 MCP 协议，提供标准化记忆 API
2. **SQLite 存储引擎** — 任务索引、进度历史、Agent 注册表，FTS5 全文搜索
3. **Markdown 上下文存储** — 每个任务一个目录，人类可读的上下文文件
4. **Agent 适配器** — 每个 agent 的接入配置和自动化 hook
5. **CLI 查询工具** — 命令行查询任务历史和上下文

---

## 3. 数据模型

### 3.1 Task（任务）

```sql
CREATE TABLE tasks (
    task_id      TEXT PRIMARY KEY,    -- UUID
    title        TEXT NOT NULL,       -- 任务标题
    description  TEXT,                -- 任务描述
    status       TEXT DEFAULT 'pending',  -- pending/in_progress/completed/failed/handed_off
    created_by   TEXT NOT NULL,       -- 创建任务的 agent_id
    current_agent TEXT,               -- 当前负责的 agent_id
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    tags         TEXT,                -- JSON 数组，标签（项目/类型）
    priority     TEXT DEFAULT 'normal'  -- low/normal/high/urgent
);
```

### 3.2 TaskProgress（任务进度）

```sql
CREATE TABLE task_progress (
    progress_id  TEXT PRIMARY KEY,    -- UUID
    task_id      TEXT NOT NULL,       -- 关联任务
    agent_id     TEXT NOT NULL,       -- 执行 agent
    timestamp    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    action       TEXT NOT NULL,       -- created/updated/completed/handed_off/note
    summary      TEXT,                -- 这一步做了什么（摘要）
    context_file TEXT,                -- 上下文文件路径
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
```

### 3.3 AgentRegistry（Agent 注册表）

```sql
CREATE TABLE agents (
    agent_id     TEXT PRIMARY KEY,    -- agent 标识
    agent_name   TEXT NOT NULL,       -- WorkBuddy/Codex/Hermes/Hanako/ZCode
    capabilities TEXT,                -- 能力描述
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.4 FTS5 全文搜索

```sql
CREATE VIRTUAL TABLE tasks_fts USING fts5(
    task_id, title, description, tags,
    content='tasks',
    content_rowid='rowid'
);
```

---

## 4. MCP API 设计

### 4.1 Tools（工具）

#### 1. create_task — 创建新任务

```json
{
  "name": "create_task",
  "description": "创建一个新任务，记录到跨 agent 记忆系统",
  "parameters": {
    "title": "string, 必填, 任务标题",
    "description": "string, 任务描述",
    "tags": "array, 标签（项目/类型）",
    "created_by": "string, 必填, agent_id",
    "priority": "string, 优先级 low/normal/high/urgent"
  },
  "returns": "task_id"
}
```

#### 2. update_progress — 更新任务进度

```json
{
  "name": "update_progress",
  "description": "更新任务进度，记录当前 agent 做了什么",
  "parameters": {
    "task_id": "string, 必填",
    "agent_id": "string, 必填",
    "action": "string, 必填, created/updated/completed/handed_off/note",
    "summary": "string, 这一步做了什么",
    "context": "string, 可选, 详细上下文（写入 context.md）"
  },
  "returns": "progress_id"
}
```

#### 3. search_tasks — 搜索任务历史

```json
{
  "name": "search_tasks",
  "description": "搜索任务历史，支持全文搜索和过滤",
  "parameters": {
    "query": "string, 搜索关键词",
    "agent_id": "string, 可选, 按 agent 过滤",
    "status": "string, 可选, 按状态过滤",
    "tags": "array, 可选, 按标签过滤",
    "limit": "number, 默认20"
  },
  "returns": "任务列表"
}
```

#### 4. get_task_context — 获取任务完整上下文

```json
{
  "name": "get_task_context",
  "description": "获取任务的完整上下文，包括进度历史和上下文文件内容",
  "parameters": {
    "task_id": "string, 必填"
  },
  "returns": "完整上下文（含进度历史 + context.md 内容）"
}
```

#### 5. handoff_task — 任务交接

```json
{
  "name": "handoff_task",
  "description": "将任务从一个 agent 交接给另一个 agent",
  "parameters": {
    "task_id": "string, 必填",
    "from_agent": "string, 必填",
    "to_agent": "string, 必填",
    "handoff_note": "string, 交接说明"
  },
  "returns": "更新后的 task"
}
```

#### 6. list_active_tasks — 列出活跃任务

```json
{
  "name": "list_active_tasks",
  "description": "列出当前活跃的任务（pending/in_progress/handed_off）",
  "parameters": {
    "agent_id": "string, 可选, 按当前负责 agent 过滤"
  },
  "returns": "活跃任务列表"
}
```

### 4.2 Resources（资源）

| URI | 说明 |
|-----|------|
| `task://{task_id}` | 任务详情 |
| `tasks://active` | 活跃任务列表 |
| `tasks://agent/{agent_id}` | 某个 agent 的任务历史 |

---

## 5. 存储设计

### 5.1 目录结构

```
~/.agent-memory/
├── memory.db                    # SQLite 数据库（任务索引/搜索）
├── tasks/                       # 任务上下文目录
│   └── {task_id}/
│       ├── context.md           # 任务完整上下文（人类可读）
│       ├── progress.jsonl       # 进度历史（JSON Lines）
│       └── artifacts/           # 产出物引用
├── agents/
│   └── registry.json            # Agent 注册表
├── config.yaml                  # 全局配置
└── logs/                        # 日志
```

### 5.2 context.md 格式

```markdown
# {任务标题}

## 基本信息
- **Task ID**: {uuid}
- **状态**: {status}
- **创建者**: {agent_name}
- **当前负责**: {agent_name}
- **创建时间**: {timestamp}
- **标签**: {tags}

## 任务描述
{description}

## 进度历史
### [{timestamp}] {agent_name} - {action}
{summary}

### [{timestamp}] {agent_name} - {action}
{summary}

## 交接记录
### [{timestamp}] {from_agent} → {to_agent}
{handoff_note}
```

---

## 6. 自动化机制

### 6.1 各 Agent 接入方式

| Agent | 接入方式 | 自动化程度 | 实现路径 |
|-------|---------|-----------|---------|
| WorkBuddy | hook + skill | 全自动 | 安装 `agent-memory-recorder` skill，通过 hook 在对话结束时自动调用 `update_progress` |
| Codex | MCP 直连 + AGENTS.md | 全自动 | 配置 MCP Server 到 Codex 的 .toml，在 AGENTS.md 中添加"任务完成时调用 update_progress"指令 |
| Hermes | MCP 直连 + skill | 全自动 | 配置 MCP Server，通过 skill 自动记录 |
| Hanako | MCP 直连（同 Hermes 生态）| 全自动 | 同 Hermes 配置 |
| ZCode | MCP 直连（官方支持）| 全自动 | 在 ZCode 的 MCP 服务器管理页面配置 |

### 6.2 WorkBuddy 自动化方案（详细）

1. 在 `~/.workbuddy/skills/` 安装 `agent-memory-recorder` skill
2. skill 提供：
   - 任务开始时：调用 `create_task`
   - 任务进行中：定期调用 `update_progress`
   - 任务完成时：调用 `update_progress` (action=completed)
   - 任务交接时：调用 `handoff_task`
3. 可选：通过 `user-prompt-submit-hook` 在每次对话开始时自动检查是否有相关任务

### 6.3 任务交接流程

```
Agent A 抽风了
    ↓
用户在 Agent B 中开始任务
    ↓
Agent B 调用 search_tasks 搜索相关任务
    ↓
找到 Agent A 的任务记录
    ↓
Agent B 调用 get_task_context 获取完整上下文
    ↓
Agent B 调用 handoff_task 正式接手
    ↓
Agent B 继续执行，自动更新进度
```

---

## 7. 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| MCP Server | Python (mcp 官方 SDK) | 生态成熟，SQLite 原生支持，与 WorkBuddy skill 共享语言 |
| 数据库 | SQLite + FTS5 | 零依赖，内置全文搜索，本地存储 |
| 上下文存储 | Markdown | 人类可读，可编辑，可 diff |
| CLI 工具 | Python (Typer/Click) | 与 Server 共享代码 |
| Web UI（可选）| FastAPI + 轻量前端 | 后期再加，非核心 |

### 7.1 依赖

```
mcp>=1.0.0          # MCP 官方 SDK
sqlite3              # Python 内置
typer>=0.9.0         # CLI 框架
pydantic>=2.0        # 数据模型
```

---

## 8. 渐进式落地计划

### Phase 1：核心 MCP Server + WorkBuddy 接入（MVP）

**目标**：跑通 WorkBuddy 的任务记录和查询

- [ ] 实现 MCP Server 核心（6个 tools）
- [ ] SQLite + Markdown 存储层
- [ ] WorkBuddy `agent-memory-recorder` skill
- [ ] 基础 CLI 查询工具（`mem search` / `mem list` / `mem context`）

**验收标准**：在 WorkBuddy 中创建任务 → 完成任务 → 用 CLI 查到任务历史

### Phase 2：Codex / Hermes 接入

**目标**：跨 agent 任务交接

- [ ] Codex MCP 配置 + AGENTS.md 指令
- [ ] Hermes MCP 配置 + skill
- [ ] 跨 agent 任务交接验证（Codex → WorkBuddy）
- [ ] Hermes ↔ WorkBuddy 用 hermes-memory-bridge 补齐

**验收标准**：在 Codex 中创建任务 → 切换到 WorkBuddy → 能看到 Codex 的进度

### Phase 3：ZCode / Hanako 接入 + CLI 完善

**目标**：5个 agent 全覆盖

- [ ] ZCode MCP 配置
- [ ] Hanako 接入（同 Hermes 生态）
- [ ] CLI 工具完善（交互式搜索 / 任务看板）
- [ ] 自动化 hook 优化

**验收标准**：任意 agent 创建任务 → 任意其他 agent 能查到并接手

### Phase 4：Web UI + 自动化优化

**目标**：可视化 + 体验优化

- [ ] 轻量 Web UI（任务看板 + 搜索 + 上下文查看）
- [ ] 自动化 hook 精度优化（减少误触发）
- [ ] 性能调优（FTS5 索引优化）
- [ ] 配置文件 + 文档完善

---

## 9. 参考方案

| 方案 | 亮点 | 借鉴点 |
|------|------|--------|
| ClawMem (clawmem.ai) | 跨 agent 记忆共享 + 自动召回 + Console | 自动召回机制、结构化标签 |
| hermes-memory-bridge | WorkBuddy ↔ Hermes 双向桥梁 | 文件信号机制 |
| cross-agent-memory.skill | JSONL + MySQL 双引擎 | Agent 隔离 + 共享机制 |
| Hindsight | 共享 bank_id 多 Hermes 实例 | 简单共享模型 |

---

## 10. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Agent hook 能力差异 | 部分 agent 无法全自动 | 提供手动 CLI fallback |
| 上下文体积过大 | SQLite 膨胀 | 定期归档 + Markdown 分离 |
| 多 agent 并发写入 | 数据冲突 | SQLite WAL 模式 + 写入锁 |
| MCP Server 进程管理 | 需要常驻 | 提供守护进程脚本 |

---

_本文档随项目进展持续更新。_
