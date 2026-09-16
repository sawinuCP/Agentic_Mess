"""ORM model registry. Importing this module registers all mappings on Base.metadata.

Models are grouped into domain subpackages mirroring the route/service areas:
``core`` (events), ``workspace`` (projects/workspaces/infra/artifacts),
``planning`` (requirements/tasks), ``orchestration`` (agents/messages/knowledge/
oversight/isolation), ``intelligence`` (codeintel), ``execution`` (ports).
"""

from app.db.models.core.events import Event
from app.db.models.execution.execution import PortAllocation
from app.db.models.intelligence.codeintel import ModelInvocation, Symbol, SymbolFile
from app.db.models.orchestration.agents import Agent, AgentSession
from app.db.models.orchestration.isolation import Resource, Worktree
from app.db.models.orchestration.knowledge import ContextItem, Memory
from app.db.models.orchestration.messages import Message
from app.db.models.orchestration.oversight import Decision, HitlRequest, Review, Validation
from app.db.models.planning.requirements import AcceptanceCriterion, Plan, Requirement
from app.db.models.planning.tasks import Task, TaskAttempt, TaskDependency
from app.db.models.workspace.artifacts import Artifact
from app.db.models.workspace.infra import RuntimeInstance, ToolchainConfig
from app.db.models.workspace.project import Project
from app.db.models.workspace.workspace import Workspace

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
    "PortAllocation",
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
