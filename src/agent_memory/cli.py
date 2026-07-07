"""agent-memory CLI — Hanako 直连存储层的命令行适配器

所有 agent 共享 ~/.agent-memory/ 下的同一份 SQLite + Markdown 数据。
Hanako 通过 exec_command 调用此脚本，无需 MCP transport。
"""

from __future__ import annotations

import argparse
import json
import sys

# 确保能 import 同级模块
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from storage import MemoryStore
from models import (
    AgentInfo, Task, TaskAction, TaskProgress,
    TaskComment, TaskArtifact,
    CommentType, ArtifactStatus, ReviewVerdict,
)


def _out(obj) -> None:
    """统一 JSON 输出。"""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_create_task(args: argparse.Namespace) -> None:
    store = MemoryStore()
    tag_list = [t.strip() for t in args.tags.split(",") if t.strip()] if args.tags else []
    task = Task(
        title=args.title,
        created_by=args.created_by,
        description=args.description or "",
        tags=tag_list,
        priority=args.priority or "normal",
    )
    result = store.create_task(task)
    _out({"task_id": result.task_id, "title": result.title, "status": result.status.value})


def cmd_update_progress(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        action = TaskAction(args.action)
    except ValueError:
        valid = ", ".join(a.value for a in TaskAction)
        _out({"error": f"无效 action: {args.action}，可选: {valid}"})
        return
    progress = TaskProgress(
        task_id=args.task_id,
        agent_id=args.agent_id,
        action=action,
        summary=args.summary or "",
    )
    result = store.update_progress(progress)
    _out({"progress_id": result.progress_id, "task_id": result.task_id, "action": result.action.value})


def cmd_search_tasks(args: argparse.Namespace) -> None:
    store = MemoryStore()
    tasks = store.search_tasks(
        query=args.query or "",
        agent_id=args.agent_id or "",
        status=args.status or "",
        limit=args.limit or 20,
    )
    _out([
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
    ])


def cmd_get_task_context(args: argparse.Namespace) -> None:
    store = MemoryStore()
    ctx = store.get_task_context(args.task_id)
    if ctx is None:
        _out({"error": f"未找到任务: {args.task_id}"})
    else:
        # 返回纯文本上下文，方便 agent 阅读
        print(ctx)


def cmd_handoff_task(args: argparse.Namespace) -> None:
    store = MemoryStore()
    task = store.handoff_task(
        args.task_id,
        args.from_agent,
        args.to_agent,
        args.note or "",
    )
    if task is None:
        _out({"error": f"未找到任务: {args.task_id}"})
    else:
        _out({
            "task_id": task.task_id,
            "title": task.title,
            "current_agent": task.current_agent,
            "status": task.status.value,
        })


def cmd_list_active_tasks(args: argparse.Namespace) -> None:
    store = MemoryStore()
    tasks = store.list_active_tasks(agent_id=args.agent_id or "")
    _out([
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
    ])


def cmd_register_agent(args: argparse.Namespace) -> None:
    store = MemoryStore()
    agent = AgentInfo(
        agent_id=args.agent_id,
        agent_name=args.agent_name,
        capabilities=args.capabilities or "",
    )
    store.register_agent(agent)
    _out({"agent_id": agent.agent_id, "agent_name": agent.agent_name, "status": "registered"})


def cmd_list_agents(args: argparse.Namespace) -> None:
    store = MemoryStore()
    agents = store.list_agents()
    _out([
        {"agent_id": a.agent_id, "agent_name": a.agent_name, "capabilities": a.capabilities}
        for a in agents
    ])


# ── 群聊协作层命令 ────────────────────────────────────────


def cmd_add_comment(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        ct = CommentType(args.comment_type)
    except ValueError:
        _out({"error": f"无效 comment_type: {args.comment_type}"})
        return
    comment = TaskComment(
        task_id=args.task_id,
        agent_id=args.agent_id,
        comment_type=ct,
        content=args.content,
    )
    result = store.add_comment(comment)
    _out({"comment_id": result.comment_id, "task_id": result.task_id, "comment_type": result.comment_type.value})


def cmd_list_comments(args: argparse.Namespace) -> None:
    store = MemoryStore()
    comments = store.list_comments(args.task_id, args.comment_type or "")
    _out([
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
    ])


def cmd_add_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    artifact = TaskArtifact(
        task_id=args.task_id,
        agent_id=args.agent_id,
        artifact_type=args.artifact_type,
        content=args.content,
    )
    result = store.add_artifact(artifact)
    _out({"artifact_id": result.artifact_id, "task_id": result.task_id, "version": result.version, "status": result.status.value})


def cmd_list_artifacts(args: argparse.Namespace) -> None:
    store = MemoryStore()
    max_len = args.max_length if hasattr(args, "max_length") and args.max_length else 2000
    artifacts = store.list_artifacts(args.task_id, args.status or "")
    out = []
    for a in artifacts:
        content = a.content
        if len(content) > max_len:
            content = content[:max_len] + f"\n...[截断，完整 {len(a.content)} 字符见 storage]"
        out.append({
            "artifact_id": a.artifact_id,
            "agent_id": a.agent_id,
            "artifact_type": a.artifact_type,
            "version": a.version,
            "status": a.status.value,
            "superseded_by": a.superseded_by,
            "created_at": a.created_at,
            "updated_at": a.updated_at,
            "content": content,
        })
    _out(out)


def cmd_update_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    result = store.update_artifact(args.artifact_id, args.agent_id, args.content, args.expected_version)
    if result is None:
        _out({"error": "冲突: 版本号不匹配或产出物已被 superseded/rejected", "expected_version": args.expected_version})
        return
    _out({"artifact_id": result.artifact_id, "version": result.version, "status": result.status.value})


def cmd_review_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        ReviewVerdict(args.verdict)
    except ValueError:
        _out({"error": f"无效 verdict: {args.verdict}"})
        return
    result = store.review_artifact(args.task_id, args.artifact_id, args.reviewer, args.verdict, args.comment or "")
    _out({"comment_id": result.comment_id, "verdict": result.verdict, "reviewer": result.agent_id})


def cmd_reopen_task(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        task = store.reopen_task(args.task_id, args.agent_id, args.reason)
    except (ValueError, PermissionError, RuntimeError) as e:
        _out({"error": str(e)})
        return
    if task is None:
        _out({"error": f"未找到任务: {args.task_id}"})
        return
    _out({
        "task_id": task.task_id,
        "status": task.status.value,
        "revision_count": task.revision_count,
        "current_agent": task.current_agent,
    })


def cmd_suggest_agent(args: argparse.Namespace) -> None:
    store = MemoryStore()
    result = store.suggest_agent(args.task_id or "", args.query or "")
    _out(result)


def cmd_poll_events(args: argparse.Namespace) -> None:
    store = MemoryStore()
    events = store.poll_events(args.agent_id, args.since_ts, args.timeout)
    _out([
        {
            "event_id": e.event_id,
            "task_id": e.task_id,
            "event_type": e.event_type,
            "agent_id": e.agent_id,
            "timestamp": e.timestamp,
            "payload": e.payload,
        }
        for e in events
    ])


def cmd_ack_event(args: argparse.Namespace) -> None:
    store = MemoryStore()
    ok = store.ack_event(args.event_id, args.agent_id)
    _out({"event_id": args.event_id, "agent_id": args.agent_id, "acked": ok})


def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-memory")
    subs = parser.add_subparsers(dest="command", required=True)

    # create_task
    p = subs.add_parser("create_task", help="创建新任务")
    p.add_argument("--title", required=True)
    p.add_argument("--created_by", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--priority", default="normal")
    p.set_defaults(handler=cmd_create_task)

    # update_progress
    p = subs.add_parser("update_progress", help="更新任务进度")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--summary", default="")
    p.set_defaults(handler=cmd_update_progress)

    # search_tasks
    p = subs.add_parser("search_tasks", help="搜索任务历史")
    p.add_argument("--query", default="")
    p.add_argument("--agent_id", default="")
    p.add_argument("--status", default="")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(handler=cmd_search_tasks)

    # get_task_context
    p = subs.add_parser("get_task_context", help="获取任务完整上下文")
    p.add_argument("--task_id", required=True)
    p.set_defaults(handler=cmd_get_task_context)

    # handoff_task
    p = subs.add_parser("handoff_task", help="交接任务给其他 agent")
    p.add_argument("--task_id", required=True)
    p.add_argument("--from_agent", required=True)
    p.add_argument("--to_agent", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(handler=cmd_handoff_task)

    # list_active_tasks
    p = subs.add_parser("list_active_tasks", help="列出活跃任务")
    p.add_argument("--agent_id", default="")
    p.set_defaults(handler=cmd_list_active_tasks)

    # register_agent
    p = subs.add_parser("register_agent", help="注册 agent")
    p.add_argument("--agent_id", required=True)
    p.add_argument("--agent_name", required=True)
    p.add_argument("--capabilities", default="")
    p.set_defaults(handler=cmd_register_agent)

    # list_agents
    p = subs.add_parser("list_agents", help="列出所有已注册 agent")
    p.set_defaults(handler=cmd_list_agents)

    # ── 群聊协作层子命令 ───────────────────────────────────

    p = subs.add_parser("add_comment", help="发表评论（群聊发言）")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--comment_type", default="discussion")
    p.set_defaults(handler=cmd_add_comment)

    p = subs.add_parser("list_comments", help="列出任务评论")
    p.add_argument("--task_id", required=True)
    p.add_argument("--comment_type", default="")
    p.set_defaults(handler=cmd_list_comments)

    p = subs.add_parser("add_artifact", help="提交产出物")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--artifact_type", required=True)
    p.add_argument("--content", required=True)
    p.set_defaults(handler=cmd_add_artifact)

    p = subs.add_parser("list_artifacts", help="列出产出物（含 superseded/rejected）")
    p.add_argument("--task_id", required=True)
    p.add_argument("--status", default="")
    p.add_argument("--max_length", type=int, default=2000)
    p.set_defaults(handler=cmd_list_artifacts)

    p = subs.add_parser("update_artifact", help="乐观锁更新产出物")
    p.add_argument("--artifact_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--expected_version", type=int, required=True)
    p.set_defaults(handler=cmd_update_artifact)

    p = subs.add_parser("review_artifact", help="审查产出物给裁决")
    p.add_argument("--task_id", required=True)
    p.add_argument("--artifact_id", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--verdict", required=True)
    p.add_argument("--comment", default="")
    p.set_defaults(handler=cmd_review_artifact)

    p = subs.add_parser("reopen_task", help="推翻重做（三重约束）")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(handler=cmd_reopen_task)

    p = subs.add_parser("suggest_agent", help="推荐接手 agent")
    p.add_argument("--task_id", default="")
    p.add_argument("--query", default="")
    p.set_defaults(handler=cmd_suggest_agent)

    p = subs.add_parser("poll_events", help="长轮询拉取事件")
    p.add_argument("--agent_id", required=True)
    p.add_argument("--since_ts", type=int, default=0)
    p.add_argument("--timeout", type=int, default=30)
    p.set_defaults(handler=cmd_poll_events)

    p = subs.add_parser("ack_event", help="确认消费事件")
    p.add_argument("--event_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.set_defaults(handler=cmd_ack_event)

    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
