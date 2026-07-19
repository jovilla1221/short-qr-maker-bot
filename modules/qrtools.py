"""QR generator + shortener helpers."""
from __future__ import annotations

import io
import re
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional, Tuple

import qrcode
from PIL import Image, ImageDraw
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.colormasks import RadialGradiantColorMask, SolidFillColorMask
from qrcode.image.styles.moduledrawers import (
    CircleModuleDrawer,
    GappedSquareModuleDrawer,
    RoundedModuleDrawer,
)

URL_RE = re.compile(r"^https?://", re.I)

EC_LEVELS = {
    "L": qrcode.constants.ERROR_CORRECT_L,
    "M": qrcode.constants.ERROR_CORRECT_M,
    "Q": qrcode.constants.ERROR_CORRECT_Q,
    "H": qrcode.constants.ERROR_CORRECT_H,
}
DRAWER_STYLES = {
    "rounded": RoundedModuleDrawer,
    "circle": CircleModuleDrawer,
    "square": GappedSquareModuleDrawer,
}
SIZE_PRESETS = {
    "small": {"box_size": 6, "border": 2},
    "medium": {"box_size": 10, "border": 4},
    "large": {"box_size": 16, "border": 6},
    "xlarge": {"box_size": 22, "border": 8},
}
COLOR_PRESETS = {
    "blue": ((0, 100, 200), (255, 255, 255)),
    "green": ((0, 150, 80), (255, 255, 255)),
    "purple": ((120, 60, 180), (255, 255, 255)),
    "black": ((20, 20, 20), (255, 255, 255)),
    "orange": ((220, 100, 20), (255, 255, 255)),
    "red": ((200, 40, 40), (255, 255, 255)),
    "pink": ((200, 80, 150), (255, 255, 255)),
    "teal": ((0, 150, 150), (255, 255, 255)),
    "dark": ((30, 30, 40), (240, 240, 240)),
}


def make_qr_png(
    data: str,
    fill: tuple = (0, 100, 200),
    back: tuple = (255, 255, 255),
    size: str = "medium",
    ec_level: str = "H",
    style: str = "rounded",
    gradient: bool = True,
) -> bytes:
    params = SIZE_PRESETS.get(size, SIZE_PRESETS["medium"])
    ec = EC_LEVELS.get(ec_level.upper(), EC_LEVELS["H"])
    qr = qrcode.QRCode(
        version=None,
        error_correction=ec,
        box_size=params["box_size"],
        border=params["border"],
    )
    qr.add_data(data)
    qr.make(fit=True)
    drawer_cls = DRAWER_STYLES.get(style, RoundedModuleDrawer)
    if gradient:
        color_mask = RadialGradiantColorMask(
            back_color=back,
            center_color=fill,
            edge_color=tuple(max(0, c - 60) for c in fill),
        )
    else:
        color_mask = SolidFillColorMask(back_color=back, front_color=fill)
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=drawer_cls(),
        color_mask=color_mask,
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def make_qr_with_logo(
    data: str,
    logo_bytes: bytes,
    fill: tuple = (0, 100, 200),
    back: tuple = (255, 255, 255),
    size: str = "large",
    style: str = "rounded",
    gradient: bool = True,
    logo_ratio: float = 0.28,
) -> bytes:
    """QR with logo in center. Always H error correction."""
    params = SIZE_PRESETS.get(size, SIZE_PRESETS["large"])
    qr = qrcode.QRCode(
        version=None,
        error_correction=EC_LEVELS["H"],
        box_size=params["box_size"],
        border=params["border"],
    )
    qr.add_data(data)
    qr.make(fit=True)
    drawer_cls = DRAWER_STYLES.get(style, RoundedModuleDrawer)
    if gradient:
        color_mask = RadialGradiantColorMask(
            back_color=back,
            center_color=fill,
            edge_color=tuple(max(0, c - 60) for c in fill),
        )
    else:
        color_mask = SolidFillColorMask(back_color=back, front_color=fill)
    img = qr.make_image(
        image_factory=StyledPilImage,
        module_drawer=drawer_cls(),
        color_mask=color_mask,
    )
    pil_img = img.convert("RGBA")
    qr_w, qr_h = pil_img.size
    try:
        logo_img = Image.open(io.BytesIO(logo_bytes)).convert("RGBA")
    except Exception:
        buf = io.BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)
        return buf.getvalue()

    logo_max = max(24, int(min(qr_w, qr_h) * logo_ratio))
    logo_img.thumbnail((logo_max, logo_max), Image.LANCZOS)
    bg_size = logo_max + 20
    bg = Image.new("RGBA", (bg_size, bg_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bg)
    draw.ellipse((0, 0, bg_size - 1, bg_size - 1), fill=(255, 255, 255, 255))
    paste_x = (qr_w - bg_size) // 2
    paste_y = (qr_h - bg_size) // 2
    pil_img.paste(bg, (paste_x, paste_y), bg)
    logo_x = (qr_w - logo_img.width) // 2
    logo_y = (qr_h - logo_img.height) // 2
    pil_img.paste(logo_img, (logo_x, logo_y), logo_img)
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def make_vcard(
    name: str,
    phone: str = "",
    email: str = "",
    org: str = "",
    website: str = "",
    note: str = "",
) -> str:
    """Build vCard 3.0 payload."""
    lines = ["BEGIN:VCARD", "VERSION:3.0", f"FN:{name}", f"N:{name};;;"]
    if org:
        lines.append(f"ORG:{org}")
    if phone:
        lines.append(f"TEL;TYPE=CELL:{phone}")
    if email:
        lines.append(f"EMAIL:{email}")
    if website:
        lines.append(f"URL:{website}")
    if note:
        lines.append(f"NOTE:{note}")
    lines.append("END:VCARD")
    return "\n".join(lines)


def make_geo(lat: float, lon: float, label: str = "") -> str:
    if label:
        # Google Maps open link is more practical for phones
        q = urllib.parse.quote(label)
        return f"https://maps.google.com/?q={lat},{lon}({q})"
    return f"geo:{lat},{lon}"


def make_maps_query(query: str) -> str:
    return "https://maps.google.com/?q=" + urllib.parse.quote(query)


def make_calendar(
    title: str,
    start: datetime,
    end: Optional[datetime] = None,
    location: str = "",
    description: str = "",
) -> str:
    """VEVENT (iCalendar) for calendar QR."""
    def fmt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%S")

    if end is None:
        end = start
    lines = [
        "BEGIN:VEVENT",
        f"SUMMARY:{title}",
        f"DTSTART:{fmt(start)}",
        f"DTEND:{fmt(end)}",
    ]
    if location:
        lines.append(f"LOCATION:{location}")
    if description:
        lines.append(f"DESCRIPTION:{description}")
    lines.append("END:VEVENT")
    return "\n".join(lines)


def parse_dt(text: str) -> Optional[datetime]:
    """Accept YYYY-MM-DD HH:MM or YYYY-MM-DD."""
    text = text.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_expiry_token(token: str) -> Optional[int]:
    """Return hours from tokens like 1h, 24h, 7d, 30d, never."""
    token = token.strip().lower()
    if token in ("never", "0", "none", "-"):
        return None
    m = re.fullmatch(r"(\d+)\s*([hdw])", token)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    if unit == "h":
        return n
    if unit == "d":
        return n * 24
    if unit == "w":
        return n * 24 * 7
    return None


def shorten_via_tinyurl(url: str) -> str:
    api = "https://tinyurl.com/api-create.php?" + urllib.parse.urlencode({"url": url})
    req = urllib.request.Request(api, headers={"User-Agent": "Aonagi-QR/3.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8")


def split_pipe(text: str, min_parts: int = 1) -> list[str]:
    parts = [p.strip() for p in text.split("|")]
    while parts and parts[-1] == "":
        parts.pop()
    return parts
