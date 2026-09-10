"""여러 에이전트 답변을 하나로 합친다.

성공 결과가 1개일 때는 LLM을 태우지 않고 원문을 그대로 통과시킨다. 토큰
절약이 아니라 왜곡 방지다 — 답변 하나를 다시 LLM에 넣으면 원문이 바뀐다.

전부 실패했을 때 `synthesize()`는 일반 지식으로 답하지 않는다. 근거 없는 답변이
근거 있는 답변처럼 보이게 된다. 그 판단은 그대로 두고, 근거 없이라도 답이
필요한 경우를 위해 `direct_answer()`를 따로 둔다 — 호출자가 명시적으로 그것을
고르고, 화면에 근거 없음을 표시할 책임을 진다. 두 경로를 한 함수에 합치지
않는 이유는 합치면 근거 있는 답과 없는 답이 같은 자리에서 같은 모양으로
나오게 되기 때문이다."""
import orchestrator_llm

SYSTEM = """너는 사내 AI 에이전트 오케스트레이터의 합성기다.
여러 전문 에이전트가 같은 질문에 각각 답했다. 그것들을 하나의 답변으로 합쳐라.

규칙:
- 각 주장이 어느 에이전트에서 나왔는지 밝혀라. 출처 없는 문장을 만들지 마라.
- 에이전트들이 서로 다르게 말하면 하나로 뭉개지 말고 양쪽을 병기하고, 다르다는 사실을 명시하라.
- "근거 부족"으로 표시된 답변은 근거를 제대로 찾지 못한 것이다. 조문·자료를 짚은 답변과 같은 무게로 섞지 말고, 참고 수준으로만 쓰고 그렇다고 밝혀라.
- 주어진 답변에 없는 내용을 네 지식으로 채우지 마라.
- 한국어로, 질문에 바로 답하는 것으로 시작하라."""


def citation_key(citation: dict) -> tuple:
    return (
        citation.get("type", ""),
        citation.get("law_name", ""),
        citation.get("article", ""),
    )


def dedupe_citations(results: list) -> list:
    """법령명+조번호가 같은 인용을 하나로 합친다.

    폴리의 법령 코퍼스는 렉스에서 옮겨온 것(poly_vectordb.migrate_from_lexagent)
    이므로 두 에이전트가 같은 조항을 인용해 돌려주는 것이 정상이다."""
    seen, merged = set(), []
    for result in results:
        if not result.ok:
            continue
        for citation in result.citations:
            if not isinstance(citation, dict):
                continue
            key = citation_key(citation)
            if key in seen:
                continue
            seen.add(key)
            merged.append(citation)
    return merged


def _label(agent: str, labels: dict) -> str:
    return (labels or {}).get(agent) or agent


def synthesize(question: str, results: list, labels: dict = None,
               call_text=orchestrator_llm.call_text) -> dict:
    ok_results = [r for r in results if r.ok]
    failed = [{"agent": r.agent, "error": r.error} for r in results if not r.ok]

    if not ok_results:
        lines = ["모든 에이전트가 응답하지 못했습니다.", ""]
        for item in failed:
            lines.append(f"- {_label(item['agent'], labels)}: {item['error']}")
        return {"answer": "\n".join(lines), "citations": [], "mode": "all_failed",
                "failed": failed}

    if len(ok_results) == 1:
        only = ok_results[0]
        return {"answer": only.answer, "citations": dedupe_citations(ok_results),
                "mode": "single", "failed": failed}

    blocks = []
    for result in ok_results:
        mark = "" if result.sufficient else " (근거 부족)"
        blocks.append(f"[{_label(result.agent, labels)}{mark}]\n{result.answer}")

    user = f"[사용자 질문]\n{question}\n\n[에이전트 답변들]\n" + "\n\n".join(blocks)
    return {"answer": call_text(SYSTEM, user), "citations": dedupe_citations(ok_results),
            "mode": "synth", "failed": failed}

DIRECT_SYSTEM = """너는 사내 AI 에이전트 오케스트레이터다.
이번 질문은 담당 에이전트가 없거나 에이전트들이 모두 응답하지 못해, 사내 자료 근거 없이 답해야 한다.

규칙:
- 첫 문장에서 이 답변이 사내 에이전트의 근거 없이 일반 지식으로 작성되었음을 밝혀라.
- 법령 조문 번호, 판례·의결 번호, 통계 수치를 만들어내지 마라. 기억에 의존한 번호는 틀린다.
  구체적 근거가 필요한 대목은 번호를 쓰지 말고 "해당 조문을 확인해야 한다"고 써라.
- 확실하지 않은 것은 확실하지 않다고 써라. 단정하지 마라.
- 마지막에 어디서 정확한 근거를 확인해야 하는지 한 줄로 안내하라.
- 한국어로, 질문에 바로 답하는 것으로 시작하라."""

DIRECT_NOTICE = "⚠️ 사내 에이전트 근거 없이 일반 지식으로 답한 내용입니다. 정확한 근거는 해당 에이전트나 원문에서 확인해야 합니다."


def direct_answer(question: str, failed: list = None, labels: dict = None,
                  call_text=orchestrator_llm.call_text) -> dict:
    """에이전트 근거 없이 오케스트레이터가 직접 답한다.

    `synthesize()`가 의도적으로 하지 않는 일이다. 호출자가 이 함수를 명시적으로
    고른 경우에만 실행되며, 반환된 answer는 맨 앞에 근거 없음 고지를 달고 온다 —
    화면 표시를 호출자 재량에 맡기면 고지 없이 렌더링되는 경로가 생긴다.

    citations는 항상 빈 배열이다. 근거가 없으므로 인용할 것이 없고, 여기에
    무언가 채우면 근거 있는 답변과 구분이 사라진다."""
    failed = failed or []
    body = call_text(DIRECT_SYSTEM, f"[사용자 질문]\n{question}")
    lines = [DIRECT_NOTICE, "", body]
    if failed:
        lines += ["", "**응답하지 못한 에이전트**"]
        lines += [f"- {_label(item['agent'], labels)}: {item['error']}" for item in failed]
    return {"answer": "\n".join(lines), "citations": [], "mode": "direct",
            "failed": failed}
