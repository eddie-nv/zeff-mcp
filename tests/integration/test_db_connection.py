"""M0 smoke test: open a session, insert a node, read it back, delete it."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from zeff.db.models import Node

pytestmark = pytest.mark.integration


async def test_insert_read_delete_node(db_session) -> None:
    node = Node(id="test_apple", type="primitive", pref_label="Test Apple")
    db_session.add(node)
    await db_session.commit()

    result = await db_session.execute(select(Node).where(Node.id == "test_apple"))
    fetched = result.scalar_one()
    assert fetched.id == "test_apple"
    assert fetched.type == "primitive"
    assert fetched.pref_label == "Test Apple"
    assert fetched.status == "active"
    assert fetched.created_at is not None

    await db_session.delete(fetched)
    await db_session.commit()

    result = await db_session.execute(select(Node).where(Node.id == "test_apple"))
    assert result.scalar_one_or_none() is None
