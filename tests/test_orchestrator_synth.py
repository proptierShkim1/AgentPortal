import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator_synth as synth
from orchestrator_executor import AgentResult

LABELS = {"lex": "렉스", "policy": "폴리"}


def _law(law_name, article, text="조문 내용"):
    return {"type": "law", "law_name": law_name, "article": article, "text": text}


def _fake_call_text(reply, capture=None):
    def _call(system, user, max_tokens=16000, client=None):
        if capture is not None:
            capture.append({"system": system, "user": user})
        return reply
    return _call


def test_citation_key_uses_law_name_and_article():
    assert synth.citation_key(_law("개인정보보호법", "제15조")) == ("law", "개인정보보호법", "제15조")


def test_dedupe_citations_removes_same_law_and_article_across_agents():
    results = [
        AgentResult(agent="lex", ok=True, answer="a", citations=[_law("개인정보보호법", "제15조")]),
        AgentResult(agent="policy", ok=True, answer="b", citations=[_law("개인정보보호법", "제15조")]),
    ]
    assert len(synth.dedupe_citations(results)) == 1


def test_dedupe_citations_keeps_different_articles():
    results = [
        AgentResult(agent="lex", ok=True, answer="a",
                    citations=[_law("개인정보보호법", "제15조"), _law("개인정보보호법", "제17조")]),
    ]
    assert len(synth.dedupe_citations(results)) == 2


def test_dedupe_citations_ignores_failed_results():
    results = [
        AgentResult(agent="lex", ok=False, error="다운", citations=[_law("개인정보보호법", "제15조")]),
    ]
    assert synth.dedupe_citations(results) == []


def test_dedupe_citations_ignores_non_dict_elements():
    results = [
        AgentResult(agent="lex", ok=True, answer="a",
                    citations=["법령명 문자열만 옴", _law("개인정보보호법", "제15조")]),
    ]
    deduped = synth.dedupe_citations(results)
    assert deduped == [_law("개인정보보호법", "제15조")]


def test_synthesize_with_string_citations_does_not_raise():
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변", citations=["문자열", "또다른 문자열"]),
    ]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("불려선 안 됨"))
    assert out["mode"] == "single"
    assert out["citations"] == []


def test_synthesize_all_failed_lists_reasons_and_does_not_call_llm():
    calls = []
    results = [
        AgentResult(agent="lex", ok=False, error="ConnectError: 연결 거부"),
        AgentResult(agent="policy", ok=False, error="HTTP 500"),
    ]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("불려선 안 됨", capture=calls))
    assert out["mode"] == "all_failed"
    assert calls == []
    assert "렉스" in out["answer"]
    assert "ConnectError: 연결 거부" in out["answer"]
    assert "HTTP 500" in out["answer"]
    assert out["citations"] == []


def test_synthesize_single_result_passes_through_without_llm():
    calls = []
    results = [AgentResult(agent="lex", ok=True, answer="렉스의 원본 답변",
                           citations=[_law("개인정보보호법", "제15조")])]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성하면 안 됨", capture=calls))
    assert out["mode"] == "single"
    assert calls == []
    assert out["answer"] == "렉스의 원본 답변"
    assert len(out["citations"]) == 1


def test_synthesize_two_results_calls_llm_and_returns_its_text():
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성된 답변"))
    assert out["mode"] == "synth"
    assert out["answer"] == "합성된 답변"


def test_synthesize_prompt_labels_each_answer_with_agent_name():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    user = calls[0]["user"]
    assert "렉스" in user and "렉스 답변" in user
    assert "폴리" in user and "폴리 답변" in user


def test_synthesize_prompt_marks_insufficient_grounding():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="근거 있음", sufficient=True),
        AgentResult(agent="policy", ok=True, answer="근거 없음", sufficient=False),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "근거 부족" in calls[0]["user"]


def test_synthesize_system_prompt_forbids_merging_conflicts():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="A라고 본다"),
        AgentResult(agent="policy", ok=True, answer="B라고 본다"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "병기" in calls[0]["system"]


def test_synthesize_reports_partial_failures_alongside_synthesis():
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="policy", ok=True, answer="폴리 답변"),
    ]
    results.append(AgentResult(agent="radar", ok=False, error="HTTP 502"))
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("합성된 답변"))
    assert out["mode"] == "synth"
    assert out["failed"] == [{"agent": "radar", "error": "HTTP 502"}]


def test_synthesize_empty_results_is_all_failed():
    out = synth.synthesize("질문", [], labels=LABELS, call_text=_fake_call_text("x"))
    assert out["mode"] == "all_failed"


def test_synthesize_falls_back_to_agent_key_when_label_missing():
    calls = []
    results = [
        AgentResult(agent="lex", ok=True, answer="렉스 답변"),
        AgentResult(agent="unknown", ok=True, answer="미등록 답변"),
    ]
    synth.synthesize("질문", results, labels=LABELS,
                     call_text=_fake_call_text("합성", capture=calls))
    assert "unknown" in calls[0]["user"]

# --- direct_answer — 근거 없는 답변 경로 ---------------------------------
# synthesize()가 의도적으로 하지 않는 일이므로, 이 경로가 (1) 반드시 고지를 달고
# (2) 인용을 절대 채우지 않고 (3) 조문 번호를 만들지 말라고 지시하는지 고정한다.


def test_direct_answer_prefixes_ungrounded_notice():
    out = synth.direct_answer("질문", call_text=_fake_call_text("본문 답변"))
    assert out["answer"].startswith(synth.DIRECT_NOTICE)
    assert "본문 답변" in out["answer"]


def test_direct_answer_mode_is_direct():
    out = synth.direct_answer("질문", call_text=_fake_call_text("본문"))
    assert out["mode"] == "direct"


def test_direct_answer_never_returns_citations():
    out = synth.direct_answer("질문", call_text=_fake_call_text("본문"))
    assert out["citations"] == []


def test_direct_answer_lists_failed_agents_with_labels():
    failed = [{"agent": "lex", "error": "연결 실패"}]
    out = synth.direct_answer("질문", failed=failed, labels=LABELS,
                              call_text=_fake_call_text("본문"))
    assert "렉스: 연결 실패" in out["answer"]
    assert out["failed"] == failed


def test_direct_answer_without_failures_omits_failure_section():
    out = synth.direct_answer("질문", call_text=_fake_call_text("본문"))
    assert "응답하지 못한 에이전트" not in out["answer"]
    assert out["failed"] == []


def test_direct_answer_system_prompt_forbids_inventing_article_numbers():
    capture = []
    synth.direct_answer("질문", call_text=_fake_call_text("본문", capture))
    system = capture[0]["system"]
    assert "만들어내지 마라" in system
    assert "근거 없이" in system or "근거 없음" in system


def test_direct_answer_sends_question_to_llm():
    capture = []
    synth.direct_answer("처리방침 개정 절차", call_text=_fake_call_text("본문", capture))
    assert "처리방침 개정 절차" in capture[0]["user"]


def test_synthesize_all_failed_still_does_not_call_llm_after_direct_added():
    """direct_answer가 생겼어도 synthesize의 무LLM 불변식은 그대로여야 한다.

    두 경로가 섞이면 근거 없는 답변이 합성 답변 자리에서 나온다."""
    calls = []
    results = [AgentResult(agent="lex", ok=False, error="연결 실패")]
    out = synth.synthesize("질문", results, labels=LABELS,
                           call_text=_fake_call_text("호출되면 안 됨", calls))
    assert calls == []
    assert out["mode"] == "all_failed"

