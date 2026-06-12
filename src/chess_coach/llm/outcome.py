"""Dispatch-outcome classification for LLM calls.

A small, dependency-free vocabulary for *why* an LLM call failed, so one
word means one thing everywhere (the live coaching path, the eval harness,
the ``check`` command). Modelled on the taxonomy FITT's gateway converged
on after repeatedly confusing "host is down" with "model is cold-loading".

The key distinction: a *connect* failure means the endpoint is unreachable,
while a *read* timeout means we connected fine but the model never answered
in time — for a local Ollama that usually means it is cold-loading or
queued for VRAM, not that anything is broken.
"""

from __future__ import annotations

from enum import Enum

import httpx


class DispatchOutcome(str, Enum):
    """Classified result of a single LLM dispatch attempt."""

    OK = "ok"
    UNREACHABLE = "unreachable"
    UPSTREAM_SILENT = "upstream_silent"
    UPSTREAM_RATE_LIMITED = "upstream_rate_limited"
    UPSTREAM_CLIENT_ERROR = "upstream_client_error"
    UPSTREAM_SERVER_ERROR = "upstream_server_error"
    EMPTY_REPLY = "empty_reply"


# Human-facing, actionable one-liners. Kept terse on purpose — these reach
# the SSE error event and the CLI.
_DESCRIPTIONS: dict[DispatchOutcome, str] = {
    DispatchOutcome.OK: "OK",
    DispatchOutcome.UNREACHABLE: "Can't reach the LLM server — is it running and is the base_url correct?",
    DispatchOutcome.UPSTREAM_SILENT: (
        "The model didn't respond in time. For a local model this usually means it's "
        "cold-loading or waiting for memory — try again in a moment, or use a smaller model."
    ),
    DispatchOutcome.UPSTREAM_RATE_LIMITED: "The LLM provider is rate-limiting requests — back off and retry.",
    DispatchOutcome.UPSTREAM_CLIENT_ERROR: "The LLM provider rejected the request (auth or bad request).",
    DispatchOutcome.UPSTREAM_SERVER_ERROR: "The LLM provider hit an internal error.",
    DispatchOutcome.EMPTY_REPLY: "The model returned an empty response.",
}


def describe(outcome: DispatchOutcome) -> str:
    """A short, user-facing explanation for an outcome."""
    return _DESCRIPTIONS.get(outcome, "Unknown LLM error.")


def classify_exception(exc: BaseException) -> DispatchOutcome:
    """Map an exception raised during an LLM call to a DispatchOutcome.

    Ordering matters: HTTP status errors are checked first (they carry a
    code), then connect-failures (unreachable), then read/other timeouts
    (silent), with a server-error catch-all for everything else.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_status(exc.response.status_code)
    # A connect failure (refused, DNS, or connect timeout) means the host
    # is unreachable — distinct from a slow/cold model that accepted the
    # connection but never answered.
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return DispatchOutcome.UNREACHABLE
    if isinstance(exc, httpx.TimeoutException):
        return DispatchOutcome.UPSTREAM_SILENT
    return DispatchOutcome.UPSTREAM_SERVER_ERROR


def classify_status(status_code: int) -> DispatchOutcome:
    """Map an HTTP status code to a DispatchOutcome."""
    if status_code in (429, 529):
        return DispatchOutcome.UPSTREAM_RATE_LIMITED
    if 400 <= status_code < 500:
        return DispatchOutcome.UPSTREAM_CLIENT_ERROR
    if status_code >= 500:
        return DispatchOutcome.UPSTREAM_SERVER_ERROR
    return DispatchOutcome.OK
