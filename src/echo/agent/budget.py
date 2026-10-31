from __future__ import annotations

import time

from echo.config import MAX_ESTIMATED_USD, MAX_INPUT_TOKENS, MAX_SECONDS, MAX_TOOL_CALLS


class Budget:
    def __init__(self) -> None:
        self.max_tool_calls = MAX_TOOL_CALLS
        self.max_input_tokens = MAX_INPUT_TOKENS
        self.max_seconds = MAX_SECONDS
        self.max_estimated_usd = MAX_ESTIMATED_USD
        # Keep enough cumulative input budget for the final structured report
        # (and, when still affordable, one bounded correction attempt).
        self.final_input_reserve = min(4000, max(1000, self.max_input_tokens // 3))
        self.max_final_response_calls = 2
        self.tool_calls = 0
        self.final_response_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.started = time.monotonic()

    def remaining_ok(self, model: str = "gpt-5.4") -> bool:
        if self.tool_calls >= self.max_tool_calls:
            return False
        if self.input_tokens >= self.max_input_tokens:
            return False
        if (time.monotonic() - self.started) >= self.max_seconds:
            return False
        if self.estimated_usd(model) >= self.max_estimated_usd:
            return False
        return True

    def diagnostics_remaining_ok(self, model: str = "gpt-5.4") -> bool:
        """Whether another diagnostic turn may run without consuming final-report budget."""
        return self.remaining_ok(model) and self.input_tokens < max(0, self.max_input_tokens - self.final_input_reserve)

    def should_reserve_final(self) -> bool:
        return self.input_tokens >= max(0, self.max_input_tokens - self.final_input_reserve)

    def reason(self, model: str = "gpt-5.4") -> str | None:
        if self.tool_calls >= self.max_tool_calls:
            return "max_tool_calls"
        if self.input_tokens >= self.max_input_tokens:
            return "max_input_tokens"
        if (time.monotonic() - self.started) >= self.max_seconds:
            return "timeout"
        if self.estimated_usd(model) >= self.max_estimated_usd:
            return "max_estimated_usd"
        return None

    def add_usage(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def estimated_usd(self, model: str) -> float:
        rates = {
            "gpt-5.4": (2.50, 15.0),
            "gpt-5-mini": (0.25, 2.0),
            "gpt-4o-mini": (0.15, 0.60),
        }
        inp, out = rates.get(model, (0.25, 2.0))
        return (self.input_tokens / 1_000_000) * inp + (self.output_tokens / 1_000_000) * out
