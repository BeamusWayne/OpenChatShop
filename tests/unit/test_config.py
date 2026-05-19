"""Tests for config validation and loading (feat-022)."""
from __future__ import annotations

import os
import textwrap

import pytest

from open_chat_shop.core.config import (
    CascadeConfigModel,
    CascadeLevelModel,
    ConfigLoader,
    ConfigValidationError,
    ProviderConfigModel,
    ProvidersFileModel,
    ScenarioConfigModel,
    ScenariosFileModel,
    SecurityFileModel,
    ToolRoutingFileModel,
)


# ---------------------------------------------------------------------------
# Fixtures: sample YAML content as strings
# ---------------------------------------------------------------------------

PROVIDERS_YAML = textwrap.dedent("""\
    providers:
      - name: openai
        type: openai
        model: gpt-4o-mini
        api_key_env: OPENAI_API_KEY
        max_context_tokens: 128000
        capabilities:
          tool_calling: true
          streaming: true
          vision: true
      - name: ollama
        type: ollama
        model: llama3
        api_key_env: OLLAMA_NOT_NEEDED
        api_base: http://localhost:11434
    cascade:
      levels:
        - provider: openai
          confidence_threshold: 0.7
          timeout_seconds: 10
      fallback_provider: openai
""")

TOOL_ROUTING_YAML = textwrap.dedent("""\
    max_tools_per_turn: 5
    rules:
      - intent_patterns: ["query_order", "query_*"]
        tools: ["query_order", "query_logistics"]
        priority: 10
      - intent_patterns: ["*"]
        tools: ["handoff_to_human"]
        priority: 0
""")

SECURITY_YAML = textwrap.dedent("""\
    injection_detection:
      enabled: true
      max_input_length: 2000
    content_safety:
      enabled: true
      pii_masking: true
    auth:
      jwt_secret_env: JWT_SECRET_KEY
      jwt_expiry_seconds: 3600
      api_key_header: X-API-Key
    rbac:
      roles:
        - name: customer
          tools: ["query_order", "search_product"]
        - name: admin
          tools: ["*"]
""")

SCENARIOS_YAML = textwrap.dedent("""\
    scenarios:
      - name: refund
        timeout_seconds: 300
        initial_state: initiated
        states: [initiated, confirmed, processing, completed, cancelled]
      - name: order_inquiry
        timeout_seconds: 180
        initial_state: idle
        states: [idle, order_found, detail_shown, completed]
""")


def _write(tmp_path, name: str, content: str) -> str:
    """Write a YAML file and return its absolute path."""
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


@pytest.fixture()
def config_dir(tmp_path):
    """Create a temp directory with all four valid YAML files."""
    _write(tmp_path, "providers.yaml", PROVIDERS_YAML)
    _write(tmp_path, "tool_routing.yaml", TOOL_ROUTING_YAML)
    _write(tmp_path, "security.yaml", SECURITY_YAML)
    _write(tmp_path, "scenarios.yaml", SCENARIOS_YAML)
    return str(tmp_path)


# ===================================================================
# Providers
# ===================================================================

@pytest.mark.unit
def test_load_providers_valid(config_dir):
    result = ConfigLoader.load_providers(os.path.join(config_dir, "providers.yaml"))
    assert isinstance(result, ProvidersFileModel)
    assert len(result.providers) == 2
    assert result.providers[0].name == "openai"
    assert result.providers[0].type == "openai"
    assert result.providers[0].capabilities is not None
    assert result.providers[0].capabilities.vision is True
    assert result.providers[1].api_base == "http://localhost:11434"
    assert result.cascade.fallback_provider == "openai"
    assert result.cascade.levels[0].confidence_threshold == 0.7


@pytest.mark.unit
def test_load_providers_missing_field(tmp_path):
    bad_yaml = textwrap.dedent("""\
        providers:
          - name: openai
            type: openai
        cascade:
          levels:
            - provider: openai
              confidence_threshold: 0.5
          fallback_provider: openai
    """)
    path = _write(tmp_path, "providers.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="model"):
        ConfigLoader.load_providers(path)


@pytest.mark.unit
def test_load_providers_empty_list(tmp_path):
    bad_yaml = textwrap.dedent("""\
        providers: []
        cascade:
          levels:
            - provider: openai
              confidence_threshold: 0.5
          fallback_provider: openai
    """)
    path = _write(tmp_path, "providers.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="providers"):
        ConfigLoader.load_providers(path)


@pytest.mark.unit
def test_load_providers_unknown_field(tmp_path):
    bad_yaml = textwrap.dedent("""\
        providers:
          - name: openai
            type: openai
            model: gpt-4o-mini
            api_key_env: KEY
            unknown_field: oops
        cascade:
          levels:
            - provider: openai
              confidence_threshold: 0.5
          fallback_provider: openai
    """)
    path = _write(tmp_path, "providers.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError):
        ConfigLoader.load_providers(path)


@pytest.mark.unit
def test_load_providers_bad_type_literal(tmp_path):
    bad_yaml = textwrap.dedent("""\
        providers:
          - name: bad
            type: nonexistent_provider
            model: x
            api_key_env: KEY
        cascade:
          levels:
            - provider: bad
              confidence_threshold: 0.5
          fallback_provider: bad
    """)
    path = _write(tmp_path, "providers.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="type"):
        ConfigLoader.load_providers(path)


# ===================================================================
# Tool routing
# ===================================================================

@pytest.mark.unit
def test_load_tool_routing_valid(config_dir):
    result = ConfigLoader.load_tool_routing(
        os.path.join(config_dir, "tool_routing.yaml"),
    )
    assert isinstance(result, ToolRoutingFileModel)
    assert result.max_tools_per_turn == 5
    assert len(result.rules) == 2
    assert result.rules[0].priority == 10


@pytest.mark.unit
def test_load_tool_routing_missing_field(tmp_path):
    bad_yaml = textwrap.dedent("""\
        max_tools_per_turn: 5
        rules:
          - intent_patterns: ["query_order"]
    """)
    path = _write(tmp_path, "tool_routing.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="tools"):
        ConfigLoader.load_tool_routing(path)


@pytest.mark.unit
def test_max_tools_per_turn_boundary_valid(tmp_path):
    for val in (1, 20):
        yaml_content = (
            f"max_tools_per_turn: {val}\n"
            "rules:\n  - intent_patterns: ['x']\n    tools: ['y']\n"
        )
        path = _write(tmp_path, f"tr_{val}.yaml", yaml_content)
        result = ConfigLoader.load_tool_routing(path)
        assert result.max_tools_per_turn == val


@pytest.mark.unit
def test_max_tools_per_turn_boundary_invalid(tmp_path):
    for val in (0, 21):
        yaml_content = (
            f"max_tools_per_turn: {val}\n"
            "rules:\n  - intent_patterns: ['x']\n    tools: ['y']\n"
        )
        path = _write(tmp_path, f"tr_bad_{val}.yaml", yaml_content)
        with pytest.raises(ConfigValidationError):
            ConfigLoader.load_tool_routing(path)


# ===================================================================
# Security
# ===================================================================

@pytest.mark.unit
def test_load_security_valid(config_dir):
    result = ConfigLoader.load_security(os.path.join(config_dir, "security.yaml"))
    assert isinstance(result, SecurityFileModel)
    assert result.injection_detection.max_input_length == 2000
    assert result.content_safety.pii_masking is True
    assert result.auth.jwt_secret_env == "JWT_SECRET_KEY"
    assert len(result.rbac.roles) == 2
    assert result.rbac.roles[1].name == "admin"


@pytest.mark.unit
def test_load_security_missing_field(tmp_path):
    bad_yaml = textwrap.dedent("""\
        injection_detection:
          enabled: true
          max_input_length: 2000
        content_safety:
          enabled: true
          pii_masking: true
        auth:
          jwt_expiry_seconds: 3600
        rbac:
          roles:
            - name: admin
              tools: ["*"]
    """)
    path = _write(tmp_path, "security.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="jwt_secret_env"):
        ConfigLoader.load_security(path)


@pytest.mark.unit
def test_security_max_input_length_too_small(tmp_path):
    bad_yaml = textwrap.dedent("""\
        injection_detection:
          enabled: true
          max_input_length: 50
        content_safety:
          enabled: true
          pii_masking: true
        auth:
          jwt_secret_env: KEY
        rbac:
          roles:
            - name: admin
              tools: ["*"]
    """)
    path = _write(tmp_path, "security.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError):
        ConfigLoader.load_security(path)


# ===================================================================
# Scenarios
# ===================================================================

@pytest.mark.unit
def test_load_scenarios_valid(config_dir):
    result = ConfigLoader.load_scenarios(os.path.join(config_dir, "scenarios.yaml"))
    assert isinstance(result, ScenariosFileModel)
    assert len(result.scenarios) == 2
    assert result.scenarios[0].name == "refund"
    assert result.scenarios[0].states == [
        "initiated", "confirmed", "processing", "completed", "cancelled",
    ]


@pytest.mark.unit
def test_load_scenarios_empty_list(tmp_path):
    path = _write(tmp_path, "scenarios.yaml", "scenarios: []\n")
    with pytest.raises(ConfigValidationError, match="scenarios"):
        ConfigLoader.load_scenarios(path)


@pytest.mark.unit
def test_scenario_states_min_length_2(tmp_path):
    bad_yaml = textwrap.dedent("""\
        scenarios:
          - name: short
            initial_state: idle
            states: [idle]
    """)
    path = _write(tmp_path, "scenarios.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError, match="states"):
        ConfigLoader.load_scenarios(path)


# ===================================================================
# Cascade confidence_threshold boundary
# ===================================================================

@pytest.mark.unit
def test_confidence_threshold_boundary_valid(tmp_path):
    for val in (0.0, 1.0):
        yaml_content = textwrap.dedent(f"""\
            providers:
              - name: openai
                type: openai
                model: gpt-4o-mini
                api_key_env: KEY
            cascade:
              levels:
                - provider: openai
                  confidence_threshold: {val}
              fallback_provider: openai
        """)
        path = _write(tmp_path, f"prov_ct_{val}.yaml", yaml_content)
        result = ConfigLoader.load_providers(path)
        assert result.cascade.levels[0].confidence_threshold == val


@pytest.mark.unit
def test_confidence_threshold_boundary_invalid(tmp_path):
    for val in (-0.1, 1.1):
        yaml_content = textwrap.dedent(f"""\
            providers:
              - name: openai
                type: openai
                model: gpt-4o-mini
                api_key_env: KEY
            cascade:
              levels:
                - provider: openai
                  confidence_threshold: {val}
              fallback_provider: openai
        """)
        path = _write(tmp_path, f"prov_bad_{val}.yaml", yaml_content)
        with pytest.raises(ConfigValidationError):
            ConfigLoader.load_providers(path)


# ===================================================================
# load_all
# ===================================================================

@pytest.mark.unit
def test_load_all_valid(config_dir):
    result = ConfigLoader.load_all(config_dir)
    assert set(result.keys()) == {"providers", "tool_routing", "security", "scenarios"}
    assert isinstance(result["providers"], ProvidersFileModel)
    assert isinstance(result["tool_routing"], ToolRoutingFileModel)
    assert isinstance(result["security"], SecurityFileModel)
    assert isinstance(result["scenarios"], ScenariosFileModel)


@pytest.mark.unit
def test_load_all_missing_file(tmp_path):
    empty_dir = str(tmp_path / "empty")
    os.makedirs(empty_dir, exist_ok=True)
    with pytest.raises(FileNotFoundError):
        ConfigLoader.load_all(empty_dir)


# ===================================================================
# Extra fields rejected (extra="forbid")
# ===================================================================

@pytest.mark.unit
def test_security_unknown_field_rejected(tmp_path):
    bad_yaml = textwrap.dedent("""\
        injection_detection:
          enabled: true
          max_input_length: 2000
          bogus: true
        content_safety:
          enabled: true
          pii_masking: true
        auth:
          jwt_secret_env: KEY
        rbac:
          roles:
            - name: admin
              tools: ["*"]
    """)
    path = _write(tmp_path, "security.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError):
        ConfigLoader.load_security(path)


@pytest.mark.unit
def test_scenario_unknown_field_rejected(tmp_path):
    bad_yaml = textwrap.dedent("""\
        scenarios:
          - name: refund
            initial_state: idle
            states: [idle, done]
            surprise_field: 42
    """)
    path = _write(tmp_path, "scenarios.yaml", bad_yaml)
    with pytest.raises(ConfigValidationError):
        ConfigLoader.load_scenarios(path)


# ===================================================================
# Non-dict root YAML
# ===================================================================

@pytest.mark.unit
def test_non_dict_root_yaml(tmp_path):
    path = _write(tmp_path, "bad.yaml", "just a string")
    with pytest.raises(ConfigValidationError, match="dictionary|mapping|valid"):
        ConfigLoader.load_providers(path)
