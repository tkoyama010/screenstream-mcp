import base64
import json
import os
from io import BytesIO
from pathlib import Path

import requests
from mcp import types
from mcp.server.fastmcp import FastMCP
from PIL import Image

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config.json"


def _load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}

    return {
        "screenstream_url": os.environ.get("SCREENSTREAM_URL", cfg.get("screenstream_url", "http://192.168.1.100:8080")),
        "timeout": int(cfg.get("timeout", 10)),
        "max_image_size_kb": int(cfg.get("max_image_size_kb", 900)),
    }


# ---------------------------------------------------------------------------
# MJPEG frame capture
# ---------------------------------------------------------------------------

def _capture_frame(url: str, timeout: int) -> bytes:
    """Capture a single JPEG frame from a ScreenStream MJPEG stream."""
    resp = requests.get(url, stream=True, timeout=timeout)
    resp.raise_for_status()

    buf = b""
    for chunk in resp.iter_content(chunk_size=4096):
        buf += chunk
        start = buf.find(b"\xff\xd8")
        if start == -1:
            buf = buf[-8:]
            continue
        end = buf.find(b"\xff\xd9", start + 2)
        if end != -1:
            return buf[start : end + 2]

    raise RuntimeError("Could not extract a frame from the MJPEG stream")


def _resize_if_needed(jpeg_bytes: bytes, max_kb: int) -> bytes:
    """Resize the image if it exceeds max_kb to stay within Claude Desktop's 1 MB limit."""
    if len(jpeg_bytes) <= max_kb * 1024:
        return jpeg_bytes

    img = Image.open(BytesIO(jpeg_bytes))
    scale = 0.8
    while True:
        new_w = max(1, int(img.width * scale))
        new_h = max(1, int(img.height * scale))
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        buf = BytesIO()
        resized.save(buf, format="JPEG", quality=80)
        data = buf.getvalue()
        if len(data) <= max_kb * 1024 or scale < 0.1:
            return data
        scale *= 0.8


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP("screenstream-mcp")


@mcp.tool()
def capture_screenshot() -> list[types.ImageContent | types.TextContent]:
    """Capture a single screenshot from ScreenStream and return it as an image."""
    cfg = _load_config()
    url = cfg["screenstream_url"].rstrip("/") + "/"

    try:
        jpeg_bytes = _capture_frame(url, cfg["timeout"])
    except requests.exceptions.ConnectionError:
        return [types.TextContent(type="text", text=f"Connection failed: {url}\nMake sure ScreenStream is running and the URL is correct.")]
    except requests.exceptions.Timeout:
        return [types.TextContent(type="text", text=f"Request timed out after {cfg['timeout']}s: {url}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error capturing screenshot: {e}")]

    jpeg_bytes = _resize_if_needed(jpeg_bytes, cfg["max_image_size_kb"])
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return [types.ImageContent(type="image", data=b64, mimeType="image/jpeg")]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
