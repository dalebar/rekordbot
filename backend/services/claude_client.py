"""Claude client — wraps the Anthropic SDK for AI tagging requests.

Handles API calls with rate limiting, retry logic, token tracking,
and structured tool use response parsing. All SDK calls are synchronous
and should be wrapped in asyncio.to_thread() by callers.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

import anthropic  # type: ignore[import-not-found]

from backend.exceptions import AiTagError
from backend.services.prompt_builder import AiTagResult, parse_tool_result

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = {429, 529}
MAX_RETRIES = 3
INITIAL_BACKOFF = 1.0

# Approximate pricing per million tokens (USD) — Sonnet 4
_COST_PER_MTOK_INPUT = 3.0
_COST_PER_MTOK_OUTPUT = 15.0


@dataclass
class ClaudeResponse:
    """Response from a single Claude API call.

    Attributes:
        results: Parsed AI tag results from tool use.
        input_tokens: Number of input tokens used.
        output_tokens: Number of output tokens used.
        model: Model ID used for this request.
        request_duration: Wall-clock time in seconds.
    """

    results: list[AiTagResult]
    input_tokens: int
    output_tokens: int
    model: str
    request_duration: float


@dataclass
class TokenUsage:
    """Cumulative token usage across multiple requests.

    Attributes:
        total_input_tokens: Total input tokens consumed.
        total_output_tokens: Total output tokens consumed.
        total_requests: Number of API requests made.
        estimated_cost_usd: Estimated cost in USD.
    """

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_requests: int = 0
    estimated_cost_usd: float = 0.0


class RateLimiter:
    """Simple timestamp-based rate limiter.

    Tracks request timestamps and sleeps when the per-minute limit
    would be exceeded. Sufficient for a single-user desktop app.

    Attributes:
        max_per_minute: Maximum requests allowed per 60-second window.
    """

    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max_per_minute
        self.timestamps: list[float] = []

    async def acquire(self) -> None:
        """Wait until a request slot is available within the rate limit."""
        now = time.time()
        self.timestamps = [t for t in self.timestamps if now - t < 60]
        if len(self.timestamps) >= self.max_per_minute:
            sleep_time = 60 - (now - self.timestamps[0])
            if sleep_time > 0:
                logger.info("Rate limit reached, sleeping %.1fs", sleep_time)
                await asyncio.sleep(sleep_time)
        self.timestamps.append(time.time())


class ClaudeClient:
    """Client for Claude API interactions with rate limiting and retries.

    Attributes:
        model: Model ID to use for requests.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_requests_per_minute: int = 10,
    ) -> None:
        if not api_key:
            raise AiTagError(
                "Anthropic API key is not configured. "
                "Set REKORDBOT_ANTHROPIC_API_KEY in your .env file.",
                status_code=400,
            )
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.rate_limiter = RateLimiter(max_requests_per_minute)
        self._usage = TokenUsage()

    def get_token_usage(self) -> TokenUsage:
        """Return cumulative token usage for this client's session.

        Returns:
            TokenUsage with totals and estimated cost.
        """
        return self._usage

    async def validate_api_key(self) -> bool:
        """Validate the API key by making a minimal API call.

        Returns:
            True if the key is valid.

        Raises:
            AiTagError: If the key is invalid or the API is unreachable.
        """
        try:
            await asyncio.to_thread(
                self.client.messages.create,
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            return True
        except anthropic.AuthenticationError:
            raise AiTagError(
                "Invalid Anthropic API key. Please check your key " "and try again.",
                status_code=401,
            ) from None
        except anthropic.APIError as e:
            raise AiTagError(
                f"Anthropic API error during key validation: {e}",
                status_code=502,
            ) from e

    async def tag_batch(
        self,
        system_prompt: str,
        user_message: str,
        tool_schema: dict[str, Any],
        batch_track_ids: list[int],
    ) -> ClaudeResponse:
        """Send a batch of tracks to Claude for tagging via tool use.

        Args:
            system_prompt: The system prompt with genre/mood guidance.
            user_message: The formatted track summaries.
            tool_schema: The tag_tracks tool schema definition.
            batch_track_ids: Track IDs in this batch (for result validation).

        Returns:
            ClaudeResponse with parsed results and token usage.

        Raises:
            AiTagError: If the API call fails after retries.
        """
        await self.rate_limiter.acquire()

        start_time = time.time()
        response = await self._call_with_retry(
            system_prompt=system_prompt,
            user_message=user_message,
            tool_schema=tool_schema,
        )
        duration = time.time() - start_time

        # Extract token usage
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens

        # Update cumulative usage
        self._usage.total_input_tokens += input_tokens
        self._usage.total_output_tokens += output_tokens
        self._usage.total_requests += 1
        self._usage.estimated_cost_usd = (
            self._usage.total_input_tokens * _COST_PER_MTOK_INPUT / 1_000_000
            + self._usage.total_output_tokens * _COST_PER_MTOK_OUTPUT / 1_000_000
        )

        # Parse tool use response
        results = self._extract_tool_results(response, batch_track_ids)

        logger.info(
            "Claude API call: %d input, %d output tokens, %.1fs, " "%d tracks tagged, model=%s",
            input_tokens,
            output_tokens,
            duration,
            len(results),
            response.model,
        )

        return ClaudeResponse(
            results=results,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=response.model,
            request_duration=duration,
        )

    async def _call_with_retry(
        self,
        system_prompt: str,
        user_message: str,
        tool_schema: dict[str, Any],
    ) -> Any:
        """Make an API call with exponential backoff retry on rate limits.

        Args:
            system_prompt: System prompt content.
            user_message: User message content.
            tool_schema: Tool definition for function calling.

        Returns:
            The Anthropic Message response.

        Raises:
            AiTagError: If all retries are exhausted or a non-retryable
                error occurs.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(
                    self.client.messages.create,
                    model=self.model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                    tools=[tool_schema],
                    tool_choice={"type": "tool", "name": "tag_tracks"},
                )
            except anthropic.AuthenticationError:
                raise AiTagError(
                    "Invalid Anthropic API key.",
                    status_code=401,
                ) from None
            except anthropic.RateLimitError:
                if attempt == MAX_RETRIES:
                    raise AiTagError(
                        "Anthropic rate limit exceeded after " f"{MAX_RETRIES} retries.",
                        status_code=429,
                    ) from None
                backoff = INITIAL_BACKOFF * (2**attempt)
                logger.warning(
                    "Rate limited, retrying in %.1fs (attempt %d/%d)",
                    backoff,
                    attempt + 1,
                    MAX_RETRIES,
                )
                await asyncio.sleep(backoff)
            except anthropic.APIStatusError as e:
                if e.status_code in RETRY_STATUS_CODES:
                    if attempt == MAX_RETRIES:
                        raise AiTagError(
                            f"Anthropic API error (status {e.status_code})"
                            f" after {MAX_RETRIES} retries: {e}",
                            status_code=502,
                        ) from e
                    backoff = INITIAL_BACKOFF * (2**attempt)
                    logger.warning(
                        "API error %d, retrying in %.1fs " "(attempt %d/%d)",
                        e.status_code,
                        backoff,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    await asyncio.sleep(backoff)
                else:
                    raise AiTagError(
                        f"Anthropic API error: {e}",
                        status_code=502,
                    ) from e
            except anthropic.APIError as e:
                raise AiTagError(
                    f"Anthropic API error: {e}",
                    status_code=502,
                ) from e

        raise AiTagError(
            "Unexpected: retry loop exhausted without result.",
            status_code=500,
        )

    def _extract_tool_results(
        self, response: Any, batch_track_ids: list[int]
    ) -> list[AiTagResult]:
        """Extract and parse tool use results from a Claude response.

        Args:
            response: The Anthropic Message response object.
            batch_track_ids: Valid track IDs for this batch.

        Returns:
            List of validated AiTagResult objects.
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "tag_tracks":
                return parse_tool_result(block.input, batch_track_ids)

        logger.warning(
            "No tag_tracks tool use found in Claude response " "(stop_reason=%s)",
            response.stop_reason,
        )
        return []
