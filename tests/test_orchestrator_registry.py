import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_registry as reg


def _entry(**over):
    base = {
        "agent_name": "LexAgent",
        "role": "개인정보 법령 해석",
        "domain": ["개인정보보호법"],
        "when_to_use": "법 조항을 물을 때",
        "when_not_to_use": "처리방침 검토 → policy로",
        "api_port": 9501,
        "timeout_sec": 60,
        "enabled": True,
    }
    base.update(over)
    return base


def test_load_registry_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(reg, "CONFIG_PATH", tmp_path / "orchestrator_registry.json")
    assert reg.load_registry() == {}


def test_load_registry_corrupted_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "orchestrator_registry.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    assert reg.load_registry() == {}


def test_load_registry_valid_file_returns_parsed_dict(tmp_path, monkeypatch):
    path = tmp_path / "orchestrator_registry.json"
    data = {"lex": _entry()}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    assert reg.load_registry() == data


def test_save_registry_creates_data_dir_and_writes_json(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "orchestrator_registry.json"
    monkeypatch.setattr(reg, "CONFIG_PATH", path)
    cfg = {"lex": _entry()}
    reg.save_registry(cfg)
    assert json.loads(path.read_text(encoding="utf-8")) == cfg


def test_enabled_agents_keeps_only_enabled_entries():
    registry = {"lex": _entry(), "policy": _entry(agent_name="PolicyAgent", enabled=False)}
    assert list(reg.enabled_agents(registry)) == ["lex"]


def test_enabled_agents_drops_entry_missing_role():
    registry = {"lex": _entry(role="")}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_drops_entry_missing_when_to_use():
    registry = {"lex": _entry(when_to_use="")}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_drops_entry_missing_api_port():
    registry = {"lex": _entry(api_port=None)}
    assert reg.enabled_agents(registry) == {}


def test_enabled_agents_ignores_non_dict_entry():
    registry = {"lex": "이건 dict가 아니다"}
    assert reg.enabled_agents(registry) == {}


def test_agent_url_builds_ask_endpoint_by_default():
    assert reg.agent_url(_entry(), "192.168.14.222") == "http://192.168.14.222:9501/ask"


def test_agent_url_accepts_explicit_path():
    url = reg.agent_url(_entry(), "192.168.10.169", path="/health")
    assert url == "http://192.168.10.169:9501/health"


def test_agent_labels_matches_meta_by_agent_name():
    agents = {"lex": _entry(agent_name="LexAgent")}
    meta_agents = [{"name": "LexAgent", "nickname": "렉스", "icon": "⚖️"}]
    assert reg.agent_labels(agents, meta_agents) == {"lex": "⚖️ 렉스"}


def test_agent_labels_falls_back_to_raw_agent_name_when_no_meta_match():
    agents = {"lex": _entry(agent_name="UnknownAgent")}
    assert reg.agent_labels(agents, []) == {"lex": "UnknownAgent"}


def test_agent_labels_strips_leading_space_when_icon_missing():
    agents = {"lex": _entry(agent_name="LexAgent")}
    meta_agents = [{"name": "LexAgent", "nickname": "렉스"}]
    assert reg.agent_labels(agents, meta_agents) == {"lex": "렉스"}
