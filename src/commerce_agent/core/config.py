"""Configuration validation and loading for CommerceAgent.

Pydantic models for YAML config validation and a unified ConfigLoader.
See docs/design/contracts.md section 13 for schema definitions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class ConfigValidationError(Exception):
    """Wraps pydantic ValidationError with a human-readable summary."""

    def __init__(self, path: str, errors: ValidationError) -> None:
        self.path = path
        self.pydantic_errors = errors
        lines: list[str] = [f"Config validation failed for {path}:"]
        for err in errors.errors():
            loc = " -> ".join(str(p) for p in err["loc"])
            lines.append(f"  [{loc}] {err['msg']}")
        super().__init__("\n".join(lines))


# ---------------------------------------------------------------------------
# Provider models
# ---------------------------------------------------------------------------

class ProviderCapabilitiesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calling: bool = True
    streaming: bool = True
    vision: bool = False


class ProviderConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    type: Literal["openai", "anthropic", "ollama", "qwen", "deepseek", "litellm"]
    model: str
    api_key_env: str
    api_base: str | None = None
    max_context_tokens: int = 4096
    capabilities: ProviderCapabilitiesModel | None = None


class CascadeLevelModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    confidence_threshold: float = Field(ge=0.0, le=1.0)
    timeout_seconds: int = 5


class CascadeConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    levels: list[CascadeLevelModel] = Field(min_length=1)
    fallback_provider: str


class ProvidersFileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderConfigModel] = Field(min_length=1)
    cascade: CascadeConfigModel


# ---------------------------------------------------------------------------
# Tool routing models
# ---------------------------------------------------------------------------

class ToolRoutingRuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent_patterns: list[str] = Field(min_length=1)
    scenario: str | None = None
    tools: list[str] = Field(min_length=1)
    priority: int = 0


class ToolRoutingFileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_tools_per_turn: int = Field(default=5, ge=1, le=20)
    rules: list[ToolRoutingRuleModel] = Field(min_length=1)


# ---------------------------------------------------------------------------
# Security models
# ---------------------------------------------------------------------------

class InjectionDetectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_input_length: int = Field(default=2000, ge=100)


class ContentSafetyModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    pii_masking: bool = True


class AuthModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jwt_secret_env: str
    jwt_expiry_seconds: int = Field(default=3600, ge=60)
    api_key_header: str = "X-API-Key"


class RBACRoleModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tools: list[str]


class RBACModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roles: list[RBACRoleModel] = Field(min_length=1)


class SecurityFileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    injection_detection: InjectionDetectionModel
    content_safety: ContentSafetyModel
    auth: AuthModel
    rbac: RBACModel


# ---------------------------------------------------------------------------
# Scenario models
# ---------------------------------------------------------------------------

class ScenarioConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    timeout_seconds: int = Field(default=300, ge=30)
    initial_state: str
    states: list[str] = Field(min_length=2)


class ScenariosFileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenarios: list[ScenarioConfigModel] = Field(min_length=1)


# ---------------------------------------------------------------------------
# ConfigLoader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """Load and validate YAML config files using Pydantic models."""

    @staticmethod
    def _load_yaml(path: str) -> dict:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        if not isinstance(data, dict):
            raise ConfigValidationError(path, ValidationError.from_exception_data(
                title=path,
                line_errors=[{
                    "type": "dict_type",
                    "loc": (),
                    "input": data,
                    "msg": "YAML root must be a mapping",
                }],
            ))
        return data

    @staticmethod
    def _validate(data: dict, model_cls: type[BaseModel], path: str):
        try:
            return model_cls.model_validate(data)
        except ValidationError as exc:
            raise ConfigValidationError(path, exc) from exc

    @classmethod
    def load_providers(cls, path: str) -> ProvidersFileModel:
        data = cls._load_yaml(path)
        return cls._validate(data, ProvidersFileModel, path)

    @classmethod
    def load_tool_routing(cls, path: str) -> ToolRoutingFileModel:
        data = cls._load_yaml(path)
        return cls._validate(data, ToolRoutingFileModel, path)

    @classmethod
    def load_security(cls, path: str) -> SecurityFileModel:
        data = cls._load_yaml(path)
        return cls._validate(data, SecurityFileModel, path)

    @classmethod
    def load_scenarios(cls, path: str) -> ScenariosFileModel:
        data = cls._load_yaml(path)
        return cls._validate(data, ScenariosFileModel, path)

    @classmethod
    def load_all(cls, config_dir: str) -> dict:
        """Load all four config files from *config_dir*.

        Returns a dict with keys: providers, tool_routing, security, scenarios.
        """
        base = Path(config_dir)
        return {
            "providers": cls.load_providers(str(base / "providers.yaml")),
            "tool_routing": cls.load_tool_routing(str(base / "tool_routing.yaml")),
            "security": cls.load_security(str(base / "security.yaml")),
            "scenarios": cls.load_scenarios(str(base / "scenarios.yaml")),
        }
