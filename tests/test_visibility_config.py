import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import visibility_config as vc


def test_load_visibility_missing_file_returns_empty_dict(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "CONFIG_PATH", tmp_path / "visibility_config.json")
    assert vc.load_visibility() == {}


def test_load_visibility_corrupted_file_returns_empty_dict(tmp_path, monkeypatch):
    path = tmp_path / "visibility_config.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    assert vc.load_visibility() == {}


def test_load_visibility_valid_file_returns_parsed_dict(tmp_path, monkeypatch):
    path = tmp_path / "visibility_config.json"
    data = {"LexAgent": {"visible_local": True, "visible_deploy": False}}
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    assert vc.load_visibility() == data


def test_save_visibility_creates_data_dir_and_writes_json(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "visibility_config.json"
    monkeypatch.setattr(vc, "CONFIG_PATH", path)
    cfg = {"GosiAgent": {"visible_local": True, "visible_deploy": True}}
    vc.save_visibility(cfg)
    assert json.loads(path.read_text(encoding="utf-8")) == cfg


def test_visible_agents_filters_by_local_key_when_not_deployed():
    agents = [{"name": "A"}, {"name": "B"}]
    visibility = {"A": {"visible_local": True, "visible_deploy": False},
                  "B": {"visible_local": False, "visible_deploy": True}}
    result = vc.visible_agents(agents, visibility, is_deployed=False)
    assert [a["name"] for a in result] == ["A"]


def test_visible_agents_filters_by_deploy_key_when_deployed():
    agents = [{"name": "A"}, {"name": "B"}]
    visibility = {"A": {"visible_local": True, "visible_deploy": False},
                  "B": {"visible_local": False, "visible_deploy": True}}
    result = vc.visible_agents(agents, visibility, is_deployed=True)
    assert [a["name"] for a in result] == ["B"]


def test_visible_agents_defaults_to_visible_when_missing_from_config():
    agents = [{"name": "NewAgent"}]
    result = vc.visible_agents(agents, {}, is_deployed=False)
    assert [a["name"] for a in result] == ["NewAgent"]
