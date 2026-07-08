"""agent-memory CLI — Hanako 直连存储层的命令行适配器

所有 agent 共享 ~/.agent-memory/ 下的同一份 SQLite + Markdown 数据。
Hanako 通过 exec_command 调用此脚本，无需 MCP transport。

子命令：
  基础8个: create_task / update_progress / search_tasks / get_task_context
           handoff_task / list_active_tasks / register_agent / list_agents
  群聊协作11个: add_comment / list_comments / add_artifact / list_artifacts
               update_artifact / supersede_artifact / review_artifact
               reopen_task / suggest_agent / poll_events / ack_event
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from storage import MemoryStore
from models import (
    AgentInfo,
    ArtifactStatus,
    CommentType,
    ReviewVerdict,
    Task,
    TaskAction,
    TaskArtifact,
    TaskComment,
    TaskProgress,
)


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _out_table(rows: list[dict], columns: list[str], max_width: int = 40) -> None:
    """P3-6: 简易表格输出。列宽自适应，长内容截断。"""
    if not rows:
        print("(empty)")
        return
    # 计算每列宽度
    col_widths = {}
    for col in columns:
        w = len(col)
        for r in rows:
            val = str(r.get(col, ""))
            w = max(w, min(len(val), max_width))
        col_widths[col] = w
    # 表头
    header = "  ".join(col.ljust(col_widths[col]) for col in columns)
    sep = "  ".join("-" * col_widths[col] for col in columns)
    print(header)
    print(sep)
    for r in rows:
        vals = []
        for col in columns:
            val = str(r.get(col, ""))
            if len(val) > max_width:
                val = val[:max_width - 3] + "..."
            vals.append(val.ljust(col_widths[col]))
        print("  ".join(vals))
    print(f"\n({len(rows)} rows)")


def _res(args: argparse.Namespace, obj: list | dict) -> None:
    """统一输出：--format json 走 JSON，--format table 走表格（仅列表类数据支持）。"""
    if getattr(args, "format", "json") == "table" and isinstance(obj, list) and obj:
        columns = list(obj[0].keys())
        _out_table(obj, columns)
    else:
        _out(obj)


def _err(msg: str) -> None:
    _out({"error": msg})


# ═══════════════════════════════════════════════════════════
# 基础 8 个子命令
# ═══════════════════════════════════════════════════════════

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
        return _err(f"无效 action: {args.action}，可选: {', '.join(a.value for a in TaskAction)}")
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
    _res(args, [
        {
            "task_id": t.task_id[:8], "title": t.title,
            "status": t.status.value, "current_agent": t.current_agent,
            "created_by": t.created_by, "updated_at": t.updated_at[-8:],
            "tags": ",".join(t.tags) if t.tags else "", "priority": t.priority,
        }
        for t in tasks
    ])


def cmd_get_task_context(args: argparse.Namespace) -> None:
    store = MemoryStore()
    ctx = store.get_task_context(args.task_id)
    if ctx is None:
        _err(f"未找到任务: {args.task_id}")
    else:
        print(ctx)


def cmd_handoff_task(args: argparse.Namespace) -> None:
    store = MemoryStore()
    task = store.handoff_task(args.task_id, args.from_agent, args.to_agent, args.note or "")
    if task is None:
        _err(f"未找到任务: {args.task_id}")
    else:
        _out({
            "task_id": task.task_id, "title": task.title,
            "current_agent": task.current_agent, "status": task.status.value,
        })


def cmd_list_active_tasks(args: argparse.Namespace) -> None:
    store = MemoryStore()
    tasks = store.list_active_tasks(agent_id=args.agent_id or "")
    _res(args, [
        {
            "task_id": t.task_id[:8], "title": t.title,
            "status": t.status.value, "current_agent": t.current_agent,
            "created_by": t.created_by, "updated_at": t.updated_at[-8:],
            "priority": t.priority,
        }
        for t in tasks
    ])


def cmd_register_agent(args: argparse.Namespace) -> None:
    store = MemoryStore()
    kw_list = [k.strip() for k in args.keywords.split(",") if k.strip()] if args.keywords else []
    agent = AgentInfo(
        agent_id=args.agent_id,
        agent_name=args.agent_name,
        capabilities=args.capabilities or "",
        keywords=kw_list,
    )
    store.register_agent(agent)
    _out({"agent_id": agent.agent_id, "agent_name": agent.agent_name, "status": "registered"})


def cmd_list_agents(args: argparse.Namespace) -> None:
    store = MemoryStore()
    _res(args, [
        {
            "agent_id": a.agent_id, "agent_name": a.agent_name,
            "capabilities": a.capabilities, "keywords": ",".join(a.keywords),
        }
        for a in store.list_agents()
    ])


# ═══════════════════════════════════════════════════════════
# 群聊协作层 11 个子命令
# ═══════════════════════════════════════════════════════════

def cmd_add_comment(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        ctype = CommentType(args.comment_type)
    except ValueError:
        return _err(f"无效 comment_type: {args.comment_type}，可选: {', '.join(c.value for c in CommentType)}")
    comment = TaskComment(
        task_id=args.task_id,
        agent_id=args.agent_id,
        comment_type=ctype,
        content=args.content,
        verdict=args.verdict or "",
        artifact_id=args.artifact_id or "",
    )
    result = store.add_comment(comment)
    _out({
        "comment_id": result.comment_id, "task_id": result.task_id,
        "agent_id": result.agent_id, "comment_type": result.comment_type.value,
    })


def cmd_list_comments(args: argparse.Namespace) -> None:
    store = MemoryStore()
    comments = store.list_comments(args.task_id, comment_type=args.comment_type or "")
    _res(args, [
        {
            "agent_id": c.agent_id, "comment_type": c.comment_type.value,
            "content": c.content[:80] + "..." if len(c.content) > 80 else c.content,
            "verdict": c.verdict, "created_at": c.created_at[-8:],
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
    _out({
        "artifact_id": result.artifact_id, "task_id": result.task_id,
        "agent_id": result.agent_id, "artifact_type": result.artifact_type,
        "version": result.version, "status": result.status.value,
    })


def cmd_list_artifacts(args: argparse.Namespace) -> None:
    store = MemoryStore()
    artifacts = store.list_artifacts(args.task_id, status=args.status or "")
    _res(args, [
        {
            "agent_id": a.agent_id, "type": a.artifact_type,
            "version": a.version, "status": a.status.value,
            "superseded_by": a.superseded_by[:8] if a.superseded_by else "",
            "created_at": a.created_at[-8:],
        }
        for a in artifacts
    ])


def cmd_update_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    result = store.update_artifact(
        args.artifact_id, args.agent_id, args.content, args.expected_version,
    )
    if result is None:
        _err(f"乐观锁冲突：artifact {args.artifact_id} 的版本已变更，请重新获取后重试")
    else:
        _out({
            "artifact_id": result.artifact_id, "version": result.version,
            "status": result.status.value, "updated_at": result.updated_at,
        })


def cmd_supersede_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    result = store.supersede_artifact(args.artifact_id, superseded_by=args.superseded_by or "")
    if result is None:
        _err(f"未找到活跃 artifact: {args.artifact_id}")
    else:
        _out({
            "artifact_id": result.artifact_id, "status": result.status.value,
            "superseded_by": result.superseded_by,
        })


def cmd_review_artifact(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        ReviewVerdict(args.verdict)
    except ValueError:
        return _err(f"无效 verdict: {args.verdict}，可选: {', '.join(v.value for v in ReviewVerdict)}")
    result = store.review_artifact(
        task_id=args.task_id,
        artifact_id=args.artifact_id,
        reviewer=args.reviewer,
        verdict=args.verdict,
        comment_text=args.comment or "",
    )
    _out({
        "comment_id": result.comment_id, "task_id": result.task_id,
        "agent_id": result.agent_id, "verdict": result.verdict,
    })


def cmd_reopen_task(args: argparse.Namespace) -> None:
    store = MemoryStore()
    try:
        result = store.reopen_task(args.task_id, args.agent_id, args.reason)
        _out({
            "task_id": result.task_id, "title": result.title,
            "status": result.status.value, "revision_count": result.revision_count,
        })
    except (ValueError, PermissionError, RuntimeError) as e:
        _err(str(e))


def cmd_suggest_agent(args: argparse.Namespace) -> None:
    store = MemoryStore()
    result = store.suggest_agent(task_id=args.task_id or "", query=args.query or "")
    _out(result)


def cmd_poll_events(args: argparse.Namespace) -> None:
    store = MemoryStore()
    events = store.poll_events(
        agent_id=args.agent_id,
        since_ts=args.since_ts or 0,
        timeout=args.timeout or 30,
    )
    _out([
        {
            "event_id": e.event_id, "task_id": e.task_id,
            "event_type": e.event_type, "agent_id": e.agent_id,
            "timestamp": e.timestamp, "payload": json.loads(e.payload),
        }
        for e in events
    ])


def cmd_ack_event(args: argparse.Namespace) -> None:
    store = MemoryStore()
    ok = store.ack_event(args.event_id, args.agent_id)
    _out({"event_id": args.event_id, "agent_id": args.agent_id, "acked": ok})


# ═══════════════════════════════════════════════════════════
# main
# ═══════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(prog="agent-memory")
    subs = parser.add_subparsers(dest="command", required=True)

    # ── 基础 ──
    p = subs.add_parser("create_task", help="创建新任务")
    p.add_argument("--title", required=True)
    p.add_argument("--created_by", required=True)
    p.add_argument("--description", default="")
    p.add_argument("--tags", default="")
    p.add_argument("--priority", default="normal")
    p.set_defaults(handler=cmd_create_task)

    p = subs.add_parser("update_progress", help="更新任务进度")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--action", required=True)
    p.add_argument("--summary", default="")
    p.set_defaults(handler=cmd_update_progress)

    p = subs.add_parser("search_tasks", help="搜索任务历史")
    p.add_argument("--query", default="")
    p.add_argument("--agent_id", default="")
    p.add_argument("--status", default="")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--format", choices=["json", "table"], default="json", help="输出格式（默认 json）")
    p.set_defaults(handler=cmd_search_tasks)

    p = subs.add_parser("get_task_context", help="获取任务完整上下文")
    p.add_argument("--task_id", required=True)
    p.set_defaults(handler=cmd_get_task_context)

    p = subs.add_parser("handoff_task", help="交接任务给其他 agent")
    p.add_argument("--task_id", required=True)
    p.add_argument("--from_agent", required=True)
    p.add_argument("--to_agent", required=True)
    p.add_argument("--note", default="")
    p.set_defaults(handler=cmd_handoff_task)

    p = subs.add_parser("list_active_tasks", help="列出活跃任务")
    p.add_argument("--agent_id", default="")
    p.add_argument("--format", choices=["json", "table"], default="json", help="输出格式（默认 json）")
    p.set_defaults(handler=cmd_list_active_tasks)

    p = subs.add_parser("register_agent", help="注册 agent")
    p.add_argument("--agent_id", required=True)
    p.add_argument("--agent_name", required=True)
    p.add_argument("--capabilities", default="")
    p.add_argument("--keywords", default="")
    p.set_defaults(handler=cmd_register_agent)

    p = subs.add_parser("list_agents", help="列出所有已注册 agent")
    p.add_argument("--format", choices=["json", "table"], default="json", help="输出格式（默认 json）")
    p.set_defaults(handler=cmd_list_agents)

    # ── 群聊协作层 ──
    p = subs.add_parser("add_comment", help="为任务添加评论/审查意见")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--comment_type", default="discussion")
    p.add_argument("--verdict", default="")
    p.add_argument("--artifact_id", default="")
    p.set_defaults(handler=cmd_add_comment)

    p = subs.add_parser("list_comments", help="列出任务评论")
    p.add_argument("--task_id", required=True)
    p.add_argument("--comment_type", default="")
    p.add_argument("--format", choices=["json", "table"], default="json", help="输出格式（默认 json）")
    p.set_defaults(handler=cmd_list_comments)

    p = subs.add_parser("add_artifact", help="提交任务产物")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--artifact_type", required=True)
    p.add_argument("--content", required=True)
    p.set_defaults(handler=cmd_add_artifact)

    p = subs.add_parser("list_artifacts", help="列出任务产物")
    p.add_argument("--task_id", required=True)
    p.add_argument("--status", default="")
    p.add_argument("--max_length", type=int, default=500)
    p.add_argument("--format", choices=["json", "table"], default="json", help="输出格式（默认 json）")
    p.set_defaults(handler=cmd_list_artifacts)

    p = subs.add_parser("update_artifact", help="更新产物内容（乐观锁）")
    p.add_argument("--artifact_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--content", required=True)
    p.add_argument("--expected_version", type=int, required=True)
    p.set_defaults(handler=cmd_update_artifact)

    p = subs.add_parser("supersede_artifact", help="标记产物为被取代")
    p.add_argument("--artifact_id", required=True)
    p.add_argument("--superseded_by", default="")
    p.set_defaults(handler=cmd_supersede_artifact)

    p = subs.add_parser("review_artifact", help="审查产物（独立 + verdict）")
    p.add_argument("--task_id", required=True)
    p.add_argument("--artifact_id", required=True)
    p.add_argument("--reviewer", required=True)
    p.add_argument("--verdict", required=True)
    p.add_argument("--comment", default="")
    p.set_defaults(handler=cmd_review_artifact)

    p = subs.add_parser("reopen_task", help="重新打开已完成任务（三重约束）")
    p.add_argument("--task_id", required=True)
    p.add_argument("--agent_id", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(handler=cmd_reopen_task)

    p = subs.add_parser("suggest_agent", help="根据任务内容建议负责 agent")
    p.add_argument("--task_id", default="")
    p.add_argument("--query", default="")
    p.set_defaults(handler=cmd_suggest_agent)

    p = subs.add_parser("poll_events", help="长轮询拉取未消费事件")
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
