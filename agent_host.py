"""에이전트 호스트 해석 — 로컬/배포 환경에 따라 하나의 호스트를 돌려준다.

에이전트는 개별 host 필드를 갖지 않는다. 환경마다 호스트가 하나이고 포트만
다르다. 이 값이 여러 곳에 복사되면 링크와 어댑터 호출이 서로 다른 서버를
가리키게 되므로 여기서만 정의한다."""
import os

LOCAL_HOST = "192.168.14.222"
DEPLOY_HOST = "192.168.10.169"

# 어댑터는 /ask에 인증이 없고 배포 서버의 호스트 방화벽도 꺼져 있다. 0.0.0.0에
# 바인딩하면 같은 망의 누구나 LLM 호출을 태울 수 있으므로 루프백으로만 열고
# 루프백으로만 부른다. 오케스트레이터와 어댑터는 로컬·배포 모두 같은 머신에 있다.
ADAPTER_HOST = "127.0.0.1"


def is_deployed() -> bool:
    return os.environ.get("PORTAL_ENV") == "deploy"


def agent_host() -> str:
    return DEPLOY_HOST if is_deployed() else LOCAL_HOST


def adapter_host() -> str:
    """어댑터(api.py)를 부를 주소. 카드 링크용 agent_host()와 의도적으로 다르다 —
    카드는 브라우저가 여는 주소라 LAN IP여야 하고, 어댑터는 밖에서 닿으면 안 된다."""
    return ADAPTER_HOST
