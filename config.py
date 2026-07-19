"""QR Short Bot — config."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Load .env
_env = BASE_DIR / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "6247336698,1015145644").split(",")
    if x.strip().isdigit()
]
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "botunlverse").lstrip("@")
CHANNEL_ID = int(os.environ.get("CHANNEL_ID", "-1002720892156") or "0")
BRAND_NAME = os.environ.get("BRAND_NAME", "Aonagi QR Tools")
DB_PATH = BASE_DIR / "data" / "qrshort.db"
