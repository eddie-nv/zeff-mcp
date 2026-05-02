"""Node domain model.

A node is a primitive food, a composite food, or a taxonomy category.
See DESIGN.md "Three node types" and "The schema" for the contract.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class NodeType(StrEnum):
    primitive = "primitive"
    composite = "composite"
    category = "category"


# Slugified IDs: must start with a lowercase letter, then lowercase letters,
# digits, or underscores. No hyphens (postgres queries on `nodes.id` should
# never need quoting).
_NODE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

NodeStatus = Literal["active", "pending_review", "deprecated"]


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1)
    type: NodeType
    pref_label: str
    alt_labels: Annotated[list[str], Field(default_factory=list)]
    parent_id: str | None = None
    status: NodeStatus = "active"

    @field_validator("id", "parent_id")
    @classmethod
    def _check_id_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _NODE_ID_RE.match(value):
            raise ValueError(f"invalid node id {value!r}: must match {_NODE_ID_RE.pattern}")
        return value

    @field_validator("pref_label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("pref_label must not be empty or whitespace")
        return stripped

    @field_validator("alt_labels")
    @classmethod
    def _normalize_alt_labels(cls, value: list[str]) -> list[str]:
        return [s.strip() for s in value if s and s.strip()]

    @model_validator(mode="after")
    def _no_self_parent(self) -> Node:
        if self.parent_id is not None and self.parent_id == self.id:
            raise ValueError("a node cannot be its own parent")
        return self
