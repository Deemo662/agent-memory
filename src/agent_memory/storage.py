"""存储层 — SQLite 索引 + Markdown 上下文双存储"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from .models import (
        AgentInfo,
        DEFAULT_AGENTS,
        DEFAULT_TAG_ROUTING,
        Task,
        TaskAction,
        TaskArtifact,
        TaskComment,
        TaskEvent,
        TaskProgress,
        TaskStatus,
        ArtifactStatus,
        CommentType,
        EventType,
        ReviewVerdict,
    )
except ImportError:
    from models import (
        AgentInfo,
        DEFAULT_AGENTS,
        DEFAULT_TAG_ROUTING,
        Task,
        TaskAction,
        TaskArtifact,
        TaskComment,
        TaskEvent,
        TaskProgress,
        TaskStatus,
        ArtifactStatus,
        CommentType,
        EventType,
        ReviewVerdict,
    )

DEFAULT_BASE_DIR = os.path.expanduser("~/.agent-memory")


class MemoryStore:
    """跨 Agent 记忆存储引擎"""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or DEFAULT_BASE_DIR)
        self.db_path = self.base_dir / "memory.db"
        self.tasks_dir = self.base_dir / "tasks"
        self.agents_dir = self.base_dir / "agents"
        self._init_dirs()
        self._init_db()
        self._init_default_agents()

    def _init_dirs(self):
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(parents=True, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id       TEXT PRIMARY KEY,
                title         TEXT NOT NULL,
                description   TEXT DEFAULT '',
                status        TEXT DEFAULT 'pending',
                created_by    TEXT NOT NULL,
                current_agent TEXT DEFAULT '',
                created_at    TEXT DEFAULT '',
                updated_at    TEXT DEFAULT '',
                tags          TEXT DEFAULT '[]',
                priority      TEXT DEFAULT 'normal'
            );

            CREATE TABLE IF NOT EXISTS task_progress (
                progress_id  TEXT PRIMARY KEY,
                task_id      TEXT NOT NULL,
                agent_id     TEXT NOT NULL,
                timestamp    TEXT DEFAULT '',
                action       TEXT NOT NULL,
                summary      TEXT DEFAULT '',
                context_file TEXT DEFAULT '',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS agents (
                agent_id      TEXT PRIMARY KEY,
                agent_name    TEXT NOT NULL,
                capabilities  TEXT DEFAULT '',
                keywords      TEXT DEFAULT '[]',
                registered_at TEXT DEFAULT ''
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
                task_id, title, description, tags,
                content='tasks',
                content_rowid='rowid'
            );

            CREATE TABLE IF NOT EXISTS task_comments (
                comment_id   TEXT PRIMARY KEY,
                task_id      TEXT NOT NULL,
                agent_id     TEXT NOT NULL,
                comment_type TEXT DEFAULT 'discussion',
                content      TEXT DEFAULT '',
                verdict      TEXT DEFAULT '',
                artifact_id  TEXT DEFAULT '',
                created_at   TEXT DEFAULT '',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS task_artifacts (
                artifact_id   TEXT PRIMARY KEY,
                task_id       TEXT NOT NULL,
                agent_id      TEXT NOT NULL,
                artifact_type TEXT DEFAULT '',
                content       TEXT DEFAULT '',
                version       INTEGER DEFAULT 1,
                status        TEXT DEFAULT 'active',
                superseded_by TEXT DEFAULT '',
                created_at    TEXT DEFAULT '',
                updated_at    TEXT DEFAULT '',
                FOREIGN KEY (task_id) REFERENCES tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS events (
                event_id    TEXT PRIMARY KEY,
                task_id     TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                agent_id    TEXT NOT NULL,
                timestamp   INTEGER NOT NULL,
                payload     TEXT DEFAULT '{}',
                consumed_by TEXT DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
            CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
            """
        )
        # P0-1: 显式 migration — 给老 tasks 表加新字段
        self._migrate_schema(conn)
        conn.commit()
        conn.close()

    def _init_default_agents(self):
        for agent in DEFAULT_AGENTS:
            self.register_agent(agent)

    def _migrate_schema(self, conn):
        """P0-1: 显式 migration — 检查字段是否存在，不存在才 ALTER TABLE ADD COLUMN。
        CREATE TABLE IF NOT EXISTS 对已存在的表是 no-op，加字段必须显式 ALTER。"""
        task_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        task_migrations = [
            ("revision_count", "INTEGER DEFAULT 0"),
        ]
        for col, typedef in task_migrations:
            if col not in task_cols:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typedef}")

        agent_cols = {r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()}
        if "keywords" not in agent_cols:
            conn.execute("ALTER TABLE agents ADD COLUMN keywords TEXT DEFAULT '[]'")

    # ── Task 操作 ──────────────────────────────────────────

    def create_task(self, task: Task) -> Task:
        conn = self._get_conn()
        if not task.current_agent:
            task.current_agent = task.created_by
        conn.execute(
            """INSERT INTO tasks
               (task_id, title, description, status, created_by, current_agent,
                created_at, updated_at, tags, priority)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.task_id, task.title, task.description, task.status.value,
                task.created_by, task.current_agent,
                task.created_at, task.updated_at,
                json.dumps(task.tags, ensure_ascii=False), task.priority,
            ),
        )
        conn.execute(
            "INSERT INTO tasks_fts (task_id, title, description, tags) VALUES (?, ?, ?, ?)",
            (task.task_id, task.title, task.description, json.dumps(task.tags, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()

        # 创建任务目录和 context.md
        task_dir = self.tasks_dir / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        self._write_context_md(task)

        # 记录 created 进度
        self.update_progress(TaskProgress(
            task_id=task.task_id,
            agent_id=task.created_by,
            action=TaskAction.CREATED,
            summary=f"任务创建: {task.title}",
        ))
        return task

    def get_task(self, task_id: str) -> Optional[Task]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        conn.close()
        return self._row_to_task(row) if row else None

    def search_tasks(
        self,
        query: str = "",
        agent_id: str = "",
        status: str = "",
        limit: int = 20,
    ) -> list[Task]:
        conn = self._get_conn()

        if query:
            # 先尝试 FTS5 全文搜索
            fts_sql = (
                "SELECT t.* FROM tasks t "
                "JOIN tasks_fts f ON t.task_id = f.task_id "
                "WHERE tasks_fts MATCH ?"
            )
            fts_params: list = [query]
            if agent_id:
                fts_sql += " AND t.current_agent = ?"
                fts_params.append(agent_id)
            if status:
                fts_sql += " AND t.status = ?"
                fts_params.append(status)
            fts_sql += " ORDER BY t.updated_at DESC LIMIT ?"
            fts_params.append(limit)
            rows = conn.execute(fts_sql, fts_params).fetchall()

            # FTS5 无结果时，用 LIKE 回退（支持中文）
            if not rows:
                like = f"%{query}%"
                like_sql = "SELECT * FROM tasks WHERE (title LIKE ? OR description LIKE ?)"
                like_params: list = [like, like]
                if agent_id:
                    like_sql += " AND current_agent = ?"
                    like_params.append(agent_id)
                if status:
                    like_sql += " AND status = ?"
                    like_params.append(status)
                like_sql += " ORDER BY updated_at DESC LIMIT ?"
                like_params.append(limit)
                rows = conn.execute(like_sql, like_params).fetchall()
        else:
            sql = "SELECT * FROM tasks WHERE 1=1"
            params: list = []
            if agent_id:
                sql += " AND current_agent = ?"
                params.append(agent_id)
            if status:
                sql += " AND status = ?"
                params.append(status)
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(sql, params).fetchall()

        conn.close()
        return [self._row_to_task(r) for r in rows]

    def list_active_tasks(self, agent_id: str = "") -> list[Task]:
        conn = self._get_conn()
        if agent_id:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE current_agent = ? AND status IN ('pending','in_progress','handed_off') ORDER BY updated_at DESC",
                (agent_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status IN ('pending','in_progress','handed_off') ORDER BY updated_at DESC"
            ).fetchall()
        conn.close()
        return [self._row_to_task(r) for r in rows]

    def handoff_task(self, task_id: str, from_agent: str, to_agent: str, note: str) -> Optional[Task]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        if not row:
            conn.close()
            return None
        conn.execute(
            "UPDATE tasks SET current_agent = ?, status = 'in_progress', updated_at = ? WHERE task_id = ?",
            (to_agent, _now_iso(), task_id),
        )
        conn.commit()
        conn.close()

        self.update_progress(TaskProgress(
            task_id=task_id,
            agent_id=from_agent,
            action=TaskAction.HANDED_OFF,
            summary=f"交接给 {to_agent}: {note}",
        ))
        return self.get_task(task_id)

    # ── Progress 操作 ──────────────────────────────────────

    def update_progress(self, progress: TaskProgress) -> TaskProgress:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO task_progress
               (progress_id, task_id, agent_id, timestamp, action, summary, context_file)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                progress.progress_id, progress.task_id, progress.agent_id,
                progress.timestamp, progress.action.value, progress.summary,
                progress.context_file,
            ),
        )

        if progress.action == TaskAction.COMPLETED:
            conn.execute(
                "UPDATE tasks SET status = 'completed', updated_at = ? WHERE task_id = ?",
                (_now_iso(), progress.task_id),
            )
        elif progress.action == TaskAction.UPDATED:
            conn.execute(
                "UPDATE tasks SET status = 'in_progress', updated_at = ? WHERE task_id = ?",
                (_now_iso(), progress.task_id),
            )

        conn.commit()
        conn.close()

        self._append_progress_md(progress)
        return progress

    def get_task_progress(self, task_id: str) -> list[TaskProgress]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM task_progress WHERE task_id = ? ORDER BY timestamp",
            (task_id,),
        ).fetchall()
        conn.close()
        return [
            TaskProgress(
                progress_id=r["progress_id"],
                task_id=r["task_id"],
                agent_id=r["agent_id"],
                timestamp=r["timestamp"],
                action=TaskAction(r["action"]),
                summary=r["summary"],
                context_file=r["context_file"],
            )
            for r in rows
        ]

    def get_task_context(self, task_id: str) -> Optional[str]:
        task = self.get_task(task_id)
        if not task:
            return None
        progress_list = self.get_task_progress(task_id)

        lines = [
            f"# {task.title}",
            "",
            "## 基本信息",
            f"- **Task ID**: {task.task_id}",
            f"- **状态**: {task.status.value}",
            f"- **创建者**: {task.created_by}",
            f"- **当前负责**: {task.current_agent}",
            f"- **创建时间**: {task.created_at}",
            f"- **标签**: {', '.join(task.tags) if task.tags else '无'}",
            f"- **优先级**: {task.priority}",
            "",
            "## 任务描述",
            task.description or "无",
            "",
            "## 进度历史",
        ]
        for p in progress_list:
            lines.append(f"\n### [{p.timestamp}] {p.agent_id} — {p.action.value}")
            lines.append(p.summary or "无")

        return "\n".join(lines)

    # ── Agent 操作 ─────────────────────────────────────────

    def register_agent(self, agent: AgentInfo) -> AgentInfo:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO agents (agent_id, agent_name, capabilities, keywords, registered_at) VALUES (?, ?, ?, ?, ?)",
            (agent.agent_id, agent.agent_name, agent.capabilities,
             json.dumps(agent.keywords, ensure_ascii=False), agent.registered_at),
        )
        conn.commit()
        conn.close()
        return agent

    def list_agents(self) -> list[AgentInfo]:
        conn = self._get_conn()
        rows = conn.execute("SELECT * FROM agents ORDER BY agent_name").fetchall()
        conn.close()
        result = []
        for r in rows:
            keys = r.keys()
            result.append(AgentInfo(
                agent_id=r["agent_id"],
                agent_name=r["agent_name"],
                capabilities=r["capabilities"],
                registered_at=r["registered_at"],
                keywords=json.loads(r["keywords"]) if "keywords" in keys and r["keywords"] else [],
            ))
        return result

    # ── 内部辅助 ───────────────────────────────────────────

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        keys = row.keys()
        return Task(
            task_id=row["task_id"],
            title=row["title"],
            description=row["description"] or "",
            status=TaskStatus(row["status"]),
            created_by=row["created_by"],
            current_agent=row["current_agent"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
            tags=json.loads(row["tags"]) if row["tags"] else [],
            priority=row["priority"] or "normal",
            revision_count=row["revision_count"] if "revision_count" in keys else 0,
        )

    def _write_context_md(self, task: Task):
        ctx_path = self.tasks_dir / task.task_id / "context.md"
        ctx_path.write_text(
            f"# {task.title}\n\n"
            f"## 基本信息\n"
            f"- **Task ID**: {task.task_id}\n"
            f"- **状态**: {task.status.value}\n"
            f"- **创建者**: {task.created_by}\n"
            f"- **当前负责**: {task.current_agent}\n"
            f"- **创建时间**: {task.created_at}\n"
            f"- **标签**: {', '.join(task.tags) if task.tags else '无'}\n\n"
            f"## 任务描述\n{task.description or '无'}\n\n"
            f"## 进度历史\n",
            encoding="utf-8",
        )

    def _append_progress_md(self, progress: TaskProgress):
        ctx_path = self.tasks_dir / progress.task_id / "context.md"
        if not ctx_path.exists():
            return
        content = ctx_path.read_text(encoding="utf-8")
        content += f"\n### [{progress.timestamp}] {progress.agent_id} — {progress.action.value}\n{progress.summary or '无'}\n"
        ctx_path.write_text(content, encoding="utf-8")

    # ── 群聊协作层：Comment 操作 ────────────────────────────

    def add_comment(self, comment: TaskComment) -> TaskComment:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO task_comments
               (comment_id, task_id, agent_id, comment_type, content, verdict, artifact_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (comment.comment_id, comment.task_id, comment.agent_id,
             comment.comment_type.value, comment.content, comment.verdict,
             comment.artifact_id, comment.created_at),
        )
        conn.commit()
        conn.close()

        self.publish_event(TaskEvent(
            task_id=comment.task_id,
            event_type=EventType.COMMENT_ADDED.value,
            agent_id=comment.agent_id,
            payload=json.dumps({"comment_id": comment.comment_id, "content": comment.content[:200]}, ensure_ascii=False),
        ))
        return comment

    def list_comments(self, task_id: str, comment_type: str = "") -> list[TaskComment]:
        conn = self._get_conn()
        if comment_type:
            rows = conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? AND comment_type = ? ORDER BY created_at",
                (task_id, comment_type),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        conn.close()
        return [self._row_to_comment(r) for r in rows]

    # ── Artifact 操作（产物版本化）────────────────────────────

    def add_artifact(self, artifact: TaskArtifact) -> TaskArtifact:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO task_artifacts
               (artifact_id, task_id, agent_id, artifact_type, content, version,
                status, superseded_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (artifact.artifact_id, artifact.task_id, artifact.agent_id,
             artifact.artifact_type, artifact.content, artifact.version,
             artifact.status.value, artifact.superseded_by,
             artifact.created_at, artifact.updated_at),
        )
        conn.commit()
        conn.close()

        self.publish_event(TaskEvent(
            task_id=artifact.task_id,
            event_type=EventType.ARTIFACT_SUBMITTED.value,
            agent_id=artifact.agent_id,
            payload=json.dumps({"artifact_id": artifact.artifact_id, "type": artifact.artifact_type}, ensure_ascii=False),
        ))
        return artifact

    def list_artifacts(self, task_id: str, status: str = "") -> list[TaskArtifact]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM task_artifacts WHERE task_id = ? AND status = ? ORDER BY updated_at DESC",
                (task_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM task_artifacts WHERE task_id = ? ORDER BY updated_at DESC",
                (task_id,),
            ).fetchall()
        conn.close()
        return [self._row_to_artifact(r) for r in rows]

    def update_artifact(self, artifact_id: str, agent_id: str, new_content: str, expected_version: int) -> Optional[TaskArtifact]:
        """P1-2: 乐观锁更新 — affected_rows == 0 表示冲突"""
        conn = self._get_conn()
        cur = conn.execute(
            """UPDATE task_artifacts SET content = ?, version = version + 1, updated_at = ?
               WHERE artifact_id = ? AND version = ? AND status = 'active'""",
            (new_content, _now_iso(), artifact_id, expected_version),
        )
        conn.commit()
        affected = cur.rowcount
        conn.close()
        if affected == 0:
            return None
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM task_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        conn.close()
        return self._row_to_artifact(row) if row else None

    def supersede_artifact(self, artifact_id: str, superseded_by: str = "") -> Optional[TaskArtifact]:
        """标记 artifact 为 superseded，保留可见性"""
        conn = self._get_conn()
        cur = conn.execute(
            "UPDATE task_artifacts SET status = 'superseded', superseded_by = ?, updated_at = ? WHERE artifact_id = ? AND status = 'active'",
            (superseded_by, _now_iso(), artifact_id),
        )
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            return None
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM task_artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        conn.close()
        return self._row_to_artifact(row) if row else None

    # ── Review 操作（P1-3: 独立 tool + verdict）──────────────

    def review_artifact(self, task_id: str, artifact_id: str, reviewer: str,
                        verdict: str, comment_text: str = "") -> TaskComment:
        """P1-3: 审查独立 — 创建 review 类型 comment + 更新 artifact 状态"""
        comment = TaskComment(
            task_id=task_id,
            agent_id=reviewer,
            comment_type=CommentType.REVIEW,
            content=comment_text,
            verdict=verdict,
            artifact_id=artifact_id,
        )
        self.add_comment(comment)

        if verdict == ReviewVerdict.REJECT.value:
            conn = self._get_conn()
            conn.execute(
                "UPDATE task_artifacts SET status = 'rejected', updated_at = ? WHERE artifact_id = ?",
                (_now_iso(), artifact_id),
            )
            conn.commit()
            conn.close()

        self.publish_event(TaskEvent(
            task_id=task_id,
            event_type=EventType.REVIEW_VERDICT.value,
            agent_id=reviewer,
            payload=json.dumps({"artifact_id": artifact_id, "verdict": verdict}, ensure_ascii=False),
        ))
        return comment

    # ── Reopen 操作（P1-1: 强制约束）─────────────────────────

    def reopen_task(self, task_id: str, agent_id: str, reason: str) -> Optional[Task]:
        """P1-1: reopen 三重约束 — reason≥10字符 + 上限3次 + 权限校验"""
        task = self.get_task(task_id)
        if not task:
            return None

        if not reason or len(reason.strip()) < 10:
            raise ValueError("reopen 必须填写 reason（≥10 字符），说明推翻原因")

        if agent_id not in (task.created_by, task.current_agent):
            raise PermissionError(
                f"仅 created_by({task.created_by}) 或 current_agent({task.current_agent}) 可 reopen，当前 agent: {agent_id}"
            )

        if task.revision_count >= 3:
            raise RuntimeError(
                f"reopen 次数已达上限(3)，请 escalate 到 workbuddy 仲裁。当前 revision_count: {task.revision_count}"
            )

        conn = self._get_conn()
        active_artifacts = conn.execute(
            "SELECT artifact_id FROM task_artifacts WHERE task_id = ? AND status = 'active'",
            (task_id,),
        ).fetchall()
        for a in active_artifacts:
            conn.execute(
                "UPDATE task_artifacts SET status = 'superseded', updated_at = ? WHERE artifact_id = ?",
                (_now_iso(), a["artifact_id"]),
            )

        conn.execute(
            "UPDATE tasks SET status = 'in_progress', revision_count = revision_count + 1, updated_at = ? WHERE task_id = ?",
            (_now_iso(), task_id),
        )
        conn.commit()
        conn.close()

        self.update_progress(TaskProgress(
            task_id=task_id,
            agent_id=agent_id,
            action=TaskAction.REOPENED,
            summary=f"reopen (第{task.revision_count + 1}次): {reason}",
        ))

        self.publish_event(TaskEvent(
            task_id=task_id,
            event_type=EventType.TASK_REOPENED.value,
            agent_id=agent_id,
            payload=json.dumps(
                {"reason": reason, "revision_count": task.revision_count + 1, "superseded_count": len(active_artifacts)},
                ensure_ascii=False,
            ),
        ))

        return self.get_task(task_id)

    # ── suggest_agent（P0-2: 关键词 + fallback）───────────────

    def suggest_agent(self, task_id: str = "", query: str = "") -> dict:
        """P0-2: 三级 fallback 策略
        1. 关键词匹配 agent.keywords
        2. tag 路由 DEFAULT_TAG_ROUTING
        3. 默认 workbuddy
        """
        text = query
        task = None
        if task_id:
            task = self.get_task(task_id)
            if task:
                text = f"{task.title} {task.description} {' '.join(task.tags)} {query}".strip()

        agents = self.list_agents()
        scores = {}

        if text:
            text_lower = text.lower()
            for agent in agents:
                keyword_hits = sum(1 for kw in agent.keywords if kw.lower() in text_lower)
                cap_hits = sum(
                    1 for cap in agent.capabilities.replace("，", " ").split()
                    if cap and cap.lower() in text_lower
                )
                scores[agent.agent_id] = keyword_hits * 2 + cap_hits

        max_score = max(scores.values()) if scores else 0

        if max_score > 0:
            best = max(scores, key=scores.get)
            return {
                "suggested_agent": best,
                "strategy": "keyword_match",
                "score": max_score,
                "scores": scores,
            }

        if task and task.tags:
            for tag in task.tags:
                tag_lower = tag.lower()
                if tag_lower in DEFAULT_TAG_ROUTING:
                    routed = DEFAULT_TAG_ROUTING[tag_lower]
                    active_counts = {a: len(self.list_active_tasks(a)) for a in routed}
                    best = min(active_counts, key=active_counts.get)
                    return {
                        "suggested_agent": best,
                        "strategy": "tag_routing",
                        "tag": tag,
                        "candidates": routed,
                    }

        return {
            "suggested_agent": "workbuddy",
            "strategy": "default",
            "reason": "无关键词命中且无 tag 路由，回退默认协调 agent",
        }

    # ── Event Bus（简化版：单表 + 长轮询）─────────────────────

    def publish_event(self, event: TaskEvent) -> TaskEvent:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO events (event_id, task_id, event_type, agent_id, timestamp, payload, consumed_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event.event_id, event.task_id, event.event_type, event.agent_id,
             event.timestamp, event.payload, event.consumed_by),
        )
        conn.commit()
        conn.close()
        return event

    def poll_events(self, agent_id: str, since_ts: int = 0, timeout: int = 30) -> list[TaskEvent]:
        """长轮询拉取未消费事件。timeout 秒内每 1s 查一次，有新事件立即返回，超时返回空列表。"""
        import time
        deadline = time.time() + timeout
        while time.time() < deadline:
            conn = self._get_conn()
            rows = conn.execute(
                """SELECT * FROM events WHERE timestamp > ?
                   AND consumed_by NOT LIKE ?
                   ORDER BY timestamp ASC""",
                (since_ts, f'%"{agent_id}"%'),
            ).fetchall()
            conn.close()
            if rows:
                return [self._row_to_event(r) for r in rows]
            time.sleep(1)
        return []

    def ack_event(self, event_id: str, agent_id: str) -> bool:
        """确认消费事件，避免重复推送"""
        conn = self._get_conn()
        row = conn.execute("SELECT consumed_by FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if not row:
            conn.close()
            return False
        consumed = json.loads(row["consumed_by"]) if row["consumed_by"] else []
        if agent_id not in consumed:
            consumed.append(agent_id)
            conn.execute(
                "UPDATE events SET consumed_by = ? WHERE event_id = ?",
                (json.dumps(consumed, ensure_ascii=False), event_id),
            )
            conn.commit()
        conn.close()
        return True

    # ── 群聊层内部辅助 ───────────────────────────────────────

    def _row_to_comment(self, row: sqlite3.Row) -> TaskComment:
        return TaskComment(
            comment_id=row["comment_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            comment_type=CommentType(row["comment_type"]),
            content=row["content"] or "",
            verdict=row["verdict"] or "",
            artifact_id=row["artifact_id"] or "",
            created_at=row["created_at"] or "",
        )

    def _row_to_artifact(self, row: sqlite3.Row) -> TaskArtifact:
        return TaskArtifact(
            artifact_id=row["artifact_id"],
            task_id=row["task_id"],
            agent_id=row["agent_id"],
            artifact_type=row["artifact_type"] or "",
            content=row["content"] or "",
            version=row["version"],
            status=ArtifactStatus(row["status"]),
            superseded_by=row["superseded_by"] or "",
            created_at=row["created_at"] or "",
            updated_at=row["updated_at"] or "",
        )

    def _row_to_event(self, row: sqlite3.Row) -> TaskEvent:
        return TaskEvent(
            event_id=row["event_id"],
            task_id=row["task_id"],
            event_type=row["event_type"],
            agent_id=row["agent_id"],
            timestamp=row["timestamp"],
            payload=row["payload"] or "{}",
            consumed_by=row["consumed_by"] or "[]",
        )


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat()
