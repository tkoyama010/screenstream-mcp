import asyncio
import base64
import json
import os
import random
import string
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
import websockets
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
# ScreenStream WebSocket + MJPEG protocol
# ---------------------------------------------------------------------------

def _random_client_id(length: int = 16) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))


async def _get_stream_address(base_url: str, client_id: str, timeout: int) -> str:
    """Connect to ScreenStream WebSocket and retrieve the MJPEG stream address."""
    parsed = urlparse(base_url)
    ws_url = f"ws://{parsed.netloc}/socket?clientId={client_id}"

    async with websockets.connect(ws_url, open_timeout=timeout) as ws:
        await ws.send(json.dumps({"type": "CONNECT"}))
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise TimeoutError("Timed out waiting for STREAM_ADDRESS from ScreenStream")
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            if msg.get("type") == "STREAM_ADDRESS":
                return msg["data"]["streamAddress"]
            if msg.get("type") == "UNAUTHORIZED":
                raise PermissionError(f"ScreenStream rejected connection: {msg.get('data')}")


def _capture_frame(stream_url: str, client_id: str, timeout: int) -> bytes:
    """Fetch a single JPEG frame from a ScreenStream MJPEG endpoint."""
    url = f"{stream_url}?clientId={client_id}"
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

    raise RuntimeError("Could not extract a JPEG frame from the MJPEG stream")


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
    base_url = cfg["screenstream_url"].rstrip("/")
    client_id = _random_client_id()

    try:
        stream_address = asyncio.run(_get_stream_address(base_url, client_id, cfg["timeout"]))
        # stream_address may be absolute, root-relative ("/stream.mjpeg"),
        # or relative ("stream.mjpeg")
        if not stream_address.startswith("http"):
            sep = "" if stream_address.startswith("/") else "/"
            stream_address = base_url + sep + stream_address
        jpeg_bytes = _capture_frame(stream_address, client_id, cfg["timeout"])
    except ConnectionRefusedError:
        return [types.TextContent(type="text", text=f"Connection refused: {base_url}\nMake sure ScreenStream is running and the URL is correct.")]
    except TimeoutError as e:
        return [types.TextContent(type="text", text=str(e))]
    except PermissionError as e:
        return [types.TextContent(type="text", text=str(e))]
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error capturing screenshot: {e}")]

    jpeg_bytes = _resize_if_needed(jpeg_bytes, cfg["max_image_size_kb"])
    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")
    return [types.ImageContent(type="image", data=b64, mimeType="image/jpeg")]


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
