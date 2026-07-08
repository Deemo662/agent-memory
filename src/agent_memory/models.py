"""数据模型 — Task / TaskProgress / AgentInfo + 群聊协作层模型"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    HANDED_OFF = "handed_off"


class TaskAction(str, Enum):
    CREATED = "created"
    UPDATED = "updated"
    COMPLETED = "completed"
    HANDED_OFF = "handed_off"
    NOTE = "note"
    # 群聊协作层新增
    COMMENTED = "commented"
    REVIEWED = "reviewed"
    REOPENED = "reopened"
    SUPERSEDED = "superseded"


class CommentType(str, Enum):
    DISCUSSION = "discussion"
    REVIEW = "review"


class ArtifactStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class ReviewVerdict(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    CHANGES_REQUESTED = "changes_requested"


class EventType(str, Enum):
    COMMENT_ADDED = "comment_added"
    ARTIFACT_SUBMITTED = "artifact_submitted"
    REVIEW_VERDICT = "review_verdict"
    TASK_REOPENED = "task_reopened"
    TASK_HANDOFF = "task_handoff"
    SUGGEST_AGENT = "suggest_agent"
    CONVENTION_UPDATED = "convention_updated"


class Task(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    created_by: str
    current_agent: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tags: list[str] = Field(default_factory=list)
    priority: str = "normal"
    # P1-1: reopen 计数，上限 3 次
    revision_count: int = 0


class TaskProgress(BaseModel):
    progress_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    agent_id: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    action: TaskAction
    summary: str = ""
    context_file: str = ""


class AgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    capabilities: str = ""
    registered_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # P0-2: 二级关键词清单，弥补粗糙 capabilities
    keywords: list[str] = Field(default_factory=list)


# ── 群聊协作层模型 ────────────────────────────────────────


class TaskComment(BaseModel):
    comment_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    agent_id: str
    comment_type: CommentType = CommentType.DISCUSSION
    content: str
    # P1-3: review 类型时填写 verdict
    verdict: str = ""
    artifact_id: str = ""  # review 关联的产出物
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    agent_id: str
    artifact_type: str  # code / doc / diff / image
    content: str
    # P1-2: 乐观锁 version 字段
    version: int = 1
    status: ArtifactStatus = ArtifactStatus.ACTIVE
    superseded_by: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TaskEvent(BaseModel):
    """简化版 Event Bus — 单表 + 长轮询"""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str
    event_type: str
    agent_id: str  # 触发者
    # B-1: 整数 Unix ts 作排序键，isoformat 仅展示
    timestamp: int = Field(default_factory=lambda: int(datetime.now(timezone.utc).timestamp()))
    payload: str = "{}"  # JSON string
    consumed_by: str = "[]"  # JSON string of agent_id list


# 默认5个 agent — P0-2: 加二级关键词清单
DEFAULT_AGENTS = [
    AgentInfo(
        agent_id="workbuddy",
        agent_name="WorkBuddy",
        capabilities="综合，wiki，文字产物",
        keywords=["报告", "文档", "总结", "周报", "计划", "分析", "调研", "写作", "ppt", "md"],
    ),
    AgentInfo(
        agent_id="codex",
        agent_name="Codex",
        capabilities="编码",
        keywords=["代码", "实现", "函数", "类", "bug", "重构", "api", "测试", "sql", "python", "js", "ts"],
    ),
    AgentInfo(
        agent_id="hermes",
        agent_name="Hermes",
        capabilities="多agent实例，消息平台",
        keywords=["消息", "通知", "飞书", "微信", "推送", "集成", "webhook", "群聊"],
    ),
    AgentInfo(
        agent_id="hanako",
        agent_name="Hanako",
        capabilities="深度查东西，电脑问题",
        keywords=["查找", "搜索", "文件", "目录", "系统", "配置", "排查", "诊断", "cli"],
    ),
    AgentInfo(
        agent_id="zcode",
        agent_name="ZCode",
        capabilities="编码（智谱GLM）",
        keywords=["代码", "实现", "函数", "类", "bug", "重构", "api", "测试", "python", "glm"],
    ),
]

# P0-2: tag → 默认 agent 路由（关键词全 miss 时的 fallback）
DEFAULT_TAG_ROUTING = {
    "coding": ["codex", "zcode"],
    "code": ["codex", "zcode"],
    "research": ["hanako", "workbuddy"],
    "调研": ["hanako", "workbuddy"],
    "writing": ["workbuddy"],
    "写作": ["workbuddy"],
    "messaging": ["hermes"],
    "消息": ["hermes"],
}
