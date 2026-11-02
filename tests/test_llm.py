from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from job_radar.apply.drafts import DraftResult
from job_radar.config import ModelPrice
from job_radar.llm import FALLBACK_BETA, AnthropicLLM, LLMError

PRICES = {"claude-sonnet-5-5": ModelPrice(input=2.0, output=10.0)}
REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


class FakeMessages:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def response(stop_reason="end_turn", parsed=None, model="claude-sonnet-5-5", stop_details=None):
    return SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=stop_details,
        parsed_output=parsed,
        model=model,
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500),
    )


def llm_with(messages, fallbacks="default"):
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return AnthropicLLM("claude-sonnet-5-5", "medium", 16000, PRICES, fallbacks, client=client)


def test_parse_sends_structured_output_effort_and_fallback():
    messages = FakeMessages(response(parsed=DraftResult(drafts=[])))
    parsed, usage = llm_with(messages).parse(system="sys", user="hi", output_model=DraftResult)
    assert parsed == DraftResult(drafts=[])
    assert messages.kwargs["output_format"] is DraftResult
    assert messages.kwargs["output_config"] == {"effort": "medium"}
    assert messages.kwargs["betas"] == [FALLBACK_BETA]
    assert messages.kwargs["fallbacks"] == "default"
    assert usage.cost_usd == pytest.approx((1000 * 2.0 + 500 * 10.0) / 1e6)


def test_fallbacks_can_be_turned_off():
    messages = FakeMessages(response(parsed=DraftResult(drafts=[])))
    llm_with(messages, fallbacks=None).parse(system="s", user="u", output_model=DraftResult)
    assert "betas" not in messages.kwargs and "fallbacks" not in messages.kwargs


@pytest.mark.parametrize(
    ("resp", "message"),
    [
        (response("refusal", stop_details=SimpleNamespace(category="cyber")), "cyber"),
        (response("max_tokens"), "max_tokens"),
        (response("end_turn", parsed=None), "沒有回傳"),
    ],
)
def test_unusable_responses_raise(resp, message):
    with pytest.raises(LLMError, match=message):
        llm_with(FakeMessages(resp)).parse(system="s", user="u", output_model=DraftResult)


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            anthropic.RateLimitError(
                "slow", response=httpx2.Response(429, request=REQUEST), body=None
            ),
            "速率限制",
        ),
        (
            anthropic.AuthenticationError(
                "bad key", response=httpx2.Response(401, request=REQUEST), body=None
            ),
            "金鑰",
        ),
        (anthropic.APIConnectionError(request=REQUEST), "連線"),
    ],
)
def test_api_errors_become_readable_messages(error, message):
    with pytest.raises(LLMError, match=message):
        llm_with(FakeMessages(error=error)).parse(system="s", user="u", output_model=DraftResult)
