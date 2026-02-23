# screenstream-mcp

An MCP server that captures screenshots from [ScreenStream](https://github.com/dkrivoruchko/ScreenStream) (Android MJPEG screen mirroring app) and returns them to Claude for analysis.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- ScreenStream app running on an Android device on the same network

## Setup

### 1. Configure the ScreenStream URL

Edit `config.json` to match your device's IP address and port:

```json
{
  "screenstream_url": "http://192.168.1.100:8080",
  "timeout": 10,
  "max_image_size_kb": 900
}
```

You can also override the URL via the environment variable `SCREENSTREAM_URL`.

### 2. Install dependencies

```bash
uv sync
```

### 3. Register with Claude Desktop

Add the following to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "screenstream": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/path/to/screenstream-mcp",
        "screenstream-mcp"
      ]
    }
  }
}
```

Replace `/path/to/screenstream-mcp` with the absolute path to this directory.

## Available Tools

| Tool | Description |
|------|-------------|
| `capture_screenshot` | Captures a single frame from the ScreenStream MJPEG feed and returns it as a JPEG image |

## Development

```bash
# Run with MCP Inspector for testing
uv run mcp dev src/screenstream_mcp/server.py
```
