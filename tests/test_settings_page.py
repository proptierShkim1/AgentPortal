"""설정 페이지의 배포 환경 가드 — 헤드리스 렌더 테스트.

배포 서버(`PORTAL_ENV=deploy`)에서는 "서버 배포"와 "어댑터 배포"가 보이면 안 된다.
`.env`가 배포 때 함께 올라가 `DEPLOY_HOST`가 서버에도 있으므로, 가드가 없으면
버튼이 비활성조차 아니고 실제로 눌린다 — 누르면 자기 자신에게 SSH 재배포·재시작이
걸려 돌아가던 앱이 끊긴다.

카드 노출 설정은 배포 서버에서도 보이되 편집은 막는다. 배포가 로컬의
visibility_config.json으로 덮어쓰므로 서버에서 고쳐봐야 다음 배포에 지워진다.

access_control.CONFIG_PATH / visibility_config.CONFIG_PATH를 tmp_path로 갈아끼워
이 리포에 커밋된 실제 설정과 무관하게 결정적으로 돌게 한다."""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from streamlit.testing.v1 import AppTest

import access_control
import visibility_config

PAGE_PATH = "pages/설정.py"
REPO = Path(__file__).parent.parent

DEPLOY_ONLY_SECTIONS = ("🚀 서버 배포", "🔌 어댑터 배포")
VISIBILITY_SECTION = "🖥️ 카드 노출 설정"


def _isolate(tmp_path, monkeypatch):
    """실제 설정 파일을 건드리지 않게 하고, admin 게이트는 부트스트랩으로 통과시킨다."""
    monkeypatch.setattr(access_control, "CONFIG_PATH", tmp_path / "access_config.json")
    vis = tmp_path / "visibility_config.json"
    shutil.copy(REPO / "data" / "visibility_config.json", vis)
    monkeypatch.setattr(visibility_config, "CONFIG_PATH", vis)
    return vis


def _run(monkeypatch, deployed: bool):
    if deployed:
        monkeypatch.setenv("PORTAL_ENV", "deploy")
    else:
        monkeypatch.delenv("PORTAL_ENV", raising=False)
    at = AppTest.from_file(PAGE_PATH, default_timeout=60)
    at.session_state["_client_ip"] = "1.2.3.4"
    at.run()
    return at


def _subheaders(at):
    return [s.value for s in at.subheader]


def test_local_shows_deploy_sections(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=False)
    assert not at.exception
    headings = _subheaders(at)
    for section in DEPLOY_ONLY_SECTIONS:
        assert section in headings


def test_deployed_hides_deploy_sections(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=True)
    assert not at.exception
    headings = _subheaders(at)
    for section in DEPLOY_ONLY_SECTIONS:
        assert section not in headings


def test_deployed_still_shows_visibility_section(tmp_path, monkeypatch):
    """두 섹션을 숨긴 뒤에도 페이지가 빈 화면이 되면 안 된다."""
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=True)
    assert VISIBILITY_SECTION in _subheaders(at)


def test_deployed_disables_visibility_controls(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=True)
    order_buttons = [b for b in at.button if b.key and b.key.startswith(("vis_up_", "vis_down_"))]
    vis_checkboxes = [c for c in at.checkbox if c.key and c.key.startswith(("vis_local_", "vis_deploy_"))]
    assert order_buttons and vis_checkboxes
    assert all(b.disabled for b in order_buttons)
    assert all(c.disabled for c in vis_checkboxes)


def test_local_leaves_visibility_controls_enabled(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=False)
    order_buttons = [b for b in at.button if b.key and b.key.startswith(("vis_up_", "vis_down_"))]
    vis_checkboxes = [c for c in at.checkbox if c.key and c.key.startswith(("vis_local_", "vis_deploy_"))]
    assert order_buttons and vis_checkboxes
    # 첫 행의 ▲와 마지막 행의 ▼는 경계라 로컬에서도 비활성이다 — 전부 켜져
    # 있는지가 아니라 "일부라도 눌리는지"를 본다.
    assert any(not b.disabled for b in order_buttons)
    assert not any(c.disabled for c in vis_checkboxes)


def test_deployed_does_not_write_visibility_file(tmp_path, monkeypatch):
    """배포 서버에서는 렌더만으로도 설정 파일을 건드리지 않아야 한다."""
    vis = _isolate(tmp_path, monkeypatch)
    before = vis.read_text(encoding="utf-8")
    _run(monkeypatch, deployed=True)
    assert vis.read_text(encoding="utf-8") == before


def test_deployed_explains_where_to_deploy(tmp_path, monkeypatch):
    """섹션이 이유 없이 사라진 것처럼 보이면 안 된다."""
    _isolate(tmp_path, monkeypatch)
    at = _run(monkeypatch, deployed=True)
    said = " ".join(i.value for i in at.info) + " ".join(c.value for c in at.caption)
    assert "로컬" in said
