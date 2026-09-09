import streamlit as st

from access_control import is_admin
from agent_host import agent_host
from agents_data import AGENTS
from orchestrator_registry import load_registry, enabled_agents, agent_labels
from orchestrator_router import route
from orchestrator_executor import ask_agents, check_health
from orchestrator_synth import synthesize

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
            decision = route(_question, _agents)

        if not decision["picks"]:
            st.info(decision["none_reason"])
            st.caption("연결된 에이전트: " + ", ".join(_labels.values()))
            st.session_state["orch_messages"].append(
                {"role": "assistant", "content": decision["none_reason"]}
            )
            st.stop()

        picked = ", ".join(_labels.get(p["agent"], p["agent"]) for p in decision["picks"])
        with st.spinner(f"{picked} 호출 중..."):
            results = ask_agents(decision["picks"], _agents, _question, history, _host)

        with st.spinner("답변을 합치는 중..."):
            out = synthesize(_question, results, labels=_labels)

        st.markdown(out["answer"])

        # 라우팅을 블랙박스로 두지 않는다 — 왜 그 에이전트를 불렀는지 항상 보여준다.
        with st.expander("이 답변이 만들어진 경로", expanded=False):
            st.markdown("**호출한 에이전트와 이유**")
            for pick in decision["picks"]:
                st.markdown(f"- {_labels.get(pick['agent'], pick['agent'])}: {pick['reason']}")

            if out["failed"]:
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
