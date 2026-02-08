"""Tests for helper / utility functions in molt_mcp.server."""

import pytest

from molt_mcp.server import _format_http_error, _format_if_match, _validate_uuid


# ── _validate_uuid ──


class TestValidateUuid:
    def test_valid_uuid(self):
        assert _validate_uuid("123e4567-e89b-12d3-a456-426614174000") is None

    def test_valid_uuid_uppercase(self):
        assert _validate_uuid("123E4567-E89B-12D3-A456-426614174000") is None

    def test_invalid_uuid_short(self):
        result = _validate_uuid("not-a-uuid")
        assert result is not None
        assert "not a valid UUID" in result

    def test_invalid_uuid_empty(self):
        result = _validate_uuid("")
        assert result is not None

    def test_invalid_uuid_no_dashes(self):
        result = _validate_uuid("123e4567e89b12d3a456426614174000")
        assert result is not None

    def test_invalid_uuid_special_chars(self):
        result = _validate_uuid("123e4567-e89b-12d3-a456-42661417400g")
        assert result is not None

    def test_custom_label_in_error(self):
        result = _validate_uuid("bad", label="workspace ID")
        assert result is not None
        assert "workspace ID" in result


# ── _format_if_match ──


class TestFormatIfMatch:
    def test_none(self):
        assert _format_if_match(None) is None

    def test_empty_string(self):
        assert _format_if_match("") is None

    def test_plain_version(self):
        assert _format_if_match("v5") == '"v5"'

    def test_already_quoted(self):
        assert _format_if_match('"v5"') == '"v5"'

    def test_double_quoted(self):
        # Edge case: user passes ""v5""
        assert _format_if_match('""v5""') == '"v5"'

    def test_preserves_content(self):
        assert _format_if_match("v123") == '"v123"'


# ── _format_http_error ──


class TestFormatHttpError:
    def test_403_on_write_operation(self):
        msg = _format_http_error(403, "", "PUT", "/docs/abc")
        assert "write key" in msg.lower()
        assert "permission denied" in msg.lower()

    def test_403_on_delete(self):
        msg = _format_http_error(403, "", "DELETE", "/docs/abc")
        assert "write key" in msg.lower()

    def test_403_on_patch(self):
        msg = _format_http_error(403, "", "PATCH", "/docs/abc")
        assert "write key" in msg.lower()

    def test_403_on_read(self):
        msg = _format_http_error(403, "", "GET", "/docs/abc")
        assert "invalid" in msg.lower()
        # Should NOT mention "write key required" for a GET
        assert "requires a write key" not in msg.lower()

    def test_404(self):
        msg = _format_http_error(404, "", "GET", "/docs/abc")
        assert "not found" in msg.lower()

    def test_409(self):
        msg = _format_http_error(409, "", "PUT", "/docs/abc")
        assert "conflict" in msg.lower()
        assert "re-read" in msg.lower()

    def test_413(self):
        msg = _format_http_error(413, "", "PUT", "/docs/abc")
        assert "5 MB" in msg

    def test_429(self):
        msg = _format_http_error(429, "", "POST", "/docs")
        assert "rate limit" in msg.lower()

    def test_400(self):
        msg = _format_http_error(400, "invalid lines param", "GET", "/docs/abc")
        assert "bad request" in msg.lower()
        assert "invalid lines param" in msg

    def test_unknown_status(self):
        msg = _format_http_error(500, "", "GET", "/health")
        assert "500" in msg

    def test_detail_appended(self):
        msg = _format_http_error(404, "Doc not found", "GET", "/docs/abc")
        assert "Doc not found" in msg
