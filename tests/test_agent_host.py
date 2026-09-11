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


def test_adapter_host_is_loopback_regardless_of_env(monkeypatch):
    # 어댑터는 인증이 없다. 호스트 방화벽도 꺼져 있으므로 루프백에만 바인딩하고
    # 루프백으로만 호출한다. 오케스트레이터와 어댑터는 항상 같은 머신에 있다.
    monkeypatch.delenv("PORTAL_ENV", raising=False)
    assert agent_host.adapter_host() == "127.0.0.1"
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.adapter_host() == "127.0.0.1"


def test_adapter_host_differs_from_agent_host(monkeypatch):
    # 카드 링크는 브라우저가 여는 주소라 LAN IP여야 한다. 둘을 섞으면 안 된다.
    monkeypatch.setenv("PORTAL_ENV", "deploy")
    assert agent_host.agent_host() != agent_host.adapter_host()
