import os
import time
from typing import Dict, Any, List

from context import APIRuntimeContext
from logger import get_logger

from openai import OpenAI
from google import genai

logger = get_logger("interface_manager")


def handle_api_chat(
    ctx: APIRuntimeContext,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Executes one API chat request and returns a normalized response.
    """

    # --------------------------------------------------
    # Driver lifecycle start
    # --------------------------------------------------
    logger.info("Driver is ready for API")

    start_ts = time.time()

    prompts: List[str] = payload.get("prompt_list", [])
    prompt = " ".join(prompts).strip()

    if not prompt:
        logger.error("Empty prompt_list received")
        raise ValueError("Empty prompt_list received")

    logger.info("Sending prompt to the bot: %s", prompt)

    logger.info(
        "API chat started | provider=%s model=%s",
        ctx.provider,
        ctx.agent_name,
    )

    try:
        # --------------------------------------------------
        # Dispatch by provider
        # --------------------------------------------------
        if ctx.is_openai():
            text = _run_openai(ctx, prompt)

        elif ctx.is_gemini():
            text = _run_gemini(ctx, prompt)

        elif ctx.is_local():
            text = _run_local(ctx, prompt)

        else:
            raise RuntimeError(f"Unsupported provider: {ctx.provider}")

        elapsed = int(time.time() - start_ts)

        logger.info(
            "(Waited:%d) Received response from API (%s): %s",
            elapsed,
            ctx.agent_name,
            text,
        )

        logger.info(
            "API chat completed | chars=%d time=%ss",
            len(text),
            round(time.time() - start_ts, 3),
        )

        return {
            "response": [
                {
                    "chat_id": payload.get("chat_id"),
                    "prompt": prompt,
                    "response": {
                        "type": "text",
                        "content": text
                    }
                }
            ]
        }

    finally:
        # --------------------------------------------------
        # Driver lifecycle end (always runs)
        # --------------------------------------------------
        logger.info("Driver quit successfully")


# ------------------------------------------------------------------
# Provider implementations
# ------------------------------------------------------------------

def _run_openai(ctx: APIRuntimeContext, prompt: str) -> str:
    logger.info("Calling OpenAI API | model=%s", ctx.agent_name)

    client = OpenAI()

    response = client.chat.completions.create(
        model=ctx.agent_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=ctx.temperature,
        max_tokens=ctx.max_tokens,
        top_p=ctx.top_p,
    )

    return response.choices[0].message.content.strip()


def _run_gemini(ctx: APIRuntimeContext, prompt: str) -> str:
    logger.info("Calling Gemini API | model=%s", ctx.agent_name)

    client = genai.Client()

    response = client.models.generate_content(
        model=ctx.agent_name,
        contents=prompt,
    )

    return response.text.strip()


def _run_local(ctx: APIRuntimeContext, prompt: str) -> str:
    """
    Call an OpenAI-compatible chat completions endpoint.

    PATCH NOTE (Gates eval): Original v2.0 silently dropped sampling params and
    crashed on Sarvam-30B's reasoning_content/null content pattern. This patched
    version:
      - Uses real api_key (not "local" placeholder)
      - Passes seed, n, temperature, max_tokens, top_p when set
      - Forwards Sarvam-specific reasoning_effort + wiki_grounding via extra_body
      - Sends system_prompt as separate role (not concatenated)
      - Enforces max_tokens >= 1024 (reasoning trace eats tokens before content)
      - Falls back to reasoning_content if content is null
    """
    logger.info(
        "Calling LOCAL OpenAI-compatible API | model=%s base_url=%s",
        ctx.agent_name,
        ctx.base_url,
    )

    if not ctx.base_url:
        raise RuntimeError("LOCAL provider requires base_url")

    # PATCH (Gates eval): resolve api_key from ctx → env var by provider hint → generic env → placeholder.
    # The env-var fallback lets config.json reference keys by name (api_key_env: SARVAM_API_KEY)
    # without committing the secret. Sarvam keys live in SARVAM_API_KEY; OpenAI-compatible
    # third-party endpoints often use OPENAI_API_KEY.
    api_key = ctx.api_key
    if not api_key:
        # Try provider-specific env first based on base_url hint
        bu = (ctx.base_url or "").lower()
        if "sarvam.ai" in bu:
            api_key = os.getenv("SARVAM_API_KEY")
        elif "openrouter.ai" in bu:
            api_key = os.getenv("OPENROUTER_API_KEY")
        elif "groq.com" in bu:
            api_key = os.getenv("GROQ_API_KEY")
        # Fallback to generic OPENAI_API_KEY for any OpenAI-compatible endpoint
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            api_key = "local"  # placeholder for truly local endpoints (Ollama, etc.)

    client = OpenAI(
        base_url=f"{ctx.base_url.rstrip('/')}/v1",
        api_key=api_key,
    )

    # Build messages: system as separate role if provided, then user prompt
    messages = []
    if ctx.system_prompt:
        messages.append({"role": "system", "content": ctx.system_prompt})
    messages.append({"role": "user", "content": prompt})

    # Build kwargs with optional sampling params
    kwargs = {
        "model": ctx.agent_name,
        "messages": messages,
        "stream": False,
    }
    if ctx.temperature is not None:
        kwargs["temperature"] = ctx.temperature
    if ctx.max_tokens is not None:
        # Reasoning models consume tokens before producing content
        kwargs["max_tokens"] = max(int(ctx.max_tokens), 1024)
    if ctx.top_p is not None:
        kwargs["top_p"] = ctx.top_p
    if ctx.seed is not None:
        kwargs["seed"] = int(ctx.seed)
    if ctx.n is not None and int(ctx.n) > 1:
        kwargs["n"] = int(ctx.n)

    # Provider-specific extensions via extra_body
    extra_body = {}
    if ctx.reasoning_effort:
        extra_body["reasoning_effort"] = ctx.reasoning_effort
    if ctx.wiki_grounding is not None:
        extra_body["wiki_grounding"] = bool(ctx.wiki_grounding)
    if extra_body:
        kwargs["extra_body"] = extra_body

    response = client.chat.completions.create(**kwargs)

    msg = response.choices[0].message
    # Reasoning models (Sarvam-30B/105B) return final answer in `content` AND
    # the chain-of-thought in `reasoning_content`. If max_tokens is exhausted
    # before the final answer, `content` is None and `reasoning_content` holds
    # the partial trace — surface that rather than crashing.
    text = (msg.content or getattr(msg, "reasoning_content", None) or "").strip()

    if not text:
        logger.warning(
            "Empty response from LOCAL provider | model=%s finish_reason=%s",
            ctx.agent_name,
            response.choices[0].finish_reason,
        )

    return text
