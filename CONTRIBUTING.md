# Contributing to molt-mcp

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/bndkts/molt-md-mcp.git
cd molt-md-mcp
uv pip install -e ".[dev]"
```

## Running Locally

```bash
export MOLT_API_KEY="your-test-key"
molt-mcp
```

Or test with the MCP Inspector:

```bash
npx @modelcontextprotocol/inspector molt-mcp
```

## Code Style

- Format with **ruff** (`ruff format .`)
- Lint with **ruff** (`ruff check .`)
- Type-check with **mypy** (`mypy src/`)

## Submitting Changes

1. Fork the repository and create a feature branch
2. Make your changes with clear commit messages
3. Ensure code passes linting and type checks
4. Open a pull request with a description of your changes

## Reporting Issues

Open an issue on [GitHub](https://github.com/bndkts/molt-md-mcp/issues) with:

- A clear description of the problem
- Steps to reproduce
- Expected vs actual behavior
- Environment details (Python version, OS)
