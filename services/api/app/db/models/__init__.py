"""ORM model registry. Importing this module registers all mappings on Base.metadata."""

from app.db.models.event import Event
from app.db.models.project import Project

__all__ = ["Event", "Project"]
