"""Unit tests for the Node domain model."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from zeff.domain.nodes import Node, NodeType


class TestNodeType:
    def test_three_values(self) -> None:
        assert {nt.value for nt in NodeType} == {"primitive", "composite", "category"}


class TestNodeId:
    def test_lowercase_alphanumeric_underscore_ok(self) -> None:
        Node(id="honeycrisp_apple", type=NodeType.primitive, pref_label="Honeycrisp Apple")

    def test_digits_in_id_ok(self) -> None:
        Node(id="ny_strip_steak_2024", type=NodeType.primitive, pref_label="x")

    def test_uppercase_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="HoneycrispApple", type=NodeType.primitive, pref_label="x")

    def test_hyphen_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="honeycrisp-apple", type=NodeType.primitive, pref_label="x")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="honeycrisp apple", type=NodeType.primitive, pref_label="x")

    def test_empty_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="", type=NodeType.primitive, pref_label="x")

    def test_leading_digit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="2024_steak", type=NodeType.primitive, pref_label="x")


class TestNodeLabel:
    def test_label_required(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="apple", type=NodeType.primitive)  # type: ignore[call-arg]

    def test_empty_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="apple", type=NodeType.primitive, pref_label="")

    def test_whitespace_only_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(id="apple", type=NodeType.primitive, pref_label="   ")

    def test_label_stripped(self) -> None:
        node = Node(id="apple", type=NodeType.primitive, pref_label="  Apple  ")
        assert node.pref_label == "Apple"


class TestNodeAltLabels:
    def test_default_empty_list(self) -> None:
        node = Node(id="apple", type=NodeType.primitive, pref_label="Apple")
        assert node.alt_labels == []

    def test_alt_labels_stripped_and_filtered(self) -> None:
        node = Node(
            id="apple",
            type=NodeType.primitive,
            pref_label="Apple",
            alt_labels=["  red apple  ", "", "  ", "honeycrisp"],
        )
        assert node.alt_labels == ["red apple", "honeycrisp"]


class TestNodeStatus:
    def test_default_active(self) -> None:
        node = Node(id="apple", type=NodeType.primitive, pref_label="Apple")
        assert node.status == "active"

    def test_pending_review_ok(self) -> None:
        node = Node(
            id="apple",
            type=NodeType.primitive,
            pref_label="Apple",
            status="pending_review",
        )
        assert node.status == "pending_review"

    def test_unknown_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Node(
                id="apple",
                type=NodeType.primitive,
                pref_label="Apple",
                status="archived",
            )


class TestNodeParentInvariants:
    """`parent_id` validation. The "parent must exist" check is enforced at
    persistence time by the FK; here we only enforce that the parent_id, when
    present, looks like a valid node id."""

    def test_no_parent_ok(self) -> None:
        node = Node(id="food", type=NodeType.category, pref_label="Food")
        assert node.parent_id is None

    def test_parent_id_format_validated(self) -> None:
        with pytest.raises(ValidationError):
            Node(
                id="apple",
                type=NodeType.primitive,
                pref_label="Apple",
                parent_id="Fruit Category",
            )

    def test_node_cannot_be_its_own_parent(self) -> None:
        with pytest.raises(ValidationError):
            Node(
                id="apple",
                type=NodeType.primitive,
                pref_label="Apple",
                parent_id="apple",
            )
