"""Tests for MCP tool functions using respx to mock HTTP requests."""

import json
from unittest.mock import patch

import httpx
import pytest
import respx

import molt_mcp.server as server
from molt_mcp.server import (
    _make_request,
    append_doc,
    create_doc,
    create_workspace,
    delete_doc,
    delete_workspace,
    health_check,
    get_metrics,
    read_doc,
    read_workspace,
    update_doc,
    update_workspace,
)

BASE = "https://test.molt-md.com/api/v1"
FAKE_UUID = "123e4567-e89b-12d3-a456-426614174000"
FAKE_UUID_2 = "223e4567-e89b-12d3-a456-426614174000"


@pytest.fixture(autouse=True)
async def _reset_client():
    """
    Reset the shared HTTP client and patch module-level config
    so that respx can intercept requests at the test BASE URL.
    """
    # Close any existing client
    if server._http_client and not server._http_client.is_closed:
        await server._http_client.aclose()
    server._http_client = None

    # Patch module-level config for every test
    with (
        patch.object(server, "BASE_URL", BASE),
        patch.object(server, "API_KEY", "test-key"),
        patch.object(server, "WORKSPACE_ID", ""),
    ):
        yield

    # Cleanup after test
    if server._http_client and not server._http_client.is_closed:
        await server._http_client.aclose()
    server._http_client = None


# ── _make_request ──


class TestMakeRequest:
    @respx.mock
    async def test_json_response(self):
        respx.get(f"{BASE}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        data, headers, error = await _make_request("GET", "/health")
        assert error is None
        assert data == {"status": "ok"}

    @respx.mock
    async def test_204_no_content(self):
        respx.delete(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(204)
        )
        data, headers, error = await _make_request("DELETE", f"/docs/{FAKE_UUID}")
        assert error is None
        assert data == {"success": True}

    @respx.mock
    async def test_text_response(self):
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                200,
                text="# Hello",
                headers={"content-type": "text/markdown"},
            )
        )
        data, headers, error = await _make_request("GET", f"/docs/{FAKE_UUID}")
        assert error is None
        assert data == "# Hello"

    @respx.mock
    async def test_403_error_on_write(self):
        respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                403,
                json={"error": "forbidden", "message": "Write key required"},
            )
        )
        data, headers, error = await _make_request(
            "PUT", f"/docs/{FAKE_UUID}", content="new content"
        )
        assert data is None
        assert error is not None
        assert "write key" in error.lower()

    @respx.mock
    async def test_404_error(self):
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                404,
                json={"error": "not_found", "message": "Document not found"},
            )
        )
        data, _, error = await _make_request("GET", f"/docs/{FAKE_UUID}")
        assert data is None
        assert "not found" in error.lower()

    @respx.mock
    async def test_409_conflict(self):
        respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                409,
                json={"error": "conflict", "current_version": 6},
            )
        )
        data, _, error = await _make_request(
            "PUT", f"/docs/{FAKE_UUID}", content="x"
        )
        assert data is None
        assert "conflict" in error.lower()

    @respx.mock
    async def test_network_error(self):
        respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("refused"))
        data, _, error = await _make_request("GET", "/health")
        assert data is None
        assert "request error" in error.lower()


# ── health_check ──


class TestHealthCheck:
    @respx.mock
    async def test_success(self):
        respx.get(f"{BASE}/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        result = await health_check()
        assert json.loads(result) == {"status": "ok"}

    @respx.mock
    async def test_failure(self):
        respx.get(f"{BASE}/health").mock(
            side_effect=httpx.ConnectError("down")
        )
        result = await health_check()
        assert "Health check failed" in result


# ── get_metrics ──


class TestGetMetrics:
    @respx.mock
    async def test_success(self):
        respx.get(f"{BASE}/metrics").mock(
            return_value=httpx.Response(200, json={"documents": 42, "workspaces": 5})
        )
        result = await get_metrics()
        data = json.loads(result)
        assert data["documents"] == 42
        assert data["workspaces"] == 5


# ── read_doc ──


class TestReadDoc:
    @respx.mock
    async def test_json_format(self):
        body = {"id": FAKE_UUID, "content": "# Hello", "version": 1}
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json=body)
        )
        result = await read_doc(FAKE_UUID)
        assert json.loads(result) == body

    @respx.mock
    async def test_markdown_format(self):
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                200,
                text="# Hello World",
                headers={
                    "content-type": "text/markdown",
                    "etag": '"v3"',
                },
            )
        )
        result = await read_doc(FAKE_UUID, as_markdown=True)
        assert "# Hello World" in result
        assert "version:" in result

    @respx.mock
    async def test_truncated_response(self):
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                200,
                text="# Title",
                headers={
                    "content-type": "text/markdown",
                    "x-molt-truncated": "true",
                    "x-molt-total-lines": "50",
                },
            )
        )
        result = await read_doc(FAKE_UUID, lines=1, as_markdown=True)
        assert "truncated" in result
        assert "50" in result

    async def test_invalid_uuid(self):
        result = await read_doc("not-valid")
        assert "not a valid UUID" in result

    @respx.mock
    async def test_lines_param_sent(self):
        route = respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                200,
                text="# Line 1",
                headers={"content-type": "text/markdown"},
            )
        )
        await read_doc(FAKE_UUID, lines=5, as_markdown=True)
        assert route.called
        assert "lines=5" in str(route.calls[0].request.url)

    @respx.mock
    async def test_not_found(self):
        respx.get(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                404,
                json={"error": "not_found", "message": "Document not found"},
            )
        )
        result = await read_doc(FAKE_UUID)
        assert "Failed to read document" in result
        assert "not found" in result.lower()


# ── read_workspace ──


class TestReadWorkspace:
    @respx.mock
    async def test_success(self):
        body = {
            "id": FAKE_UUID,
            "name": "Project",
            "entries": [],
            "version": 1,
        }
        respx.get(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json=body)
        )
        result = await read_workspace(FAKE_UUID)
        assert json.loads(result) == body

    @respx.mock
    async def test_preview_lines_param(self):
        route = respx.get(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"id": FAKE_UUID, "name": "X", "entries": [], "version": 1})
        )
        await read_workspace(FAKE_UUID, preview_lines=2)
        assert "preview_lines=2" in str(route.calls[0].request.url)

    async def test_invalid_uuid(self):
        result = await read_workspace("bad-id")
        assert "not a valid UUID" in result


# ── create_doc ──


class TestCreateDoc:
    @respx.mock
    async def test_with_content(self):
        resp_body = {
            "id": FAKE_UUID,
            "write_key": "wk_abc",
            "read_key": "rk_xyz",
        }
        route = respx.post(f"{BASE}/docs").mock(
            return_value=httpx.Response(201, json=resp_body)
        )
        result = await create_doc(content="# New Doc")
        data = json.loads(result)
        assert data["id"] == FAKE_UUID
        assert data["write_key"] == "wk_abc"
        # Verify the body was sent correctly
        req_body = json.loads(route.calls[0].request.content)
        assert req_body["content"] == "# New Doc"

    @respx.mock
    async def test_empty_doc(self):
        respx.post(f"{BASE}/docs").mock(
            return_value=httpx.Response(
                201,
                json={"id": FAKE_UUID, "write_key": "wk", "read_key": "rk"},
            )
        )
        result = await create_doc()
        assert FAKE_UUID in result

    @respx.mock
    async def test_rate_limited(self):
        respx.post(f"{BASE}/docs").mock(
            return_value=httpx.Response(
                429,
                json={"error": "rate_limited", "message": "Too many requests"},
            )
        )
        result = await create_doc(content="x")
        assert "Failed to create document" in result
        assert "rate limit" in result.lower()


# ── update_doc ──


class TestUpdateDoc:
    @respx.mock
    async def test_success(self):
        respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 2})
        )
        result = await update_doc(FAKE_UUID, content="# Updated")
        data = json.loads(result)
        assert data["success"] is True
        assert data["version"] == 2

    @respx.mock
    async def test_with_if_match(self):
        route = respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 3})
        )
        await update_doc(FAKE_UUID, content="new", if_match="v2")
        sent_headers = route.calls[0].request.headers
        assert sent_headers["if-match"] == '"v2"'

    @respx.mock
    async def test_conflict(self):
        respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                409,
                json={"error": "conflict", "current_version": 5},
            )
        )
        result = await update_doc(FAKE_UUID, content="x", if_match="v4")
        assert "Failed to update document" in result
        assert "conflict" in result.lower()

    @respx.mock
    async def test_forbidden_read_key(self):
        respx.put(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                403,
                json={"error": "forbidden", "message": "Write key required"},
            )
        )
        result = await update_doc(FAKE_UUID, content="x")
        assert "write key" in result.lower()

    async def test_invalid_uuid(self):
        result = await update_doc("bad", content="x")
        assert "not a valid UUID" in result


# ── append_doc ──


class TestAppendDoc:
    @respx.mock
    async def test_success(self):
        respx.patch(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 3})
        )
        result = await append_doc(FAKE_UUID, content="## New Section")
        data = json.loads(result)
        assert data["success"] is True

    @respx.mock
    async def test_with_if_match_quoted(self):
        route = respx.patch(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 4})
        )
        # Pass already-quoted value
        await append_doc(FAKE_UUID, content="text", if_match='"v3"')
        sent_headers = route.calls[0].request.headers
        assert sent_headers["if-match"] == '"v3"'

    async def test_invalid_uuid(self):
        result = await append_doc("nope", content="x")
        assert "not a valid UUID" in result


# ── delete_doc ──


class TestDeleteDoc:
    @respx.mock
    async def test_success(self):
        respx.delete(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(204)
        )
        result = await delete_doc(FAKE_UUID)
        assert "deleted successfully" in result.lower()

    @respx.mock
    async def test_forbidden(self):
        respx.delete(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                403,
                json={"error": "forbidden", "message": "Write key required"},
            )
        )
        result = await delete_doc(FAKE_UUID)
        assert "Failed to delete document" in result
        assert "write key" in result.lower()

    @respx.mock
    async def test_not_found(self):
        respx.delete(f"{BASE}/docs/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                404,
                json={"error": "not_found", "message": "Document not found"},
            )
        )
        result = await delete_doc(FAKE_UUID)
        assert "not found" in result.lower()

    async def test_invalid_uuid(self):
        result = await delete_doc("x")
        assert "not a valid UUID" in result


# ── create_workspace ──


class TestCreateWorkspace:
    @respx.mock
    async def test_success(self):
        resp_body = {"id": FAKE_UUID, "write_key": "wk", "read_key": "rk"}
        respx.post(f"{BASE}/workspaces").mock(
            return_value=httpx.Response(201, json=resp_body)
        )
        result = await create_workspace(name="My Project")
        data = json.loads(result)
        assert data["id"] == FAKE_UUID

    @respx.mock
    async def test_with_entries(self):
        route = respx.post(f"{BASE}/workspaces").mock(
            return_value=httpx.Response(
                201,
                json={"id": FAKE_UUID, "write_key": "wk", "read_key": "rk"},
            )
        )
        entries = [{"type": "md", "id": FAKE_UUID_2, "key": "dockey"}]
        await create_workspace(name="Proj", entries=entries)
        req_body = json.loads(route.calls[0].request.content)
        assert req_body["entries"] == entries


# ── update_workspace ──


class TestUpdateWorkspace:
    @respx.mock
    async def test_success(self):
        respx.put(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 2})
        )
        result = await update_workspace(
            FAKE_UUID, name="Updated", entries=[]
        )
        data = json.loads(result)
        assert data["success"] is True

    @respx.mock
    async def test_with_if_match(self):
        route = respx.put(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(200, json={"success": True, "version": 2})
        )
        await update_workspace(
            FAKE_UUID, name="X", entries=[], if_match="v1"
        )
        sent_headers = route.calls[0].request.headers
        assert sent_headers["if-match"] == '"v1"'

    async def test_invalid_uuid(self):
        result = await update_workspace("bad", name="X", entries=[])
        assert "not a valid UUID" in result


# ── delete_workspace ──


class TestDeleteWorkspace:
    @respx.mock
    async def test_success(self):
        respx.delete(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(204)
        )
        result = await delete_workspace(FAKE_UUID)
        assert "deleted successfully" in result.lower()

    @respx.mock
    async def test_forbidden(self):
        respx.delete(f"{BASE}/workspaces/{FAKE_UUID}").mock(
            return_value=httpx.Response(
                403,
                json={"error": "forbidden", "message": "Write key required"},
            )
        )
        result = await delete_workspace(FAKE_UUID)
        assert "write key" in result.lower()

    async def test_invalid_uuid(self):
        result = await delete_workspace("nope")
        assert "not a valid UUID" in result
