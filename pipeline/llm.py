"""Model access for the pipeline, so the provider can be swapped in one place.

Default is Google Gemini (GEMINI_API_KEY). Set LLM_PROVIDER=anthropic (with
ANTHROPIC_API_KEY) to use Claude for the JSON-only steps instead; the
web-grounded steps (research, article verification) need Gemini.

Model ids live in config.py (TRIAGE_MODEL, RESEARCH_MODEL).
"""
import json
import os

import config

_gemini_client = None

# Running totals for this process, written to the cost log by run.py.
usage = {"models": {}, "gemini_searches": 0, "serper_queries": 0}


def _record(model, input_tokens, output_tokens, searches=0):
    m = usage["models"].setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    m["calls"] += 1
    m["input_tokens"] += input_tokens or 0
    m["output_tokens"] += output_tokens or 0
    usage["gemini_searches"] += searches


def provider():
    return (os.environ.get("LLM_PROVIDER") or "gemini").lower()


def available(grounded=False):
    if grounded or provider() == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"))
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _gemini():
    global _gemini_client
    if _gemini_client is None:
        from google import genai  # reads GEMINI_API_KEY / GOOGLE_API_KEY

        _gemini_client = genai.Client()
    return _gemini_client


def generate_json(system, prompt, schema, model=None, search=False, read_urls=False):
    """Return the model's JSON answer (a dict) validated against `schema`.

    search=True lets Gemini run Google searches; read_urls=True lets it open
    URLs that appear in the prompt (URL context). Returns (data, sources)
    where sources are the URLs Gemini actually grounded on.
    """
    if provider() == "gemini" or search or read_urls:
        from google.genai import types

        tools = []
        if search:
            tools.append(types.Tool(google_search=types.GoogleSearch()))
        if read_urls:
            tools.append(types.Tool(url_context=types.UrlContext()))
        model = model or config.TRIAGE_MODEL
        response = _gemini().models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=tools or None,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        meta = response.candidates[0].grounding_metadata if response.candidates else None
        um = response.usage_metadata
        _record(
            model,
            # URL-context and search results are billed as input tokens.
            (getattr(um, "prompt_token_count", 0) or 0) + (getattr(um, "tool_use_prompt_token_count", 0) or 0),
            # Thinking tokens are billed as output.
            (getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0),
            searches=len(getattr(meta, "web_search_queries", None) or []) if meta else 0,
        )
        if not response.text:
            raise ValueError(f"empty response (finish reason: {_finish_reason(response)})")
        sources = []
        for chunk in (meta.grounding_chunks or []) if meta else []:
            if chunk.web and chunk.web.uri:
                sources.append({"url": chunk.web.uri, "title": chunk.web.title})
        return json.loads(response.text), sources

    import anthropic

    response = anthropic.Anthropic().beta.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    _record(config.CLAUDE_MODEL, response.usage.input_tokens, response.usage.output_tokens)
    if response.stop_reason in ("refusal", "max_tokens"):
        raise ValueError(f"stopped: {response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), []


def _finish_reason(response):
    try:
        return response.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return "unknown"
