"""MCP Memory Server — 跨 Agent 统一记忆服务

通过 MCP 协议提供任务记录、搜索、交接能力。
所有 agent 通过 MCP 连接此 Server，共享同一份任务记忆。
"""

from __future__ import annotations

import json
import os
import sys

# 确保能 import 同级模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from models import (
    AgentInfo, Task, TaskAction, TaskProgress, TaskStatus,
    TaskComment, TaskArtifact, TaskEvent,
    CommentType, ArtifactStatus, EventType, ReviewVerdict,
)
from storage import MemoryStore

# 初始化存储
store = MemoryStore()

# 创建 MCP Server
mcp = FastMCP("agent-memory")


# ── 6 个核心 Tools ────────────────────────────────────────


@mcp.tool()
def create_task(
    title: str,
    created_by: str,
    description: str = "",
    tags: str = "",
    priority: str = "normal",
) -> str:
    """创建一个新任务，记录到跨 agent 记忆系统。

    Args:
        title: 任务标题
        created_by: 创建任务的 agent_id（workbuddy/codex/hermes/hanako/zcode）
        description: 任务描述
        tags: 标签，逗号分隔（如 "research,coding"）
        priority: 优先级 low/normal/high/urgent
    """
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    task = Task(
        title=title,
        created_by=created_by,
        description=description,
        tags=tag_list,
        priority=priority,
    )
    result = store.create_task(task)
    return json.dumps(
        {"task_id": result.task_id, "title": result.title, "status": result.status.value},
        ensure_ascii=False,
    )


@mcp.tool()
def update_progress(
    task_id: str,
    agent_id: str,
    action: str,
    summary: str = "",
) -> str:
    """更新任务进度，记录当前 agent 做了什么。

    Args:
        task_id: 任务 ID
        agent_id: 执行 agent 的 ID
        action: 动作类型 created/updated/completed/handed_off/note
        summary: 这一步做了什么（摘要）
    """
    try:
        action_enum = TaskAction(action)
    except ValueError:
        return f"错误: 无效的 action '{action}'，可选: {', '.join(a.value for a in TaskAction)}"

    progress = TaskProgress(
        task_id=task_id,
        agent_id=agent_id,
        action=action_enum,
        summary=summary,
    )
    result = store.update_progress(progress)
    return json.dumps(
        {"progress_id": result.progress_id, "task_id": result.task_id, "action": result.action.value},
        ensure_ascii=False,
    )


@mcp.tool()
def search_tasks(
    query: str = "",
    agent_id: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """搜索任务历史，支持全文搜索和过滤。

    Args:
        query: 搜索关键词（FTS5 全文搜索）
        agent_id: 按当前负责 agent 过滤
        status: 按状态过滤 pending/in_progress/completed/failed/handed_off
        limit: 返回数量上限，默认20
    """
    tasks = store.search_tasks(query=query, agent_id=agent_id, status=status, limit=limit)
    return json.dumps(
        [
            {
                "task_id": t.task_id,
                "title": t.title,
                "status": t.status.value,
                "current_agent": t.current_agent,
                "created_by": t.created_by,
                "updated_at": t.updated_at,
                "tags": t.tags,
            }
            for t in tasks
        ],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def get_task_context(task_id: str) -> str:
    """获取任务的完整上下文，包括进度历史。

    新 agent 接手任务时调用此工具，了解之前所有 agent 的执行进度。

    Args:
        task_id: 任务 ID
    """
    context = store.get_task_context(task_id)
    return context if context else f"未找到任务: {task_id}"


@mcp.tool()
def handoff_task(
    task_id: str,
    from_agent: str,
    to_agent: str,
    handoff_note: str = "",
) -> str:
    """将任务从一个 agent 交接给另一个 agent。

    Agent A 抽风后，在 Agent B 中调用此工具正式接手任务。

    Args:
        task_id: 任务 ID
        from_agent: 原 agent ID
        to_agent: 新 agent ID
        handoff_note: 交接说明
    """
    task = store.handoff_task(task_id, from_agent, to_agent, handoff_note)
    if not task:
        return f"未找到任务: {task_id}"
    return json.dumps(
        {
            "task_id": task.task_id,
            "title": task.title,
            "current_agent": task.current_agent,
            "status": task.status.value,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def list_active_tasks(agent_id: str = "") -> str:
    """列出当前活跃的任务（pending/in_progress/handed_off）。

    Args:
        agent_id: 按当前负责 agent 过滤，留空返回所有活跃任务
    """
    tasks = store.list_active_tasks(agent_id=agent_id)
    return json.dumps(
        [
            {
                "task_id": t.task_id,
                "title": t.title,
                "status": t.status.value,
                "current_agent": t.current_agent,
                "created_by": t.created_by,
                "updated_at": t.updated_at,
                "tags": t.tags,
            }
            for t in tasks
        ],
        ensure_ascii=False,
        indent=2,
    )


# ── Agent 管理 Tools ──────────────────────────────────────


@mcp.tool()
def register_agent(agent_id: str, agent_name: str, capabilities: str = "") -> str:
    """注册一个 agent 到记忆系统。

    Args:
        agent_id: agent 唯一标识
        agent_name: agent 名称
        capabilities: 能力描述
    """
    agent = AgentInfo(agent_id=agent_id, agent_name=agent_name, capabilities=capabilities)
    store.register_agent(agent)
    return f"已注册 agent: {agent_name} ({agent_id})"


@mcp.tool()
def list_agents() -> str:
    """列出所有已注册的 agent。"""
    agents = store.list_agents()
    return json.dumps(
        [
            {"agent_id": a.agent_id, "agent_name": a.agent_name, "capabilities": a.capabilities}
            for a in agents
        ],
        ensure_ascii=False,
        indent=2,
    )


# ── 群聊协作层 Tools ──────────────────────────────────────


@mcp.tool()
def add_comment(
    task_id: str,
    agent_id: str,
    content: str,
    comment_type: str = "discussion",
) -> str:
    """在任务下发表评论（群聊发言）。自动触发 comment_added 事件通知其他 agent。

    Args:
        task_id: 任务 ID
        agent_id: 发言 agent ID
        content: 评论内容
        comment_type: discussion（普通讨论）/ review（审查结论，配合 review_artifact 使用）
    """
    try:
        ct = CommentType(comment_type)
    except ValueError:
        return f"错误: 无效 comment_type '{comment_type}'，可选: {', '.join(c.value for c in CommentType)}"
    comment = TaskComment(
        task_id=task_id,
        agent_id=agent_id,
        comment_type=ct,
        content=content,
    )
    result = store.add_comment(comment)
    return json.dumps(
        {"comment_id": result.comment_id, "task_id": result.task_id, "comment_type": result.comment_type.value},
        ensure_ascii=False,
    )


@mcp.tool()
def list_comments(task_id: str, comment_type: str = "") -> str:
    """列出任务下的所有评论（群聊记录）。

    Args:
        task_id: 任务 ID
        comment_type: 过滤类型 discussion/review，留空返回全部
    """
    comments = store.list_comments(task_id, comment_type)
    return json.dumps(
        [
            {
                "comment_id": c.comment_id,
                "agent_id": c.agent_id,
                "comment_type": c.comment_type.value,
                "content": c.content,
                "verdict": c.verdict,
                "artifact_id": c.artifact_id,
                "created_at": c.created_at,
            }
            for c in comments
        ],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def add_artifact(
    task_id: str,
    agent_id: str,
    artifact_type: str,
    content: str,
) -> str:
    """提交产出物（代码/文档/diff）。自动触发 artifact_submitted 事件。

    Args:
        task_id: 任务 ID
        agent_id: 提交 agent ID
        artifact_type: 产出类型 code/doc/diff/image
        content: 产出内容
    """
    artifact = TaskArtifact(
        task_id=task_id,
        agent_id=agent_id,
        artifact_type=artifact_type,
        content=content,
    )
    result = store.add_artifact(artifact)
    return json.dumps(
        {"artifact_id": result.artifact_id, "task_id": result.task_id, "version": result.version, "status": result.status.value},
        ensure_ascii=False,
    )


@mcp.tool()
def list_artifacts(task_id: str, status: str = "") -> str:
    """列出任务的产出物。superseded/rejected 的也可见，用于新 agent 参考旧版本。

    Args:
        task_id: 任务 ID
        status: 过滤状态 active/superseded/rejected，留空返回全部
    """
    artifacts = store.list_artifacts(task_id, status)
    return json.dumps(
        [
            {
                "artifact_id": a.artifact_id,
                "agent_id": a.agent_id,
                "artifact_type": a.artifact_type,
                "version": a.version,
                "status": a.status.value,
                "superseded_by": a.superseded_by,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
                "content_preview": a.content[:200] + "..." if len(a.content) > 200 else a.content,
            }
            for a in artifacts
        ],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def update_artifact(
    artifact_id: str,
    agent_id: str,
    new_content: str,
    expected_version: int,
) -> str:
    """P1-2: 乐观锁更新产出物。expected_version 不匹配会冲突失败。

    Args:
        artifact_id: 产出物 ID
        agent_id: 修改 agent ID
        new_content: 新内容
        expected_version: 调用方持有的当前版本号（乐观锁）
    """
    result = store.update_artifact(artifact_id, agent_id, new_content, expected_version)
    if result is None:
        return json.dumps(
            {"error": "冲突: 版本号不匹配或产出物已被 superseded/rejected", "expected_version": expected_version},
            ensure_ascii=False,
        )
    return json.dumps(
        {"artifact_id": result.artifact_id, "version": result.version, "status": result.status.value},
        ensure_ascii=False,
    )


@mcp.tool()
def review_artifact(
    task_id: str,
    artifact_id: str,
    reviewer: str,
    verdict: str,
    comment: str = "",
) -> str:
    """P1-3: 审查产出物，给出明确裁决。verdict=reject 时自动标记 artifact 为 rejected。

    Args:
        task_id: 任务 ID
        artifact_id: 被审查的产出物 ID
        reviewer: 审查 agent ID
        verdict: 裁决 approve / reject / changes_requested
        comment: 审查说明
    """
    try:
        ReviewVerdict(verdict)
    except ValueError:
        return f"错误: 无效 verdict '{verdict}'，可选: {', '.join(v.value for v in ReviewVerdict)}"
    result = store.review_artifact(task_id, artifact_id, reviewer, verdict, comment)
    return json.dumps(
        {"comment_id": result.comment_id, "verdict": result.verdict, "reviewer": result.agent_id},
        ensure_ascii=False,
    )


@mcp.tool()
def reopen_task(
    task_id: str,
    agent_id: str,
    reason: str,
) -> str:
    """P1-1: 推翻重做。三重约束：reason≥10字符 + 上限3次 + 仅 created_by/current_agent 可操作。
    自动 supersede 所有 active artifacts（保留可见性），revision_count + 1。

    Args:
        task_id: 任务 ID
        agent_id: 发起 reopen 的 agent（必须是 created_by 或 current_agent）
        reason: 推翻原因（≥10 字符）
    """
    try:
        task = store.reopen_task(task_id, agent_id, reason)
    except (ValueError, PermissionError, RuntimeError) as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    if task is None:
        return f"未找到任务: {task_id}"
    return json.dumps(
        {
            "task_id": task.task_id,
            "status": task.status.value,
            "revision_count": task.revision_count,
            "current_agent": task.current_agent,
        },
        ensure_ascii=False,
    )


@mcp.tool()
def suggest_agent(task_id: str = "", query: str = "") -> str:
    """P0-2: 推荐接手 agent。三级 fallback：关键词匹配 → tag 路由 → 默认 workbuddy。

    Args:
        task_id: 任务 ID（提供时用任务标题/描述/标签做匹配）
        query: 额外查询文本（任务未创建时用）
    """
    result = store.suggest_agent(task_id, query)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
def poll_events(
    agent_id: str,
    since_ts: int = 0,
    timeout: int = 30,
) -> str:
    """Event Bus: 长轮询拉取未消费事件。30s 内有新事件立即返回，超时返回空列表。
    拿到事件后应调用 ack_event 确认消费，避免重复推送。

    Args:
        agent_id: 拉取事件的 agent ID
        since_ts: 只拉取此 timestamp 之后的事件（0 表示全部）
        timeout: 长轮询超时秒数，默认 30
    """
    events = store.poll_events(agent_id, since_ts, timeout)
    return json.dumps(
        [
            {
                "event_id": e.event_id,
                "task_id": e.task_id,
                "event_type": e.event_type,
                "agent_id": e.agent_id,
                "timestamp": e.timestamp,
                "payload": e.payload,
            }
            for e in events
        ],
        ensure_ascii=False,
        indent=2,
    )


@mcp.tool()
def ack_event(event_id: str, agent_id: str) -> str:
    """Event Bus: 确认消费事件，避免重复推送。

    Args:
        event_id: 事件 ID
        agent_id: 确认消费的 agent ID
    """
    ok = store.ack_event(event_id, agent_id)
    return json.dumps({"event_id": event_id, "agent_id": agent_id, "acked": ok}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run()
