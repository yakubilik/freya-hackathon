"""Model backends for the readers.

Claude through ``claude_agent_sdk.query`` (no tools, ``permission_mode="dontAsk"``, model from ``BUILDER_MODEL``,
default ``claude-opus-5-5``). R4 backend order: the OpenAI API over plain HTTPS when ``OPENAI_API_KEY`` is set
(model ``gpt-6-astra``), else the ``codex`` CLI when installed, else a second Claude process logged as
``assurance: single model family``.

Every call takes ``timeout_s`` and an optional outer ``Deadline``; the effective timeout is the smaller.
Each call returns ``(text, usage)`` with ``usage = {model, purpose, tokens, seconds, backend, ...}`` for the trace.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
DEFAULT_R4_MODEL = os.environ.get("R4_MODEL", "gpt-6-astra")   # the second family's model, as BUILDER_MODEL is Claude's
OPENAI_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")


class ModelCallError(Exception):
    pass


class DeadlineExceeded(ModelCallError):
    pass


class Deadline:
    """An outer deadline shared by every call of a run."""

    def __init__(self, seconds: float):
        self.seconds = float(seconds)
        self.t0 = time.monotonic()

    def remaining(self) -> float:
        return max(0.0, self.seconds - (time.monotonic() - self.t0))

    def expired(self) -> bool:
        return self.remaining() <= 0

    def elapsed(self) -> float:
        return time.monotonic() - self.t0


def _effective_timeout(timeout_s: float, deadline: Deadline | None) -> float:
    t = float(timeout_s)
    if deadline is not None:
        t = min(t, deadline.remaining())
    if t <= 1:
        raise DeadlineExceeded("no time left before the outer deadline")
    return t


def claude_model() -> str:
    return os.environ.get("BUILDER_MODEL", DEFAULT_CLAUDE_MODEL)


async def _claude_async(prompt: str, system: str | None, model: str, timeout_s: float, effort: str | None) -> tuple[str, dict]:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock, query

    kwargs = dict(model=model, tools=[], allowed_tools=[], permission_mode="dontAsk", max_turns=1,
                  cwd=tempfile.gettempdir(), env={"CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
                           "CLAUDE_CODE_MAX_OUTPUT_TOKENS": os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS", "64000")})
    if system:
        kwargs["system_prompt"] = system
    if effort:
        kwargs["effort"] = effort
    options = ClaudeAgentOptions(**kwargs)
    texts: list[str] = []
    result: ResultMessage | None = None

    async def consume():
        nonlocal result
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        texts.append(block.text)
            elif isinstance(message, ResultMessage):
                result = message

    await asyncio.wait_for(consume(), timeout=timeout_s)
    usage = {}
    if result is not None:
        u = result.usage or {}
        usage = {"input_tokens": u.get("input_tokens", 0), "output_tokens": u.get("output_tokens", 0),
                 "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0),
                 "cache_read_input_tokens": u.get("cache_read_input_tokens", 0),
                 "cost_usd": result.total_cost_usd, "is_error": result.is_error, "session_id": result.session_id}
        if result.is_error and not texts:
            raise ModelCallError(f"claude result error: {result.result!r}")
        if not texts and result.result:
            texts.append(result.result)
    text = "\n".join(texts).strip()
    if not text:
        raise ModelCallError("claude returned no text")
    return text, usage


def claude_text(prompt: str, *, system: str | None = None, model: str | None = None, timeout_s: float = 600,
                deadline: Deadline | None = None, purpose: str = "r1", effort: str | None = None) -> tuple[str, dict]:
    model = model or claude_model()
    effort = effort or os.environ.get("BUILDER_EFFORT", "high")
    t = _effective_timeout(timeout_s, deadline)
    start = time.monotonic()
    try:
        text, u = asyncio.run(_claude_async(prompt, system, model, t, effort))
    except asyncio.TimeoutError as e:
        raise ModelCallError(f"claude call timed out after {t:.0f}s") from e
    seconds = time.monotonic() - start
    tokens = sum(u.get(k, 0) or 0 for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    usage = {"model": model, "purpose": purpose, "tokens": tokens, "seconds": round(seconds, 1), "backend": "claude", "detail": u}
    return text, usage


def _http_json(url: str, payload: dict, headers: dict, timeout_s: float) -> tuple[int, dict | str]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, body


def openai_text(prompt: str, *, system: str | None = None, model: str = DEFAULT_R4_MODEL, timeout_s: float = 600,
                deadline: Deadline | None = None, purpose: str = "r4", effort: str = "high") -> tuple[str, dict]:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ModelCallError("OPENAI_API_KEY not set")
    t = _effective_timeout(timeout_s, deadline)
    headers = {"Authorization": f"Bearer {key}"}
    start = time.monotonic()
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    status, body = _http_json(f"{OPENAI_URL}/responses", {"model": model, "input": messages, "reasoning": {"effort": effort}}, headers, t)
    text, usage_detail = "", {}
    if status == 200 and isinstance(body, dict):
        for item in body.get("output", []):
            for c in item.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    text += c["text"]
        usage_detail = body.get("usage", {}) or {}
    elif status in (400, 404):
        # Older-style deployments: chat completions.
        status, body = _http_json(f"{OPENAI_URL}/chat/completions", {"model": model, "messages": messages, "reasoning_effort": effort}, headers, t)
        if status == 200 and isinstance(body, dict):
            text = (body.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            usage_detail = body.get("usage", {}) or {}
    if status != 200:
        raise ModelCallError(f"openai status {status}: {str(body)[:300]}")
    if not text.strip():
        raise ModelCallError("openai returned no text")
    seconds = time.monotonic() - start
    tokens = (usage_detail.get("total_tokens") or (usage_detail.get("input_tokens", 0) + usage_detail.get("output_tokens", 0))
              or (usage_detail.get("prompt_tokens", 0) + usage_detail.get("completion_tokens", 0)))
    return text.strip(), {"model": model, "purpose": purpose, "tokens": tokens, "seconds": round(seconds, 1), "backend": "openai", "detail": usage_detail}


def codex_available() -> bool:
    return shutil.which("codex") is not None


def codex_text(prompt: str, *, system: str | None = None, model: str = DEFAULT_R4_MODEL, timeout_s: float = 600,
               deadline: Deadline | None = None, purpose: str = "r4", effort: str = "high") -> tuple[str, dict]:
    if not codex_available():
        raise ModelCallError("codex CLI not installed")
    t = _effective_timeout(timeout_s, deadline)
    full = (system + "\n\n" if system else "") + prompt
    start = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        out_file = os.path.join(tmp, "last.txt")
        cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "-m", model, "-c", f"model_reasoning_effort={effort}",
               "-o", out_file, full]
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=t, cwd=tmp)
        except subprocess.TimeoutExpired as e:
            raise ModelCallError(f"codex timed out after {t:.0f}s") from e
        text = ""
        if os.path.exists(out_file):
            text = open(out_file).read().strip()
        if not text:
            text = proc.stdout.strip()
        if proc.returncode != 0 and not text:
            raise ModelCallError(f"codex exit {proc.returncode}: {proc.stderr[-500:]}")
        m = re.search(r"tokens used[:\s]+([\d,.]+)\s*([kKmM]?)", proc.stderr + proc.stdout, re.I)
    seconds = time.monotonic() - start
    if m:
        num = float(m.group(1).replace(",", ""))
        tokens = int(num * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1))
    else:
        tokens = (len(full) + len(text)) // 4
    return text, {"model": model, "purpose": purpose, "tokens": tokens, "seconds": round(seconds, 1), "backend": "codex",
                  "tokens_estimated": m is None}


def r4_backend() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if codex_available():
        return "codex"
    return "claude"


def r4_text(prompt: str, *, system: str | None = None, timeout_s: float = 600, deadline: Deadline | None = None,
            purpose: str = "r4") -> tuple[str, dict]:
    """Blind auditor call on the strongest available second family; falls through on failure.
    Effort from ``R4_EFFORT`` (default medium: high measured 596 s on Brief A, over the 8-minute R4 window)."""
    effort = os.environ.get("R4_EFFORT", "medium")
    errors = []
    order = [r4_backend()]
    for b in ("codex", "claude"):
        if b not in order:
            order.append(b)
    if "openai" in order and not os.environ.get("OPENAI_API_KEY"):
        order.remove("openai")
    if "codex" in order and not codex_available():
        order.remove("codex")
    for backend in order:
        try:
            if backend == "openai":
                text, usage = openai_text(prompt, system=system, timeout_s=timeout_s, deadline=deadline, purpose=purpose, effort=effort)
            elif backend == "codex":
                text, usage = codex_text(prompt, system=system, timeout_s=timeout_s, deadline=deadline, purpose=purpose, effort=effort)
            else:
                text, usage = claude_text(prompt, system=system, timeout_s=timeout_s, deadline=deadline, purpose=purpose)
                usage["assurance"] = "single model family"
            usage["assurance"] = usage.get("assurance", "two model families")
            if errors:
                usage["fallback_from"] = errors
            return text, usage
        except DeadlineExceeded:
            raise
        except ModelCallError as e:
            errors.append(f"{backend}: {e}")
    raise ModelCallError("every R4 backend failed: " + "; ".join(errors))
