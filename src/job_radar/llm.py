"""Claude client used for drafting: one structured-output call, with cost accounting."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from job_radar.config import Effort, ModelPrice

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """A drafting call failed; the message is shown to the user as-is."""


@dataclass
class LLMUsage:
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class StructuredLLM(Protocol):
    model: str

    def parse(self, *, system: str, user: str, output_model: type[T]) -> tuple[T, LLMUsage]: ...


class AnthropicLLM:
    def __init__(
        self,
        model: str,
        effort: Effort,
        max_tokens: int,
        prices: dict[str, ModelPrice],
        fallbacks: str | None = "default",
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.prices = prices
        self.fallbacks = fallbacks
        self._client = client

    def _get_client(self) -> anthropic.Anthropic:
        if self._client is None:
            try:
                self._client = anthropic.Anthropic()
            except anthropic.AnthropicError as exc:
                raise LLMError(
                    "找不到 Anthropic 憑證：在 .env 設定 ANTHROPIC_API_KEY，或執行 `ant auth login`"
                ) from exc
        return self._client

    def parse(self, *, system: str, user: str, output_model: type[T]) -> tuple[T, LLMUsage]:
        extra: dict = {}
        if self.fallbacks:
            extra = {"betas": [FALLBACK_BETA], "fallbacks": self.fallbacks}
        try:
            response = self._get_client().beta.messages.parse(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                output_format=output_model,
                output_config={"effort": self.effort},
                **extra,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMError("Anthropic API 金鑰無效或已過期") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMError("這個 API 金鑰沒有使用此模型的權限") from exc
        except anthropic.NotFoundError as exc:
            raise LLMError(f"找不到模型 {self.model}（檢查 TAILOR_MODEL）") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("超過 Anthropic API 速率限制，請稍後再試") from exc
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Anthropic API 拒絕了請求：{exc.message}") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API 錯誤（HTTP {exc.status_code}），請稍後再試") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("無法連線到 Anthropic API，請檢查網路") from exc
        except (ValidationError, ValueError) as exc:
            raise LLMError("模型回傳的格式無法解析，請再試一次") from exc

        usage = self._usage(response)
        if response.stop_reason == "refusal":
            category = response.stop_details.category if response.stop_details else None
            raise LLMError(f"模型拒絕產生這份草稿（類別：{category or '未分類'}）")
        if response.stop_reason == "max_tokens":
            raise LLMError("草稿太長被截斷：請提高 config/settings.yaml 的 llm.max_tokens")
        parsed = response.parsed_output
        if parsed is None:
            raise LLMError("模型沒有回傳可用的結果，請再試一次")
        return parsed, usage

    def _usage(self, response: object) -> LLMUsage:
        usage = response.usage  # type: ignore[attr-defined]
        served_by = getattr(response, "model", self.model) or self.model
        if served_by != self.model:
            log.info("這次由備援模型 %s 產生（成本以 %s 的價格估算）", served_by, served_by)
        price = self.prices.get(served_by) or self.prices.get(self.model)
        cost = 0.0
        if price:
            cost = (usage.input_tokens * price.input + usage.output_tokens * price.output) / 1e6
        else:
            log.warning("config/settings.yaml 沒有 %s 的價格，成本記為 0", served_by)
        log.info(
            "LLM 用量：輸入 %d tokens、輸出 %d tokens，約 $%.4f",
            usage.input_tokens,
            usage.output_tokens,
            cost,
        )
        return LLMUsage(served_by, usage.input_tokens, usage.output_tokens, cost)
