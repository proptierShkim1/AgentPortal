"""에이전트 호스트 해석 — 로컬/배포 환경에 따라 하나의 호스트를 돌려준다.

에이전트는 개별 host 필드를 갖지 않는다. 환경마다 호스트가 하나이고 포트만
다르다. 이 값이 여러 곳에 복사되면 링크와 어댑터 호출이 서로 다른 서버를
가리키게 되므로 여기서만 정의한다."""
import os

LOCAL_HOST = "192.168.14.222"
DEPLOY_HOST = "192.168.10.169"


def is_deployed() -> bool:
    return os.environ.get("PORTAL_ENV") == "deploy"


def agent_host() -> str:
    return DEPLOY_HOST if is_deployed() else LOCAL_HOST
