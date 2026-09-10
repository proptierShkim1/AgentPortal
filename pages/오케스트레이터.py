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


def _run_llm_step(step_desc: str, fn, *args, **kwargs):
    """route()/synthesize()가 던질 수 있는 anthropic/json 예외를 잡아 화면에
    안내를 띄우고 멈춘다. 두 호출부가 같은 함수를 거치므로 예외 처리 순서와
    문구 스타일이 항상 같다 — 한쪽만 고치고 다른 쪽을 빠뜨리는 일이 없다.

    질문은 이미 st.session_state["orch_messages"]에 사용자 메시지로 들어가
    있으므로, 실패 시 답 없는 질문만 남기지 않도록 오류 문구를 assistant
    메시지로 이어 붙인 뒤 멈춘다."""
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
    st.session_state["orch_messages"].append({"role": "assistant", "content": msg})
    st.stop()


_client_ip = st.session_state.get("_client_ip", "")
if not is_admin(_client_ip):
    st.error("이 페이지는 관리자만 사용할 수 있습니다.")
    st.stop()

st.title("🎛️ 오케스트레이터")
st.caption("질문 하나로 관련 에이전트들을 골라 부르고, 답변을 하나로 합칩니다.")

_registry = load_registry()
_agents = enabled_agents(_registry)
_host = agent_host()

# 카드 아이콘·닉네임 재사용 — agents_data.py의 name과 레지스트리의 agent_name을 연결한다.
_labels = agent_labels(_agents, AGENTS)

if not _agents:
    st.warning(
        "연결된 에이전트가 없습니다. `data/orchestrator_registry.json`에서 "
        "어댑터가 준비된 에이전트의 `enabled`를 true로 바꿔주세요."
    )
    st.stop()

with st.expander(f"연결된 에이전트 {len(_agents)}개 · 상태 확인", expanded=False):
    st.write(", ".join(_labels.values()))
    if st.button("헬스체크 실행"):
        for key, entry in _agents.items():
            health = check_health(entry, _host)
            if health["ok"]:
                counts = ", ".join(f"{k} {v}" for k, v in health["corpus_counts"].items())
                st.success(f"{_labels[key]} · 정상 {'· ' + counts if counts else ''}")
            else:
                st.error(f"{_labels[key]} · 실패 — {health['error']}")

if "orch_messages" not in st.session_state:
    st.session_state["orch_messages"] = []

for msg in st.session_state["orch_messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

_question = st.chat_input("질문을 입력하세요")

if _question:
    st.session_state["orch_messages"].append({"role": "user", "content": _question})
    with st.chat_message("user"):
        st.markdown(_question)

    history = st.session_state["orch_messages"][:-1]

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
            st.session_state["orch_messages"].append(
                {"role": "assistant", "content": out["answer"]}
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

    st.session_state["orch_messages"].append({"role": "assistant", "content": out["answer"]})
