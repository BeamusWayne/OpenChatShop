"""Regression tests for the re-audit *security* cluster.

Finding (audit LOW — least privilege in the DEFAULT RBAC):
``_DEFAULT_RBAC`` (the fallback PermissionChecker uses when no ``roles`` are
supplied — e.g. ``SecurityGuard({})`` or a security.yaml without an rbac block)
previously granted the ``agent`` and ``admin`` roles ``tools: ["*"]``. Only the
customer-facing WebSocket actually reaches this checker, and it always passes
``user_role="customer"`` — so the wildcard was latent. But if a non-customer
role ever became reachable under the *default* config it would silently get
unrestricted tool access, including any future/unknown tool.

The fix enumerates an explicit least-privilege tool set for elevated roles in
the *default* while leaving explicit ``["*"]`` grants untouched. These tests pin:

  1. Under the DEFAULT config, ``agent``/``admin`` are NOT granted an arbitrary
     (unknown / privileged) tool — i.e. no silent ``"*"``.  (FAILS before fix.)
  2. ``customer`` keeps its exact existing 8-tool access under the default — the
     contract the production path and the ``SecurityGuard({})`` tests rely on.
  3. An EXPLICIT ``["*"]`` config still grants every tool — wildcard semantics
     survive; only the implicit fallback changed.
"""
from __future__ import annotations

import pytest

from open_chat_shop.core.security import (
    _CUSTOMER_TOOLS,
    PermissionChecker,
    SecurityGuard,
)


def _default_checker() -> PermissionChecker:
    """A PermissionChecker that falls back to _DEFAULT_RBAC.

    Passing an empty dict means ``config.get("roles", ...)`` returns the default
    roles — exactly what ``SecurityGuard({})`` (used across the suite) produces
    via ``config.get("rbac", {})``.
    """
    return PermissionChecker({})


@pytest.mark.unit
class TestDefaultRbacLeastPrivilege:
    """The DEFAULT RBAC must not silently grant elevated roles every tool."""

    # -- (1) elevated roles no longer get a silent "*" under the default ------

    @pytest.mark.parametrize("role", ["agent", "admin"])
    def test_default_elevated_role_denied_unknown_tool(self, role: str) -> None:
        """Before the fix, _DEFAULT_RBAC gave agent/admin ``["*"]`` so ANY tool
        name returned True. After the fix the default is enumerated, so an
        unknown / privileged tool that is not in the customer toolset is denied.
        """
        checker = _default_checker()
        # A tool that is deliberately NOT one of the enumerated customer tools.
        assert "admin_delete_everything" not in _CUSTOMER_TOOLS
        assert checker.has_permission(role, "admin_delete_everything") is False

    @pytest.mark.parametrize("role", ["agent", "admin"])
    def test_default_elevated_role_not_wildcard(self, role: str) -> None:
        """get_allowed_tools must enumerate tools, never return ``["*"]`` under
        the default — i.e. the role's access is explicit and bounded."""
        checker = _default_checker()
        tools = checker.get_allowed_tools(role)
        assert tools != ["*"]
        # It is bounded to the known customer toolset (least privilege over "*").
        assert set(tools) == set(_CUSTOMER_TOOLS)

    @pytest.mark.parametrize("role", ["agent", "admin"])
    def test_default_elevated_role_still_handles_real_tools(self, role: str) -> None:
        """Least privilege must not break the tools that actually exist: an
        agent/admin under the default can still use every real builtin tool."""
        checker = _default_checker()
        for tool in _CUSTOMER_TOOLS:
            assert checker.has_permission(role, tool) is True

    # -- (2) customer contract preserved under the default -------------------

    def test_default_customer_keeps_exact_eight_tools(self) -> None:
        """The production path runs as ``customer`` against the default config;
        its 8-tool allow-list must be unchanged by this fix."""
        checker = _default_checker()
        tools = checker.get_allowed_tools("customer")
        assert len(tools) == 8
        assert set(tools) == set(_CUSTOMER_TOOLS)

    def test_default_customer_denied_admin_tool(self) -> None:
        checker = _default_checker()
        assert checker.has_permission("customer", "admin_dashboard") is False

    def test_securityguard_empty_config_uses_default_customer_grant(self) -> None:
        """End-to-end through SecurityGuard({}) — the exact construction used by
        many suite fixtures — customer access is intact and an unknown tool for
        an elevated role is rejected (no silent wildcard)."""
        guard = SecurityGuard({})
        # customer keeps a granted tool ...
        guard.check_permission("customer", "query_order")  # must not raise
        # ... and an elevated role does NOT get an arbitrary tool by default.
        from open_chat_shop.core.exceptions import SecurityError

        with pytest.raises(SecurityError, match="not permitted"):
            guard.check_permission("admin", "admin_delete_everything")

    # -- (3) explicit wildcard semantics survive -----------------------------

    @pytest.mark.parametrize("role", ["agent", "admin", "anything"])
    def test_explicit_wildcard_config_still_grants_all(self, role: str) -> None:
        """An EXPLICIT ``["*"]`` grant must still mean "all tools". The fix only
        tightened the implicit fallback; it must not change wildcard semantics
        for callers that opt in (the real configs/security.yaml does)."""
        checker = PermissionChecker({"roles": [{"name": role, "tools": ["*"]}]})
        assert checker.has_permission(role, "any_unknown_tool") is True
        assert checker.get_allowed_tools(role) == ["*"]
