"""Tests for Docker and deployment configuration (feat-037)."""
from __future__ import annotations

import os

import pytest


@pytest.mark.unit
def test_dockerfile_exists():
    assert os.path.isfile("Dockerfile")


@pytest.mark.unit
def test_dockerfile_uses_python311():
    with open("Dockerfile") as f:
        content = f.read()
    assert "python:3.11" in content or "python:3" in content


@pytest.mark.unit
def test_dockerfile_exposes_8000():
    with open("Dockerfile") as f:
        content = f.read()
    assert "EXPOSE 8000" in content


@pytest.mark.unit
def test_dockerfile_copies_main():
    with open("Dockerfile") as f:
        content = f.read()
    assert "main.py" in content


@pytest.mark.unit
def test_docker_compose_exists():
    assert os.path.isfile("docker-compose.yml")


@pytest.mark.unit
def test_docker_compose_has_app_service():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert "agent-api" in content or "app" in content
    assert "8000" in content


@pytest.mark.unit
def test_docker_compose_has_postgres():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert "postgres" in content.lower()


@pytest.mark.unit
def test_docker_compose_has_redis():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert "redis" in content.lower()


@pytest.mark.unit
def test_docker_compose_healthchecks():
    with open("docker-compose.yml") as f:
        content = f.read()
    assert "healthcheck" in content


@pytest.mark.unit
def test_run_sh_exists():
    assert os.path.isfile("run.sh")


@pytest.mark.unit
def test_run_sh_is_executable():
    assert os.access("run.sh", os.X_OK)


@pytest.mark.unit
def test_run_sh_references_main():
    with open("run.sh") as f:
        content = f.read()
    assert "main.py" in content or "main" in content


# Production Docker Compose (feat-041)


@pytest.mark.unit
def test_prod_compose_exists():
    assert os.path.isfile("docker-compose.prod.yml")


@pytest.mark.unit
def test_prod_compose_requires_jwt_secret():
    with open("docker-compose.prod.yml") as f:
        content = f.read()
    assert "JWT_SECRET_KEY" in content


@pytest.mark.unit
def test_prod_compose_disables_grafana_anonymous():
    with open("docker-compose.prod.yml") as f:
        content = f.read()
    assert "GF_AUTH_ANONYMOUS_ENABLED=false" in content


@pytest.mark.unit
def test_prod_compose_no_default_passwords():
    """Production compose must not contain default weak passwords."""
    with open("docker-compose.prod.yml") as f:
        content = f.read()
    assert "commerce" not in content, "Default password 'commerce' found in prod compose"


@pytest.mark.unit
def test_dockerfile_has_frontend_build_stage():
    with open("Dockerfile") as f:
        content = f.read()
    assert "frontend-builder" in content
    assert "npm run build" in content


# Gunicorn configuration (feat-043)


@pytest.mark.unit
def test_gunicorn_conf_exists():
    assert os.path.isfile("gunicorn.conf.py")


@pytest.mark.unit
def test_gunicorn_conf_uses_uvicorn_worker():
    with open("gunicorn.conf.py") as f:
        content = f.read()
    assert "uvicorn.workers.UvicornWorker" in content


@pytest.mark.unit
def test_gunicorn_conf_imports_multiprocessing():
    with open("gunicorn.conf.py") as f:
        content = f.read()
    assert "multiprocessing" in content


@pytest.mark.unit
def test_dockerfile_uses_gunicorn():
    with open("Dockerfile") as f:
        content = f.read()
    assert "gunicorn" in content
