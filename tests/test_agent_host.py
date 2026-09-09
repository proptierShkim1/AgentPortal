import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import agent_host


def test_is_deployed_false_when_env_unset(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    assert agent_host.is_deployed() is False


def test_is_deployed_true_only_for_exact_deploy_value(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.is_deployed() is True
    monkeypatch.setenv("PORTAL_ENV", "DEPLOY")
    assert agent_host.is_deployed() is False


def test_agent_host_returns_local_when_not_deployed(monkeypatch):
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    assert agent_host.agent_host() == "192.168.14.222"


def test_agent_host_returns_deploy_when_deployed(monkeypatch):
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.agent_host() == "192.168.10.169"
