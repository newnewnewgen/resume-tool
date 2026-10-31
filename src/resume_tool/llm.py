"""The one LLM seam. Everything model-shaped goes through complete().

Thin on purpose (SPEC learning #6): model IDs and token budgets come from
Config, never from call sites, and callers depend on a plain callable
`(system, prompt) -> str` so tests substitute a fake without any mocking
of the provider SDK.
"""

from __future__ import annotations

from collections.abc import Callable

from .config import Config

# What step modules accept wherever they need a model.
CompleteFn = Callable[[str, str], str]


class LLMError(RuntimeError):
    """Raised when the provider cannot be used or returns garbage."""


def complete(system: str, prompt: str) -> str:
    """One blocking completion through the configured Anthropic model."""
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - packaging error
        raise LLMError("the 'anthropic' package is not installed — pip install -e .") from exc

    config = Config.load()
    try:
        client = anthropic.Anthropic()
        with client.messages.stream(
            model=config.model,
            max_tokens=config.max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()
    except anthropic.AuthenticationError as exc:
        raise LLMError(
            "no usable Anthropic credentials — set ANTHROPIC_API_KEY or run `ant auth login`"
        ) from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"could not reach the API: {exc}") from exc

    if response.stop_reason == "refusal":
        raise LLMError("the model declined this request (stop_reason=refusal)")
    if response.stop_reason == "max_tokens":
        raise LLMError(
            f"response was truncated at {config.max_tokens} tokens — "
            "raise RESUME_TOOL_MAX_TOKENS"
        )

    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise LLMError("the model returned no text")
    return text
