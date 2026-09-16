"""ORM model registry. Importing this module registers all mappings on Base.metadata."""

from app.db.models.agents import Agent, AgentSession
from app.db.models.artifacts import Artifact
from app.db.models.codeintel import ModelInvocation, Symbol, SymbolFile
from app.db.models.events import Event
from app.db.models.infra import RuntimeInstance, ToolchainConfig
from app.db.models.isolation import Resource, Worktree
from app.db.models.knowledge import ContextItem, Memory
from app.db.models.messages import Message
from app.db.models.oversight import Decision, HitlRequest, Review, Validation
from app.db.models.project import Project
from app.db.models.requirements import AcceptanceCriterion, Plan, Requirement
from app.db.models.tasks import Task, TaskAttempt, TaskDependency
from app.db.models.workspace import Workspace

__all__ = [
    "AcceptanceCriterion",
    "Agent",
    "AgentSession",
    "Artifact",
    "ContextItem",
    "Decision",
    "Event",
    "HitlRequest",
    "Memory",
    "Message",
    "ModelInvocation",
    "Plan",
    "Project",
    "Requirement",
    "Resource",
    "Review",
    "RuntimeInstance",
    "Symbol",
    "SymbolFile",
    "Task",
    "TaskAttempt",
    "TaskDependency",
    "ToolchainConfig",
    "Validation",
    "Workspace",
    "Worktree",
]
