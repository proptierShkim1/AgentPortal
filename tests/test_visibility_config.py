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


def test_sort_by_order_reorders_by_explicit_order_value():
    agents = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    visibility = {"A": {"order": 2}, "B": {"order": 0}, "C": {"order": 1}}
    result = vc.sort_by_order(agents, visibility)
    assert [a["name"] for a in result] == ["B", "C", "A"]


def test_sort_by_order_defaults_missing_agent_to_original_position():
    agents = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    visibility = {"A": {"order": 5}}
    result = vc.sort_by_order(agents, visibility)
    assert [a["name"] for a in result] == ["B", "C", "A"]


def test_sort_by_order_is_stable_for_duplicate_order_values():
    agents = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
    visibility = {"A": {"order": 0}, "B": {"order": 0}, "C": {"order": 0}}
    result = vc.sort_by_order(agents, visibility)
    assert [a["name"] for a in result] == ["A", "B", "C"]


# ── move_agent — 설정 화면의 ▲▼ 순서 이동 ────────────────────────────

_ABC = [{"name": "A"}, {"name": "B"}, {"name": "C"}]


def _ordered(visibility):
    return [a["name"] for a in vc.sort_by_order(_ABC, visibility)]


def _flat(order_by_name):
    return {n: {"visible_local": True, "visible_deploy": True, "order": o}
            for n, o in order_by_name.items()}


def test_move_agent_down_swaps_with_next():
    out = vc.move_agent(_flat({"A": 0, "B": 1, "C": 2}), _ABC, "A", 1)
    assert _ordered(out) == ["B", "A", "C"]


def test_move_agent_up_swaps_with_previous():
    out = vc.move_agent(_flat({"A": 0, "B": 1, "C": 2}), _ABC, "C", -1)
    assert _ordered(out) == ["A", "C", "B"]


def test_move_agent_renumbers_orders_from_zero():
    out = vc.move_agent(_flat({"A": 0, "B": 1, "C": 2}), _ABC, "A", 1)
    assert [out[n]["order"] for n in ("B", "A", "C")] == [0, 1, 2]


def test_move_agent_up_at_top_returns_input_unchanged():
    visibility = _flat({"A": 0, "B": 1, "C": 2})
    assert vc.move_agent(visibility, _ABC, "A", -1) == visibility


def test_move_agent_down_at_bottom_returns_input_unchanged():
    visibility = _flat({"A": 0, "B": 1, "C": 2})
    assert vc.move_agent(visibility, _ABC, "C", 1) == visibility


def test_move_agent_unknown_name_returns_input_unchanged():
    visibility = _flat({"A": 0, "B": 1, "C": 2})
    assert vc.move_agent(visibility, _ABC, "없는에이전트", 1) == visibility


def test_move_agent_normalizes_duplicate_orders():
    """중복 order는 한 번의 이동으로 0..n-1로 정리된다."""
    out = vc.move_agent(_flat({"A": 0, "B": 0, "C": 0}), _ABC, "A", 1)
    assert sorted(out[n]["order"] for n in ("A", "B", "C")) == [0, 1, 2]


def test_move_agent_gives_missing_entries_an_order_and_defaults():
    out = vc.move_agent({"A": {"order": 0}}, _ABC, "A", 1)
    assert sorted(out[n]["order"] for n in ("A", "B", "C")) == [0, 1, 2]
    assert out["B"]["visible_local"] is True
    assert out["B"]["visible_deploy"] is True


def test_move_agent_preserves_visibility_flags():
    visibility = {
        "A": {"visible_local": False, "visible_deploy": True, "order": 0},
        "B": {"visible_local": True, "visible_deploy": False, "order": 1},
        "C": {"visible_local": True, "visible_deploy": True, "order": 2},
    }
    out = vc.move_agent(visibility, _ABC, "A", 1)
    assert out["A"]["visible_local"] is False
    assert out["A"]["visible_deploy"] is True
    assert out["B"]["visible_deploy"] is False


def test_move_agent_does_not_mutate_input():
    visibility = _flat({"A": 0, "B": 1, "C": 2})
    before = {n: dict(e) for n, e in visibility.items()}
    vc.move_agent(visibility, _ABC, "A", 1)
    assert visibility == before
