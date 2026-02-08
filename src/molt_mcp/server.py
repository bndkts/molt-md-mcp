"""molt-md MCP Server - Encrypted markdown document hosting API wrapper."""

import json
import logging
import os
import re
import sys
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

# Configure logging to stderr (stdout is reserved for MCP protocol)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("molt-mcp")

# Initialize FastMCP server
mcp = FastMCP("molt-md")

# Configuration from environment
WORKSPACE_ID = os.getenv("MOLT_WORKSPACE_ID", "")
API_KEY = os.getenv("MOLT_API_KEY", "")
BASE_URL = os.getenv("MOLT_BASE_URL", "https://molt-md.com/api/v1")

# UUID validation pattern
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

# Shared HTTP client (created lazily, reused for connection pooling)
_http_client: Optional[httpx.AsyncClient] = None


def _validate_uuid(value: str, label: str = "ID") -> Optional[str]:
    """Validate a UUID string. Returns an error message if invalid, None if valid."""
    if not _UUID_RE.match(value):
        return f"Invalid {label}: '{value}' is not a valid UUID."
    return None


def _format_if_match(if_match: Optional[str]) -> Optional[str]:
    """Normalize an If-Match value into a properly quoted ETag."""
    if not if_match:
        return None
    # Strip any existing quotes and re-wrap cleanly
    clean = if_match.strip('"')
    return f'"{clean}"'


def _format_http_error(status: int, detail: str, method: str, path: str) -> str:
    """Return a human-readable, LLM-friendly error message for an HTTP status code."""
    suffix = f" ({detail})" if detail else ""

    messages: dict[int, str] = {
        400: f"Bad request{suffix}. Check that all parameters are valid.",
        403: (
            f"Permission denied{suffix}. "
            "This operation requires a write key, but a read key was provided. "
            "Use a write key in the MOLT_API_KEY environment variable."
            if method in ("PUT", "PATCH", "DELETE")
            else f"Permission denied{suffix}. The provided key is invalid."
        ),
        404: (
            f"Not found{suffix}. The document or workspace does not exist, "
            "or is not accessible through the current workspace."
        ),
        409: (
            f"Version conflict{suffix}. The document was modified by another client. "
            "Re-read the document to get the latest version, then retry."
        ),
        413: f"Content too large{suffix}. Maximum size is 5 MB.",
        429: f"Rate limited{suffix}. Too many requests — wait and retry.",
    }
    return messages.get(status, f"HTTP {status}{suffix}")


async def _get_http_client() -> httpx.AsyncClient:
    """Get or create a shared HTTP client with connection pooling."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        headers = {"X-Molt-Key": API_KEY}
        if WORKSPACE_ID:
            headers["X-Molt-Workspace"] = WORKSPACE_ID
        _http_client = httpx.AsyncClient(
            base_url=BASE_URL, headers=headers, timeout=30.0
        )
    return _http_client


async def _make_request(
    method: str, path: str, **kwargs
) -> tuple[Any, dict[str, str], Optional[str]]:
    """
    Make an HTTP request and return (response_data, response_headers, error_message).
    Returns (data, headers, None) on success, (None, {}, error_message) on failure.
    """
    try:
        client = await _get_http_client()
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()

        resp_headers = dict(response.headers)

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json(), resp_headers, None
        elif response.status_code == 204:
            return {"success": True}, resp_headers, None
        else:
            return response.text, resp_headers, None

    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        detail = ""
        try:
            error_data = e.response.json()
            detail = error_data.get("message", "")
        except Exception:
            pass

        error_msg = _format_http_error(status, detail, method, path)
        logger.error(f"Request failed: {error_msg}")
        return None, {}, error_msg

    except Exception as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(error_msg)
        return None, {}, error_msg


# ── Read-only tools (available with both read and write keys) ──


@mcp.tool()
async def health_check() -> str:
    """Check if the molt-md API is available and responding."""
    data, _, error = await _make_request("GET", "/health")
    if error:
        return f"Health check failed: {error}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_metrics() -> str:
    """Get database statistics (total documents and workspaces count)."""
    data, _, error = await _make_request("GET", "/metrics")
    if error:
        return f"Failed to get metrics: {error}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def read_doc(
    doc_id: str,
    lines: Optional[int] = None,
    as_markdown: bool = False,
) -> str:
    """
    Read a document's decrypted content.

    Args:
        doc_id: UUID of the document to read
        lines: Optional - return only the first N lines (for previews)
        as_markdown: If True, return plain markdown; if False, return JSON with metadata
    """
    if err := _validate_uuid(doc_id, "document ID"):
        return err

    headers = {"Accept": "text/markdown" if as_markdown else "application/json"}
    params = {"lines": lines} if lines else {}

    data, resp_headers, error = await _make_request(
        "GET", f"/docs/{doc_id}", headers=headers, params=params
    )
    if error:
        return f"Failed to read document: {error}"

    if isinstance(data, str):
        # For markdown responses, append version and truncation metadata
        meta_parts: list[str] = []
        if etag := resp_headers.get("etag"):
            meta_parts.append(f"version: {etag}")
        if resp_headers.get("x-molt-truncated") == "true":
            total = resp_headers.get("x-molt-total-lines", "?")
            meta_parts.append(f"truncated (total lines: {total})")
        if meta_parts:
            return f"{data}\n\n<!-- {', '.join(meta_parts)} -->"
        return data
    return json.dumps(data, indent=2)


@mcp.tool()
async def read_workspace(
    workspace_id: str,
    preview_lines: Optional[int] = None,
) -> str:
    """
    Read a workspace's decrypted content (name and entries).

    Args:
        workspace_id: UUID of the workspace to read
        preview_lines: Optional - include preview of first N lines for each document entry
    """
    if err := _validate_uuid(workspace_id, "workspace ID"):
        return err

    params = {"preview_lines": preview_lines} if preview_lines else {}

    data, _, error = await _make_request(
        "GET", f"/workspaces/{workspace_id}", params=params
    )
    if error:
        return f"Failed to read workspace: {error}"

    return json.dumps(data, indent=2)


# ── Write tools ──


@mcp.tool()
async def create_doc(content: str = "") -> str:
    """
    Create a new encrypted document.
    Returns the document ID and both write and read keys.
    IMPORTANT: Save these keys - they are shown only once!

    Args:
        content: Initial markdown content for the document (optional)
    """
    json_body = {"content": content} if content else {}
    data, _, error = await _make_request("POST", "/docs", json=json_body)
    if error:
        return f"Failed to create document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def update_doc(
    doc_id: str,
    content: str,
    if_match: Optional[str] = None,
) -> str:
    """
    Replace a document's entire content with new content.
    Requires write key. The API will return 403 if a read key is used.

    Args:
        doc_id: UUID of the document to update
        content: New markdown content (replaces existing content)
        if_match: Optional - version ETag (e.g., 'v5') to prevent conflicts
    """
    if err := _validate_uuid(doc_id, "document ID"):
        return err

    headers = {"Content-Type": "text/markdown"}
    etag = _format_if_match(if_match)
    if etag:
        headers["If-Match"] = etag

    data, _, error = await _make_request(
        "PUT", f"/docs/{doc_id}", headers=headers, content=content
    )
    if error:
        return f"Failed to update document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def append_doc(
    doc_id: str,
    content: str,
    if_match: Optional[str] = None,
) -> str:
    """
    Append content to the end of a document (separated by newline).
    Requires write key. The API will return 403 if a read key is used.

    Args:
        doc_id: UUID of the document to append to
        content: Markdown content to append
        if_match: Optional - version ETag (e.g., 'v5') to prevent conflicts
    """
    if err := _validate_uuid(doc_id, "document ID"):
        return err

    headers = {"Content-Type": "text/markdown"}
    etag = _format_if_match(if_match)
    if etag:
        headers["If-Match"] = etag

    data, _, error = await _make_request(
        "PATCH", f"/docs/{doc_id}", headers=headers, content=content
    )
    if error:
        return f"Failed to append to document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def delete_doc(doc_id: str) -> str:
    """
    Permanently delete a document. This action cannot be undone.
    Requires write key. The API will return 403 if a read key is used.

    Args:
        doc_id: UUID of the document to delete
    """
    if err := _validate_uuid(doc_id, "document ID"):
        return err

    _, _, error = await _make_request("DELETE", f"/docs/{doc_id}")
    if error:
        return f"Failed to delete document: {error}"

    return "Document deleted successfully."


@mcp.tool()
async def create_workspace(
    name: str,
    entries: Optional[list[dict[str, str]]] = None,
) -> str:
    """
    Create a new encrypted workspace to bundle multiple documents.
    Returns the workspace ID and both write and read keys.
    IMPORTANT: Save these keys - they are shown only once!

    Args:
        name: Human-readable workspace name
        entries: Optional list of entries. Each entry should have:
                 - type: "md" for documents or "workspace" for sub-workspaces
                 - id: UUID of the document/workspace
                 - key: Write or read key for the item
    """
    json_body = {"name": name, "entries": entries or []}
    data, _, error = await _make_request("POST", "/workspaces", json=json_body)
    if error:
        return f"Failed to create workspace: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def update_workspace(
    workspace_id: str,
    name: str,
    entries: list[dict[str, str]],
    if_match: Optional[str] = None,
) -> str:
    """
    Replace a workspace's entire content (name and entries).
    Requires write key. The API will return 403 if a read key is used.

    Args:
        workspace_id: UUID of the workspace to update
        name: New workspace name
        entries: New list of entries (replaces existing entries)
        if_match: Optional - version ETag (e.g., 'v1') to prevent conflicts
    """
    if err := _validate_uuid(workspace_id, "workspace ID"):
        return err

    headers = {"Content-Type": "application/json"}
    etag = _format_if_match(if_match)
    if etag:
        headers["If-Match"] = etag

    json_body = {"name": name, "entries": entries}
    data, _, error = await _make_request(
        "PUT", f"/workspaces/{workspace_id}", json=json_body, headers=headers
    )
    if error:
        return f"Failed to update workspace: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def delete_workspace(workspace_id: str) -> str:
    """
    Permanently delete a workspace. This action cannot be undone.
    Referenced documents and sub-workspaces are NOT deleted.
    Requires write key. The API will return 403 if a read key is used.

    Args:
        workspace_id: UUID of the workspace to delete
    """
    if err := _validate_uuid(workspace_id, "workspace ID"):
        return err

    _, _, error = await _make_request("DELETE", f"/workspaces/{workspace_id}")
    if error:
        return f"Failed to delete workspace: {error}"

    return "Workspace deleted successfully."


def main():
    """Main entry point for the MCP server."""
    if not API_KEY:
        logger.error("MOLT_API_KEY environment variable is required")
        sys.exit(1)

    logger.info("Starting molt-md MCP server")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Workspace ID: {WORKSPACE_ID or 'Not set (accessing docs directly)'}")

    mcp.run()


if __name__ == "__main__":
    main()
