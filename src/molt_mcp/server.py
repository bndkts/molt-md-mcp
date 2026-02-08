"""molt-md MCP Server - Encrypted markdown document hosting API wrapper."""

import asyncio
import json
import logging
import os
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

# Global state for key type detection
_is_write_key: Optional[bool] = None


async def _get_http_client() -> httpx.AsyncClient:
    """Get configured HTTP client with base URL and auth header."""
    headers = {"X-Molt-Key": API_KEY}
    if WORKSPACE_ID:
        headers["X-Molt-Workspace"] = WORKSPACE_ID
    return httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=30.0)


async def _detect_key_type() -> bool:
    """
    Detect if the provided key is a write key or read key.
    Returns True for write key, False for read key.
    """
    global _is_write_key
    if _is_write_key is not None:
        return _is_write_key

    # Try to list metrics (doesn't require auth) to validate base URL
    try:
        async with await _get_http_client() as client:
            # Create a minimal test document to check write access
            response = await client.post("/docs", json={"content": "test"})
            if response.status_code == 201:
                # Cleanup test document
                test_id = response.json()["id"]
                test_write_key = response.json()["write_key"]
                await client.delete(
                    f"/docs/{test_id}", headers={"X-Molt-Key": test_write_key}
                )
                _is_write_key = True
                logger.info("Detected write key - all tools enabled")
                return True
    except Exception as e:
        logger.warning(f"Key detection failed: {e}")

    # If creation fails, assume read key
    _is_write_key = False
    logger.info("Using read-only mode - write operations disabled")
    return False


async def _make_request(
    method: str, path: str, **kwargs
) -> tuple[Optional[Any], Optional[str]]:
    """
    Make an HTTP request and return (response_data, error_message).
    Returns (data, None) on success, (None, error_message) on failure.
    """
    try:
        async with await _get_http_client() as client:
            response = await client.request(method, path, **kwargs)
            response.raise_for_status()

            # Handle different content types
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                return response.json(), None
            elif response.status_code == 204:
                return {"success": True}, None
            else:
                return response.text, None

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP {e.response.status_code}"
        try:
            error_data = e.response.json()
            error_msg += f": {error_data.get('error', 'unknown')} - {error_data.get('message', str(e))}"
        except Exception:
            error_msg += f": {str(e)}"
        logger.error(f"Request failed: {error_msg}")
        return None, error_msg

    except Exception as e:
        error_msg = f"Request error: {str(e)}"
        logger.error(error_msg)
        return None, error_msg


# Read-only tools (available for both read and write keys)


@mcp.tool()
async def health_check() -> str:
    """Check if the molt-md API is available and responding."""
    data, error = await _make_request("GET", "/health")
    if error:
        return f"Health check failed: {error}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def get_metrics() -> str:
    """Get database statistics (total documents and workspaces count)."""
    data, error = await _make_request("GET", "/metrics")
    if error:
        return f"Failed to get metrics: {error}"
    return json.dumps(data, indent=2)


@mcp.tool()
async def read_doc(doc_id: str, lines: Optional[int] = None, as_markdown: bool = False) -> str:
    """
    Read a document's decrypted content.
    
    Args:
        doc_id: UUID of the document to read
        lines: Optional - return only the first N lines (for previews)
        as_markdown: If True, return plain markdown; if False, return JSON with metadata
    """
    headers = {"Accept": "text/markdown" if as_markdown else "application/json"}
    params = {"lines": lines} if lines else {}

    data, error = await _make_request("GET", f"/docs/{doc_id}", headers=headers, params=params)
    if error:
        return f"Failed to read document: {error}"

    if isinstance(data, str):
        return data
    return json.dumps(data, indent=2)


@mcp.tool()
async def read_workspace(workspace_id: str, preview_lines: Optional[int] = None) -> str:
    """
    Read a workspace's decrypted content (name and entries).
    
    Args:
        workspace_id: UUID of the workspace to read
        preview_lines: Optional - include preview of first N lines for each document entry
    """
    params = {"preview_lines": preview_lines} if preview_lines else {}

    data, error = await _make_request("GET", f"/workspaces/{workspace_id}", params=params)
    if error:
        return f"Failed to read workspace: {error}"

    return json.dumps(data, indent=2)


# Write tools (only available with write key)


@mcp.tool()
async def create_doc(content: str = "") -> str:
    """
    Create a new encrypted document.
    Returns the document ID and both write and read keys.
    IMPORTANT: Save these keys - they are shown only once!
    
    Args:
        content: Initial markdown content for the document (optional)
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    json_body = {"content": content} if content else {}
    data, error = await _make_request("POST", "/docs", json=json_body)
    if error:
        return f"Failed to create document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def update_doc(doc_id: str, content: str, if_match: Optional[str] = None) -> str:
    """
    Replace a document's entire content with new content.
    Requires write key.
    
    Args:
        doc_id: UUID of the document to update
        content: New markdown content (replaces existing content)
        if_match: Optional - version ETag (e.g., 'v5') to prevent conflicts
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    headers = {"Content-Type": "text/markdown"}
    if if_match:
        headers["If-Match"] = f'"{if_match}"' if not if_match.startswith('"') else if_match

    data, error = await _make_request("PUT", f"/docs/{doc_id}", headers=headers, content=content)
    if error:
        return f"Failed to update document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def append_doc(doc_id: str, content: str, if_match: Optional[str] = None) -> str:
    """
    Append content to the end of a document (separated by newline).
    Requires write key.
    
    Args:
        doc_id: UUID of the document to append to
        content: Markdown content to append
        if_match: Optional - version ETag (e.g., 'v5') to prevent conflicts
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    headers = {"Content-Type": "text/markdown"}
    if if_match:
        headers["If-Match"] = f'"{if_match}"' if not if_match.startswith('"') else if_match

    data, error = await _make_request("PATCH", f"/docs/{doc_id}", headers=headers, content=content)
    if error:
        return f"Failed to append to document: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def delete_doc(doc_id: str) -> str:
    """
    Permanently delete a document. This action cannot be undone.
    Requires write key.
    
    Args:
        doc_id: UUID of the document to delete
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    data, error = await _make_request("DELETE", f"/docs/{doc_id}")
    if error:
        return f"Failed to delete document: {error}"

    return "Document deleted successfully"


@mcp.tool()
async def create_workspace(name: str, entries: list[dict[str, str]] = None) -> str:
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
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    json_body = {"name": name, "entries": entries or []}
    data, error = await _make_request("POST", "/workspaces", json=json_body)
    if error:
        return f"Failed to create workspace: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def update_workspace(
    workspace_id: str, name: str, entries: list[dict[str, str]], if_match: Optional[str] = None
) -> str:
    """
    Replace a workspace's entire content (name and entries).
    Requires write key.
    
    Args:
        workspace_id: UUID of the workspace to update
        name: New workspace name
        entries: New list of entries (replaces existing entries)
        if_match: Optional - version ETag (e.g., 'v1') to prevent conflicts
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    headers = {"Content-Type": "application/json"}
    if if_match:
        headers["If-Match"] = f'"{if_match}"' if not if_match.startswith('"') else if_match

    json_body = {"name": name, "entries": entries}
    data, error = await _make_request("PUT", f"/workspaces/{workspace_id}", json=json_body, headers=headers)
    if error:
        return f"Failed to update workspace: {error}"

    return json.dumps(data, indent=2)


@mcp.tool()
async def delete_workspace(workspace_id: str) -> str:
    """
    Permanently delete a workspace. This action cannot be undone.
    Referenced documents and sub-workspaces are NOT deleted.
    Requires write key.
    
    Args:
        workspace_id: UUID of the workspace to delete
    """
    is_write = await _detect_key_type()
    if not is_write:
        return "Error: Write key required. Current key is read-only."

    data, error = await _make_request("DELETE", f"/workspaces/{workspace_id}")
    if error:
        return f"Failed to delete workspace: {error}"

    return "Workspace deleted successfully"


def main():
    """Main entry point for the MCP server."""
    # Validate required environment variables
    if not API_KEY:
        logger.error("MOLT_API_KEY environment variable is required")
        sys.exit(1)

    logger.info(f"Starting molt-md MCP server")
    logger.info(f"Base URL: {BASE_URL}")
    logger.info(f"Workspace ID: {WORKSPACE_ID or 'Not set (accessing docs directly)'}")

    # Run the FastMCP server
    mcp.run()


if __name__ == "__main__":
    main()
