import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import layout_config as lc


def test_load_columns_missing_file_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "CONFIG_PATH", tmp_path / "layout_config.json")
    assert lc.load_columns() == 3


def test_load_columns_corrupted_file_returns_default(tmp_path, monkeypatch):
    path = tmp_path / "layout_config.json"
    path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(lc, "CONFIG_PATH", path)
    assert lc.load_columns() == 3


def test_load_columns_valid_file_returns_saved_value(tmp_path, monkeypatch):
    path = tmp_path / "layout_config.json"
    path.write_text(json.dumps({"columns": 5}), encoding="utf-8")
    monkeypatch.setattr(lc, "CONFIG_PATH", path)
    assert lc.load_columns() == 5


def test_load_columns_rejects_out_of_range_value(tmp_path, monkeypatch):
    path = tmp_path / "layout_config.json"
    path.write_text(json.dumps({"columns": 7}), encoding="utf-8")
    monkeypatch.setattr(lc, "CONFIG_PATH", path)
    assert lc.load_columns() == 3


def test_save_columns_creates_data_dir_and_writes_json(tmp_path, monkeypatch):
    path = tmp_path / "nested" / "layout_config.json"
    monkeypatch.setattr(lc, "CONFIG_PATH", path)
    lc.save_columns(4)
    assert json.loads(path.read_text(encoding="utf-8")) == {"columns": 4}
