import json
import os
import time

import requests


class LLM:
    """Optional last-step trade veto. Never opens a trade."""

    def __init__(self, cfg, journal):
        self.c, self.j = cfg, journal

    def _fail(self, why):
        # Safety-critical: errors can never authorize a trade.
        return {
            "approve": False,
            "reason": why,
            "error": True,
        }

    def verify(self, sig, trend, closes):
        if not self.c.get("enabled"):
            return {
                "approve": False,
                "skipped": True,
                "reason": "LLM approval is mandatory but LLM is disabled",
            }

        key_env = self.c.get("api_key_env", "")
        key = os.environ.get(key_env, "") if key_env else ""

        if not key:
            return self._fail("No LLM API key loaded")

        day = time.strftime("%Y-%m-%d")
        try:
            n = int(self.j.kv_get(f"llm_calls_{day}", 0))
            cap = int(self.c.get("max_calls_per_day", 30))
        except (TypeError, ValueError) as e:
            return self._fail(f"Invalid LLM call-limit state: {type(e).__name__}")

        if n >= cap:
            return self._fail("LLM daily call cap reached")

        prompt = (
            "You check a long-only spot trend-following setup. "
            "Reply with one JSON object only, using exactly these fields: "
            '{"approve": true, "trend": "up", "reason": "short explanation"}. '
            "approve must be a JSON boolean. trend must be up, range, or down. "
            "Keep reason within 20 words.\n"
            f"Setup: {sig.setup} on {sig.symbol}; "
            f"entry {sig.entry}, stop {sig.stop}, target {sig.take_profit}. "
            f"Why: {sig.reason}. "
            f"Trend filter: {json.dumps(trend['detail'])}. "
            f"Last closes (oldest to newest): {closes}"
        )

        # Count attempted calls so repeated failures cannot bypass the daily cap.
        try:
            self.j.kv_set(f"llm_calls_{day}", n + 1)

            response = requests.post(
                self.c["base_url"].rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                timeout=40,
                json={
                    "model": self.c["model"],
                    "max_completion_tokens": 1000,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            try:
                data = response.json()
            except ValueError:
                return self._fail(
                    f"LLM returned non-JSON HTTP response ({response.status_code})"
                )

            if not response.ok:
                error = data.get("error", {})
                if isinstance(error, dict):
                    message = error.get("message", "Unknown API error")
                else:
                    message = str(error) or "Unknown API error"
                return self._fail(
                    f"LLM HTTP {response.status_code}: {message[:250]}"
                )

            choices = data.get("choices")
            if not isinstance(choices, list) or not choices:
                return self._fail("LLM response contains no choices")

            message = choices[0].get("message") or {}
            content = message.get("content")

            if not isinstance(content, str) or not content.strip():
                return self._fail("LLM returned empty content")

            # Accept a JSON object, optionally surrounded by Markdown fences.
            content = content.strip()
            if content.startswith("```"):
                lines = content.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines).strip()

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                return self._fail("LLM response is not valid JSON")

            if not isinstance(result, dict):
                return self._fail("LLM JSON must be an object")

            approve = result.get("approve")
            direction = result.get("trend")
            reason = result.get("reason")

            if type(approve) is not bool:
                return self._fail("LLM approve field must be a JSON boolean")

            if direction not in {"up", "range", "down"}:
                return self._fail("LLM trend field has an invalid value")

            if not isinstance(reason, str) or not reason.strip():
                return self._fail("LLM reason field is missing or invalid")

            # A downtrend can never be approved by the LLM.
            return {
                "approve": approve and direction != "down",
                "trend": direction,
                "reason": reason.strip()[:500],
            }

        except requests.RequestException as e:
            return self._fail(f"LLM network error: {type(e).__name__}")
        except Exception as e:
            return self._fail(f"LLM verification error: {type(e).__name__}")
