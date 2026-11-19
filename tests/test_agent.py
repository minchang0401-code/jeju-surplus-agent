"""에이전트(규칙 기반 모드)의 질문 이해·답변과 LLM 오류 처리. 시험 문항은 run_scenarios.py 와 같은 목록을 씀."""
import pytest
import requests

import agent
from run_scenarios import ANSWER_TESTS, FOLLOWUP_TESTS, ROUTING_TESTS, SCENARIOS


@pytest.mark.parametrize("q,expected", ROUTING_TESTS)
def test_routing(q, expected):
    tools_used = [n for n, _ in agent._route(q)] or ["(답할 수 없음)"]
    assert expected in tools_used


@pytest.mark.parametrize("prev,q,expected", FOLLOWUP_TESTS)
def test_followup(prev, q, expected):
    routed, _ = agent._with_context(q, [prev])
    tools_used = [n for n, _ in agent._route(routed)] or ["(답할 수 없음)"]
    assert expected in tools_used


@pytest.mark.parametrize("q,must,must_not", ANSWER_TESTS)
def test_answers(q, must, must_not):
    a = agent.ask(q)["answer"]
    for m in must:
        assert m in a, m
    for m in must_not:
        assert m not in a, m


@pytest.mark.parametrize("title,q,expected,purpose", SCENARIOS)
def test_scenarios(title, q, expected, purpose):
    res = agent.ask(q)
    used = [t["tool"] for t in res["trace"]]
    assert all(e in used for e in expected)
    assert res["mode"] == "fallback"


def test_unknown_question_is_declined():
    a = agent.ask("제주 맛집 추천해줘")["answer"]
    assert "답할 수 없어요" in a


class _Resp:
    def __init__(self, code, body=None):
        self.status_code, self._b, self.text = code, body or {}, str(body)

    def json(self):
        return self._b


def test_llm_retry_then_error_message(monkeypatch):
    seq = [_Resp(429, {"error": {"message": "quota"}}), _Resp(400, {"error": {"message": "bad request"}})]
    monkeypatch.setattr(agent.requests, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(agent.LLMError, match="HTTP 400"):
        agent._post_retry("u", {}, {})


def test_llm_timeout_is_retried(monkeypatch):
    calls = []

    def post(*a, **k):
        calls.append(1)
        if len(calls) < 3:
            raise requests.ReadTimeout("slow")
        return _Resp(200)
    monkeypatch.setattr(agent.requests, "post", post)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert agent._post_retry("u", {}, {}).status_code == 200 and len(calls) == 3


def test_llm_failure_falls_back_and_hides_key(monkeypatch):
    secret = "TEST-SECRET-KEY-123"
    monkeypatch.setattr(agent, "_llm_config", lambda: {"provider": "gemini", "key": secret,
                                                       "base_url": "u", "model": "m"})

    def boom(*a, **k):
        raise agent.LLMError(f"HTTP 401: bad key {secret}")
    monkeypatch.setattr(agent, "_chat_openai", boom)
    res = agent.ask("빨래 언제 돌려?")
    assert res["mode"] == "fallback"
    err = [t for t in res["trace"] if t["tool"] == "llm_error"][0]["result"]["error"]
    assert secret not in err and "***" in err


def test_tool_args_are_repaired():
    r = agent._run_tool("plan_appliance_use", {"target": "전기차", "car": "아이오닉5", "unknown_arg": 1})
    assert "error" not in r and r["appliance"] == "전기차"


def test_time_answers_end_with_how_to_take_part():
    """시간 추천 답 끝에 '실제로 참여하는 길'(요금제 확인 창구, 전기차는 플러스 DR)이 붙고, 요금제 가입자에게는 가입 권유 대신 이득을 말함."""
    from agent import _fallback
    ev = _fallback("전기차 언제 충전하는 게 좋아?", [])
    assert "계시별 선택요금제" in ev and "123" in ev and "플러스 DR" in ev and "확인" in ev
    wash = _fallback("토요일에 세탁기 언제 돌려?", [])
    assert "요금까지 아끼려면" in wash and "플러스 DR" not in wash
    joined = _fallback("토요일에 세탁기 언제 돌려?", [], profile={"area": "", "car": "", "work_start": None,
                                                              "work_end": None, "tou": "가입"})
    assert "가입하셨으니" in joined and "요금까지 아끼려면" not in joined
