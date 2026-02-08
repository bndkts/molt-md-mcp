# molt-mcp

A Model Context Protocol (MCP) server that provides LLM access to [molt-md](https://molt-md.com), an encrypted markdown document hosting service. **Turn your markdown files into an LLM-accessible knowledge base** by uploading them to molt-md and accessing them through this MCP server. Your AI assistant can read, update, and manage encrypted markdown documents organized in workspaces.

## Features

- **Markdown → MCP Server** - Organize your markdown files into LLM-accessible storage with workspaces (free while in beta)
- **Full API Coverage** - Every molt-md endpoint exposed as an MCP tool
- **Encrypted Storage** - End-to-end encryption with AES-256-GCM
- **Read/Write Key Support** - Permission enforcement via the API's dual-key model
- **Workspace Management** - Bundle and organize multiple documents
- **Partial Fetches** - Efficient document previews with line-limited reads
- **Version Control** - Optimistic concurrency control with ETag support

## Installation

Install directly from GitHub using `uvx`:

```bash
uvx --from git+https://github.com/bndkts/molt-md-mcp molt-mcp
```

Or install from source for development:

```bash
git clone https://github.com/bndkts/molt-md-mcp.git
cd molt-md-mcp
uv pip install -e .
```

## Configuration

### Claude Desktop

Add to your Claude Desktop config file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "molt-md": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/bndkts/molt-md-mcp", "molt-mcp"],
      "env": {
        "MOLT_API_KEY": "your-api-key-here",
        "MOLT_WORKSPACE_ID": "your-workspace-id-here"
      }
    }
  }
}
```

### Environment Variables

- **`MOLT_API_KEY`** (required) - Your molt-md write key or read key (obtained by creating a document)
- **`MOLT_WORKSPACE_ID`** (optional) - Access documents through a specific workspace
- **`MOLT_BASE_URL`** (optional) - API base URL (defaults to `https://api.molt-md.com/api/v1`; use `http://localhost:8000/api/v1` for local development)

### Permission Model

The server passes your configured key to the molt-md API on every request:

- **Write key** → All operations succeed (read + create + update + delete)
- **Read key** → Read operations succeed; write operations return `403 Forbidden` from the API

## Available Tools

### Read-Only Tools (Available with both key types)

- **`health_check`** - Check if the molt-md API is available
- **`get_metrics`** - Get database statistics (document and workspace counts)
- **`read_doc`** - Read a document's decrypted content
  - Supports partial fetches with `lines` parameter
  - Returns JSON with metadata or plain markdown
- **`read_workspace`** - Read a workspace's content (name and entries)
  - Supports preview generation with `preview_lines` parameter

### Write Tools (Require write key)

#### Document Operations
- **`create_doc`** - Create a new encrypted document
  - Returns document ID, write key, and read key
- **`update_doc`** - Replace a document's entire content
  - Supports optimistic locking with `if_match` (version ETag)
- **`append_doc`** - Append content to the end of a document
  - Supports optimistic locking with `if_match`
- **`delete_doc`** - Permanently delete a document

#### Workspace Operations
- **`create_workspace`** - Create a new workspace to bundle documents
  - Returns workspace ID, write key, and read key
- **`update_workspace`** - Replace a workspace's content (name and entries)
  - Supports optimistic locking with `if_match`
- **`delete_workspace`** - Permanently delete a workspace
  - Does not delete referenced documents

## Usage Examples

### Basic Document Operations

```
User: Create a new document with the title "Meeting Notes"
Assistant: [Uses create_doc tool] → Returns doc ID and keys

User: Read that document
Assistant: [Uses read_doc tool with the doc ID]

User: Append a new section to the document
Assistant: [Uses append_doc tool]
```

### Workspace Management

```
User: Create a workspace called "Project Alpha" with these two documents
Assistant: [Uses create_workspace tool with document IDs and keys]

User: Show me a preview of all documents in the workspace
Assistant: [Uses read_workspace with preview_lines=1]
```

### Partial Fetches for Efficiency

```
User: Show me just the title of document xyz
Assistant: [Uses read_doc with lines=1 and as_markdown=true]
```

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/bndkts/molt-md-mcp.git
cd molt-md-mcp

# Install dependencies
uv pip install -e .

# Run the server
molt-mcp
```

### Testing

**With local molt-md API:**

```bash
# Start the molt-md API server first (in another terminal)
cd /path/to/molt-md
cargo run  # or your preferred method

# Create a test document to get keys
curl -X POST http://localhost:8000/api/v1/docs \
  -H "Content-Type: application/json" \
  -d '{"content": "# Test Document"}'
# Save the write_key and id from the response

# Run the MCP server
export MOLT_BASE_URL="http://localhost:8000/api/v1"
export MOLT_API_KEY="your-write-key-here"
npx @modelcontextprotocol/inspector molt-mcp
```

**With production molt-md API:**

```bash
# Create a test document to get keys
curl -X POST https://api.molt-md.com/api/v1/docs \
  -H "Content-Type: application/json" \
  -d '{"content": "# Test Document"}'
# Save the write_key from the response

# Run the MCP server
export MOLT_API_KEY="your-write-key-here"
npx @modelcontextprotocol/inspector molt-mcp
```

## Security Notes

- **Never commit API keys to version control**
- **Keys are shown only once** during document/workspace creation - save them securely
- **Read keys** can be safely shared for read-only collaborators
- **Write keys** provide full access - share only with trusted editors
- **Lost keys** cannot be recovered - the content becomes permanently inaccessible

## Architecture

This is a thin wrapper around the molt-md REST API:

1. **FastMCP** handles the MCP protocol and tool registration
2. **httpx** makes async HTTP requests with connection pooling
3. **Environment config** provides API key and optional workspace context
4. **UUID validation** and **ETag formatting** ensure correct API usage

## Links

- **molt-md**: [https://molt-md.com](https://molt-md.com)
- **MCP Specification**: [https://modelcontextprotocol.io](https://modelcontextprotocol.io)
- **FastMCP**: [https://github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please open an issue or pull request on GitHub.

---

Built with ❤️ for the Model Context Protocol ecosystem
