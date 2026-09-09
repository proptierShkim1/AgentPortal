"""여러 에이전트 답변을 하나로 합친다.

성공 결과가 1개일 때는 LLM을 태우지 않고 원문을 그대로 통과시킨다. 토큰
절약이 아니라 왜곡 방지다 — 답변 하나를 다시 LLM에 넣으면 원문이 바뀐다.

전부 실패했을 때 일반 지식으로 답하지 않는다. 근거 없는 답변이 근거 있는
답변처럼 보이게 된다."""
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
