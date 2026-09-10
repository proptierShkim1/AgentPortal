import json

import anthropic
import streamlit as st

from access_control import is_admin
from agent_host import agent_host
from agents_data import AGENTS
from orchestrator_registry import load_registry, enabled_agents, agent_labels
from orchestrator_router import route
from orchestrator_executor import ask_agents, check_health
from orchestrator_synth import synthesize, direct_answer
import orchestrator_sessions as sessions_store


def _run_llm_step(step_desc: str, fn, *args, **kwargs):
    """route()/synthesize()가 던질 수 있는 anthropic/json 예외를 잡아 화면에
    안내를 띄우고 멈춘다. 두 호출부가 같은 함수를 거치므로 예외 처리 순서와
    문구 스타일이 항상 같다 — 한쪽만 고치고 다른 쪽을 빠뜨리는 일이 없다.

    질문은 이미 세션 파일에 사용자 메시지로 저장돼 있으므로, 실패 시 답 없는
    질문만 남지 않도록 오류 문구를 assistant 메시지로 이어 붙인 뒤 멈춘다."""
    try:
        return fn(*args, **kwargs)
    except anthropic.AuthenticationError:
        msg = (f"{step_desc} 중 인증 오류가 발생했습니다. "
               "`.env`에 `ANTHROPIC_API_KEY`를 설정해야 합니다.")
    except anthropic.RateLimitError:
        msg = f"{step_desc} 중 LLM 호출 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
    except anthropic.APIStatusError as e:
        msg = (f"{step_desc} 중 LLM API 오류가 발생했습니다 "
               f"(상태 코드 {e.status_code}). 잠시 후 다시 시도해주세요.")
    except anthropic.APIConnectionError:
        msg = f"{step_desc} 중 LLM 서버에 연결하지 못했습니다. 네트워크 상태를 확인해주세요."
    except json.JSONDecodeError:
        msg = f"{step_desc} 중 LLM 응답을 해석하지 못했습니다 (JSON 형식 오류). 다시 시도해주세요."
    except Exception as e:
        msg = f"{step_desc} 중 알 수 없는 오류가 발생했습니다: {type(e).__name__}: {e}"

    st.error(msg)
    sessions_store.append_message(
        st.session_state.get("_client_ip", ""),
        st.session_state.get("orch_session_id", ""),
        "assistant", msg,
    )
    st.stop()


_client_ip = st.session_state.get("_client_ip", "")
if not is_admin(_client_ip):
    st.error("이 페이지는 관리자만 사용할 수 있습니다.")
    st.stop()

_registry = load_registry()
_agents = enabled_agents(_registry)
_host = agent_host()

# 카드 아이콘·닉네임 재사용 — agents_data.py의 name과 레지스트리의 agent_name을 연결한다.
_labels = agent_labels(_agents, AGENTS)

# 제목과 상태확인 버튼을 한 줄에 둔다. 상태 확인은 가끔 쓰는 기능이라 본문 위에
# 펼침 상자로 자리를 차지하면 대화가 밀린다 — 우측 상단 버튼 + 다이얼로그로 옮긴다.
_head_left, _head_right = st.columns([4, 1], vertical_alignment="center")
with _head_left:
    st.title("🎛️ 오케스트레이터")
with _head_right:
    _open_status = st.button("🩺 에이전트 확인", use_container_width=True)
st.caption("질문 하나로 관련 에이전트들을 골라 부르고, 답변을 하나로 합칩니다.")

if not _agents:
    st.warning(
        "연결된 에이전트가 없습니다. `data/orchestrator_registry.json`에서 "
        "어댑터가 준비된 에이전트의 `enabled`를 true로 바꿔주세요."
    )
    st.stop()


@st.dialog("연결된 에이전트 상태")
def _status_dialog():
    st.caption(f"총 {len(_agents)}개 · {', '.join(_labels.values())}")
    # 헬스체크는 어댑터마다 수 초가 걸릴 수 있어 진행 상황을 보여준다.
    for key, entry in _agents.items():
        with st.spinner(f"{_labels[key]} 확인 중..."):
            health = check_health(entry, _host)
        if health["ok"]:
            counts = ", ".join(f"{k} {v}" for k, v in health["corpus_counts"].items())
            st.success(f"{_labels[key]} · 정상 · 포트 {entry['api_port']}"
                       + (f" · {counts}" if counts else ""))
        else:
            st.error(f"{_labels[key]} · 실패 · 포트 {entry['api_port']} — {health['error']}")


if _open_status:
    _status_dialog()

# --- 대화 세션 (IP별 저장) -------------------------------------------------
# 브라우저를 닫아도 지난 대화를 다시 열어 이어서 물을 수 있어야 한다.
_all_sessions = sessions_store.load_sessions(_client_ip)
if not _all_sessions:
    _all_sessions = [sessions_store.create_session(_client_ip)]

_ids = [s["id"] for s in _all_sessions]
_current_id = st.session_state.get("orch_session_id")
if _current_id not in _ids:
    _current_id = _ids[-1]


def _start_new_conversation():
    # 빈 대화가 이미 열려 있으면 새로 만들지 않는다 — 빈 세션만 쌓인다.
    if _all_sessions[-1].get("messages"):
        st.session_state["orch_session_id"] = sessions_store.create_session(_client_ip)["id"]
    else:
        st.session_state["orch_session_id"] = _all_sessions[-1]["id"]


# 대화가 하나뿐이면 고를 것이 없다 — 드롭다운 대신 버튼만 둔다.
if len(_ids) == 1:
    _picked_id = _ids[0]
    _, _newbtn = st.columns([4, 1], vertical_alignment="center")
    with _newbtn:
        st.button("🆕 새 대화", use_container_width=True, on_click=_start_new_conversation)
else:
    _order = list(reversed(_ids))              # 최신 대화가 위로
    _picker, _newbtn = st.columns([4, 1], vertical_alignment="bottom")
    with _picker:
        _picked_id = st.selectbox(
            f"지난 대화 {len(_ids)}개 · 골라서 이어 물을 수 있습니다",
            options=_order,
            index=_order.index(_current_id),
            format_func=lambda sid: sessions_store.session_label(
                next(s for s in _all_sessions if s["id"] == sid)
            ),
        )
    with _newbtn:
        st.button("🆕 새 대화", use_container_width=True, on_click=_start_new_conversation)

st.session_state["orch_session_id"] = _picked_id

_session = next(s for s in _all_sessions if s["id"] == _picked_id)
_messages = _session.get("messages", [])

def _render_provenance(meta: dict, key: str):
    """어느 에이전트를 왜 불렀고 무엇을 근거로 답했는지 펼쳐 보여준다.

    방금 답한 턴과 지난 대화가 같은 함수를 쓰게 해서, 다시 열었을 때 근거가
    사라지지 않게 한다. meta가 없는 예전 대화도 있으므로 키마다 있는 것만 그린다."""
    picks, citations, failed = meta.get("picks"), meta.get("citations"), meta.get("failed")
    if not (picks or citations or failed):
        return
    with st.expander("이 답변이 만들어진 경로", expanded=False):
        if picks:
            st.markdown("**호출한 에이전트와 이유**")
            for pick in picks:
                st.markdown(f"- {pick['agent']}: {pick['reason']}")
        if failed:
            st.markdown("**응답하지 못한 에이전트**")
            for item in failed:
                st.markdown(f"- {item['agent']}: {item['error']}")
    if citations:
        with st.expander(f"인용 {len(citations)}건", expanded=False):
            for citation in citations:
                label = " ".join(
                    str(citation.get(f, "")) for f in ("law_name", "article")
                ).strip()
                st.markdown(f"- **{label or citation.get('type', '')}** {citation.get('text', '')}")


for _idx, _msg in enumerate(_messages):
    with st.chat_message(_msg["role"]):
        st.markdown(_msg["content"])
        if _msg["role"] == "assistant":
            _render_provenance(_msg.get("meta") or {}, f"hist{_idx}")

_question = st.chat_input("질문을 입력하세요")

if _question:
    # history는 이번 질문을 제외한 이전 턴들이다 — _messages는 이번 질문을 붙이기
    # 전에 읽어둔 것이라 그대로 쓰면 된다. meta는 화면 표시용이라 에이전트에는
    # 보내지 않는다.
    history = [{"role": m["role"], "content": m["content"]} for m in _messages]
    sessions_store.append_message(_client_ip, _picked_id, "user", _question)
    with st.chat_message("user"):
        st.markdown(_question)

    with st.chat_message("assistant"):
        with st.spinner("어느 에이전트가 담당인지 판단하는 중..."):
            decision = _run_llm_step("라우팅", route, _question, _agents)

        if not decision["picks"]:
            st.caption(decision["none_reason"])
            st.caption("연결된 에이전트: " + ", ".join(_labels.values()))
            with st.spinner("담당 에이전트가 없어 직접 답하는 중..."):
                out = _run_llm_step("직접 답변", direct_answer, _question,
                                    labels=_labels)
            st.markdown(out["answer"])
            sessions_store.append_message(
                _client_ip, _picked_id, "assistant", out["answer"],
                meta=sessions_store.answer_meta(out["mode"]),
            )
            st.stop()

        picked = ", ".join(_labels.get(p["agent"], p["agent"]) for p in decision["picks"])
        with st.spinner(f"{picked} 호출 중..."):
            results = ask_agents(decision["picks"], _agents, _question, history, _host)

        with st.spinner("답변을 합치는 중..."):
            out = _run_llm_step("답변 합성", synthesize, _question, results, labels=_labels)

        # 합성기는 전부 실패했을 때 일반 지식으로 답하지 않는다(그 판단은 유지한다).
        # 그래도 답이 필요하므로 근거 없음을 명시한 직접 답변으로 대신한다.
        if out["mode"] == "all_failed":
            with st.spinner("에이전트가 모두 응답하지 못해 직접 답하는 중..."):
                out = _run_llm_step("직접 답변", direct_answer, _question,
                                    failed=out["failed"], labels=_labels)

        st.markdown(out["answer"])

        # 라우팅을 블랙박스로 두지 않는다 — 왜 그 에이전트를 불렀는지 항상 보여준다.
        with st.expander("이 답변이 만들어진 경로", expanded=False):
            st.markdown("**호출한 에이전트와 이유**")
            for pick in decision["picks"]:
                st.markdown(f"- {_labels.get(pick['agent'], pick['agent'])}: {pick['reason']}")

            if out["failed"] and out["mode"] != "direct":
                st.markdown("**응답하지 못한 에이전트**")
                for item in out["failed"]:
                    st.markdown(f"- {_labels.get(item['agent'], item['agent'])}: {item['error']}")

            st.markdown("**각 에이전트의 원본 답변**")
            for result in results:
                if not result.ok:
                    continue
                label = _labels.get(result.agent, result.agent)
                mark = "" if result.sufficient else " · 근거 부족"
                st.markdown(f"**{label}**{mark} · {result.elapsed_ms}ms")
                st.markdown(result.answer)
                if result.grounding:
                    st.caption(f"근거: {result.grounding}")

        if out["citations"]:
            with st.expander(f"인용 {len(out['citations'])}건", expanded=False):
                for citation in out["citations"]:
                    label = " ".join(
                        str(citation.get(f, "")) for f in ("law_name", "article")
                    ).strip()
                    st.markdown(f"- **{label or citation.get('type', '')}** {citation.get('text', '')}")

    sessions_store.append_message(
        _client_ip, _picked_id, "assistant", out["answer"],
        meta=sessions_store.answer_meta(
            out["mode"], picks=decision["picks"], labels=_labels,
            citations=out["citations"],
            failed=out["failed"] if out["mode"] != "direct" else None,
        ),
    )
