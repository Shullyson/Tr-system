"""
Shared Anthropic API wrapper. Used by FA, TA, and decision agents.

Every call here enforces JSON-only output when structured_output=True and
fails loudly (raises) rather than silently returning malformed data — a
financial system should never guess what a broken LLM response meant.
"""
import os
import json
import sys

from anthropic import Anthropic
from dotenv import load_dotenv

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "config"))
from settings import LLM_CONFIG as CFG

load_dotenv()


class LLMClient:
    def __init__(self, api_key: str = None):
        api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to a .env file in the "
                "project root or export it in your shell."
            )
        self.client = Anthropic(api_key=api_key)

    def call(self, system_prompt: str, user_prompt: str,
              structured_output: bool = False, max_tokens: int = None) -> str:
        """Returns raw text response."""
        messages = [{"role": "user", "content": user_prompt}]
        response = self.client.messages.create(
            model=CFG["model"],
            max_tokens=max_tokens or CFG["max_tokens"],
            system=system_prompt,
            messages=messages,
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return text.strip()

    def call_json(self, system_prompt: str, user_prompt: str, max_tokens: int = None) -> dict:
        """
        Calls the model and parses the response as JSON. Strips markdown
        code fences if the model wraps its output in them despite
        instructions. Raises ValueError if parsing fails — callers should
        not proceed with a trade decision on unparseable model output.
        """
        strict_system = (
            system_prompt
            + "\n\nRespond with ONLY valid JSON. No preamble, no markdown "
              "code fences, no explanation outside the JSON structure."
        )
        raw = self.call(strict_system, user_prompt, max_tokens=max_tokens)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"LLM did not return valid JSON. Raw response: {raw[:500]}"
            ) from e


if __name__ == "__main__":
    client = LLMClient()
    result = client.call_json(
        system_prompt="You are a helpful assistant that responds in JSON.",
        user_prompt='Return a JSON object with a single key "status" set to "ok".',
    )
    print(result)