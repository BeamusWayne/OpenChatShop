"""Unit tests for main.py's RBAC config construction.

Why this matters: main.py reads a custom ``security.yaml`` and must hand the
RBAC roles to ``PermissionChecker`` in the exact shape it parses. The audit
found main built ``{role.name: {"tools": ...}}`` while ``PermissionChecker``
expects ``{"roles": [{"name": .., "tools": ..}]}``. The mismatch made the
checker silently fall back to ``_DEFAULT_RBAC`` — a custom security.yaml was
ignored, so a "customer-only-query_order" policy would not actually restrict
anything. These tests pin the contract: a custom role built by main must take
effect (no silent fallback to defaults).
"""
from __future__ import annotations

import os

import pytest

# main.py builds the app at import time and aborts (SystemExit) unless some
# auth mode is configured. DEV_MODE skips that check so we can import the module
# and exercise its pure RBAC-building helper without standing up the server.
os.environ.setdefault("DEV_MODE", "true")

import main

from open_chat_shop.core.config import RBACModel, RBACRoleModel
from open_chat_shop.core.security import PermissionChecker


def _custom_sec_rbac(role_name: str, tools: list[str]) -> RBACModel:
    """Build an RBACModel as main would receive it from parsed security.yaml."""
    return RBACModel(roles=[RBACRoleModel(name=role_name, tools=tools)])


@pytest.mark.unit
class TestMainBuildsRbacForPermissionChecker:
    """main's RBAC config must be parsable by PermissionChecker so custom roles
    actually take effect instead of silently reverting to the built-in default."""

    def test_custom_role_grant_takes_effect(self) -> None:
        """A custom 'customer' role granted only ['query_order'] must allow that
        tool — proving the custom config reached PermissionChecker (not the
        default RBAC, where 'customer' has many more tools, masking the bug)."""
        rbac_config = main._build_rbac_config(
            _custom_sec_rbac("customer", ["query_order"])
        )
        checker = PermissionChecker(rbac_config["rbac"])

        assert checker.has_permission("customer", "query_order") is True

    def test_custom_role_denies_ungranted_tool(self) -> None:
        """The same 'customer' role must be DENIED a tool it was not granted.

        This is the load-bearing assertion: under the old buggy build, the
        config silently fell back to _DEFAULT_RBAC, where 'customer' DOES have
        'cancel_order' — so this would wrongly pass as True. It only stays False
        when main's custom config genuinely reaches the checker.
        """
        rbac_config = main._build_rbac_config(
            _custom_sec_rbac("customer", ["query_order"])
        )
        checker = PermissionChecker(rbac_config["rbac"])

        assert checker.has_permission("customer", "cancel_order") is False

    def test_rbac_config_has_roles_key_with_role_dicts(self) -> None:
        """The built rbac payload must use the 'roles' list-of-dicts shape that
        PermissionChecker.__init__ parses (the shape that was wrong before)."""
        rbac_config = main._build_rbac_config(
            _custom_sec_rbac("customer", ["query_order"])
        )

        rbac = rbac_config["rbac"]
        assert "roles" in rbac
        assert rbac["roles"] == [{"name": "customer", "tools": ["query_order"]}]

    def test_wildcard_role_still_grants_all(self) -> None:
        """A role with ['*'] built by main must grant any tool via the checker,
        confirming the wildcard semantics survive the construction."""
        rbac_config = main._build_rbac_config(_custom_sec_rbac("admin", ["*"]))
        checker = PermissionChecker(rbac_config["rbac"])

        assert checker.has_permission("admin", "query_order") is True
        assert checker.has_permission("admin", "create_refund") is True
