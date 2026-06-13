"""Tests for chess_coach.llm.outcome — dispatch-outcome classification."""

from __future__ import annotations

import httpx
import pytest

from chess_coach.llm.outcome import (
    DispatchOutcome,
    classify_exception,
    classify_status,
    describe,
)


class TestClassifyStatus:
    @pytest.mark.parametrize("code", [429, 529])
    def test_rate_limited(self, code: int) -> None:
        assert classify_status(code) is DispatchOutcome.UPSTREAM_RATE_LIMITED

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
    def test_client_error(self, code: int) -> None:
        assert classify_status(code) is DispatchOutcome.UPSTREAM_CLIENT_ERROR

    @pytest.mark.parametrize("code", [500, 502, 503])
    def test_server_error(self, code: int) -> None:
        assert classify_status(code) is DispatchOutcome.UPSTREAM_SERVER_ERROR

    @pytest.mark.parametrize("code", [200, 201, 204])
    def test_success_codes(self, code: int) -> None:
        assert classify_status(code) is DispatchOutcome.OK


class TestClassifyException:
    def _status_error(self, code: int) -> httpx.HTTPStatusError:
        request = httpx.Request("POST", "http://x/api")
        response = httpx.Response(code, request=request)
        return httpx.HTTPStatusError("boom", request=request, response=response)

    def test_connect_error_is_unreachable(self) -> None:
        exc = httpx.ConnectError("Connection refused")
        assert classify_exception(exc) is DispatchOutcome.UNREACHABLE

    def test_connect_timeout_is_unreachable(self) -> None:
        # A connect timeout means we never reached the host — distinct from a
        # read timeout where the host accepted us but the model was slow.
        exc = httpx.ConnectTimeout("timed out connecting")
        assert classify_exception(exc) is DispatchOutcome.UNREACHABLE

    def test_read_timeout_is_silent(self) -> None:
        # Connected fine, model never answered: cold-loading / VRAM queue.
        exc = httpx.ReadTimeout("read timed out")
        assert classify_exception(exc) is DispatchOutcome.UPSTREAM_SILENT

    def test_pool_timeout_is_silent(self) -> None:
        exc = httpx.PoolTimeout("pool timed out")
        assert classify_exception(exc) is DispatchOutcome.UPSTREAM_SILENT

    def test_status_429_is_rate_limited(self) -> None:
        assert classify_exception(self._status_error(429)) is DispatchOutcome.UPSTREAM_RATE_LIMITED

    def test_status_400_is_client_error(self) -> None:
        assert classify_exception(self._status_error(400)) is DispatchOutcome.UPSTREAM_CLIENT_ERROR

    def test_status_500_is_server_error(self) -> None:
        assert classify_exception(self._status_error(500)) is DispatchOutcome.UPSTREAM_SERVER_ERROR

    def test_unknown_exception_is_server_error(self) -> None:
        assert classify_exception(RuntimeError("???")) is DispatchOutcome.UPSTREAM_SERVER_ERROR

    def test_subprocess_timeout_is_silent(self) -> None:
        import subprocess

        exc = subprocess.TimeoutExpired(cmd="judge", timeout=5.0)
        assert classify_exception(exc) is DispatchOutcome.UPSTREAM_SILENT

    def test_missing_executable_is_unreachable(self) -> None:
        assert classify_exception(FileNotFoundError("no such file")) is DispatchOutcome.UNREACHABLE


class TestDescribe:
    @pytest.mark.parametrize("outcome", list(DispatchOutcome))
    def test_every_outcome_has_a_nonempty_description(self, outcome: DispatchOutcome) -> None:
        assert describe(outcome).strip()
