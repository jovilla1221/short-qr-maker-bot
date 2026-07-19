#!/usr/bin/env python3
"""Aonagi QR Tools — full feature set."""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest

from config import BOT_TOKEN, ADMIN_IDS, CHANNEL_USERNAME, CHANNEL_ID, BRAND_NAME
from modules.db import (
    init_db,
    upsert_user,
    get_user,
    set_user_name,
    bump_qr,
    bump_short,
    all_users,
    stats,
    create_qr_item,
    create_short_item,
    list_qr_items,
    list_short_items,
    get_qr_item,
    get_short_item,
    edit_qr_item,
    revoke_qr_item,
    revoke_short_item,
    set_qr_expiry,
    set_short_expiry,
    item_status_label,
)
from modules.qrtools import (
    make_qr_png,
    make_qr_with_logo,
    make_vcard,
    make_geo,
    make_maps_query,
    make_calendar,
    parse_dt,
    parse_expiry_token,
    shorten_via_tinyurl,
    URL_RE,
    COLOR_PRESETS,
    split_pipe,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("qr-short")

# ── Labels ────────────────────────────────────────────────────────
BTN_QR = "📱 Buat QR"
BTN_SHORT = "🔗 Short URL"
BTN_QRSHORT = "✨ QR + Short"
BTN_WIFI = "📶 QR WiFi"
BTN_PAY = "💳 QR Payment"
BTN_LOGO = "🖼 QR Logo"
BTN_VCARD = "👤 vCard"
BTN_LOC = "📍 Location"
BTN_EVENT = "📅 Calendar"
BTN_BULK = "📦 Bulk QR"
BTN_MYQR = "🗂 My QR"
BTN_HISTORY = "🕘 Riwayat"
BTN_HELP = "ℹ️ Bantuan"
BTN_MENU = "🏠 Menu"
BTN_CANCEL = "❌ Batal"

COLOR_LABELS = {
    "blue": "💙 Biru",
    "green": "💚 Hijau",
    "purple": "💜 Ungu",
    "black": "🖤 Hitam",
    "orange": "🧡 Oranye",
    "red": "❤️ Merah",
    "pink": "💗 Pink",
    "teal": "🩵 Teal",
}
SIZE_LABELS = {
    "small": "S Kecil",
    "medium": "M Standar",
    "large": "L Besar",
    "xlarge": "XL Super",
}
STYLE_LABELS = {
    "rounded": "▢ Rounded",
    "circle": "● Circle",
    "square": "■ Square",
}
EC_LABELS = {"L": "L 7%", "M": "M 15%", "Q": "Q 25%", "H": "H 30%"}
EXPIRY_OPTS = [
    ("1h", "1 jam"),
    ("24h", "24 jam"),
    ("7d", "7 hari"),
    ("30d", "30 hari"),
    ("never", "Tanpa expiry"),
]


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


async def is_member(bot, user_id: int) -> bool:
    if is_admin(user_id):
        return True
    try:
        chat_id = CHANNEL_ID or f"@{CHANNEL_USERNAME}"
        m = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return m.status in ("member", "administrator", "creator")
    except Exception as e:
        log.warning("force-sub check fail: %s", e)
        return False


def default_opts() -> dict:
    return {
        "color": "blue",
        "size": "medium",
        "style": "rounded",
        "ec": "H",
        "gradient": True,
        "expiry": "never",
    }


def opts_summary(opts: dict) -> str:
    c = COLOR_LABELS.get(opts.get("color", "blue"), opts.get("color"))
    s = SIZE_LABELS.get(opts.get("size", "medium"), opts.get("size"))
    st = STYLE_LABELS.get(opts.get("style", "rounded"), opts.get("style"))
    e = EC_LABELS.get(opts.get("ec", "H"), opts.get("ec"))
    g = "Gradient ON" if opts.get("gradient", True) else "Solid"
    x = opts.get("expiry", "never")
    return f"{c} · {s} · {st} · {e} · {g} · exp:{x}"


# ── Keyboards ─────────────────────────────────────────────────────

def force_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📢 Join @{CHANNEL_USERNAME}", url=f"https://t.me/{CHANNEL_USERNAME}")],
        [InlineKeyboardButton("✅ Saya sudah join", callback_data="check_sub")],
    ])


def welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🚀 Buka Menu", callback_data="open_menu")]])


def menu_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📱 Buat QR", callback_data="menu_qr"),
            InlineKeyboardButton("🔗 Short URL", callback_data="menu_short"),
        ],
        [
            InlineKeyboardButton("✨ QR + Short", callback_data="menu_qrshort"),
            InlineKeyboardButton("🖼 QR Logo", callback_data="menu_logo"),
        ],
        [
            InlineKeyboardButton("👤 vCard", callback_data="menu_vcard"),
            InlineKeyboardButton("📍 Location", callback_data="menu_loc"),
        ],
        [
            InlineKeyboardButton("📅 Calendar", callback_data="menu_event"),
            InlineKeyboardButton("💳 Payment", callback_data="menu_pay"),
        ],
        [
            InlineKeyboardButton("📶 WiFi", callback_data="menu_wifi"),
            InlineKeyboardButton("📦 Bulk QR", callback_data="menu_bulk"),
        ],
        [
            InlineKeyboardButton("🗂 My QR", callback_data="menu_myqr"),
            InlineKeyboardButton("🎨 Custom", callback_data="menu_custom"),
        ],
        [
            InlineKeyboardButton("🕘 Riwayat", callback_data="menu_history"),
            InlineKeyboardButton("ℹ️ Bantuan", callback_data="menu_help"),
        ],
    ])


def reply_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(BTN_QR), KeyboardButton(BTN_SHORT)],
            [KeyboardButton(BTN_QRSHORT), KeyboardButton(BTN_LOGO)],
            [KeyboardButton(BTN_VCARD), KeyboardButton(BTN_LOC)],
            [KeyboardButton(BTN_EVENT), KeyboardButton(BTN_PAY)],
            [KeyboardButton(BTN_WIFI), KeyboardButton(BTN_BULK)],
            [KeyboardButton(BTN_MYQR), KeyboardButton(BTN_HISTORY)],
            [KeyboardButton(BTN_HELP), KeyboardButton(BTN_MENU)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def cancel_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_mode")],
        [InlineKeyboardButton(BTN_MENU, callback_data="open_menu")],
    ])


def after_result_kb(code: Optional[str] = None, short_url: Optional[str] = None) -> InlineKeyboardMarkup:
    rows = []
    if code:
        rows.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"editqr:{code}"),
            InlineKeyboardButton("⏳ Expiry", callback_data=f"expqr:{code}"),
            InlineKeyboardButton("🚫 Revoke", callback_data=f"revqr:{code}"),
        ])
    if short_url and code:
        rows.append([
            InlineKeyboardButton("⏳ Short expiry", callback_data=f"expsh:{code}"),
            InlineKeyboardButton("🚫 Revoke short", callback_data=f"revsh:{code}"),
        ])
    elif short_url:
        rows.append([InlineKeyboardButton("📱 QR dari short link", callback_data=f"qr_from:{short_url[:160]}")])
    rows += [
        [
            InlineKeyboardButton("📱 QR lagi", callback_data="menu_qr"),
            InlineKeyboardButton("🔗 Short lagi", callback_data="menu_short"),
        ],
        [
            InlineKeyboardButton("🗂 My QR", callback_data="menu_myqr"),
            InlineKeyboardButton(BTN_MENU, callback_data="open_menu"),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def quick_color_kb(prefix: str = "qcolor") -> InlineKeyboardMarkup:
    rows, row = [], []
    for key, label in COLOR_LABELS.items():
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}_{key}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_mode")])
    return InlineKeyboardMarkup(rows)


def custom_panel_kb(opts: dict) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎨 Warna", callback_data="opt_color")],
        [InlineKeyboardButton("📐 Ukuran", callback_data="opt_size")],
        [InlineKeyboardButton("🧩 Style", callback_data="opt_style")],
        [InlineKeyboardButton("🛡 Error Correction", callback_data="opt_ec")],
        [InlineKeyboardButton("⏳ Default expiry", callback_data="opt_expiry")],
        [InlineKeyboardButton(
            "🌈 Gradient: ON" if opts.get("gradient", True) else "⬜ Gradient: OFF",
            callback_data="opt_toggle_grad",
        )],
        [InlineKeyboardButton("✅ Lanjut — kirim konten", callback_data="opt_ready")],
        [InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_mode")],
    ])


def pick_kb(kind: str, items: dict) -> InlineKeyboardMarkup:
    rows, row = [], []
    for k, label in items.items():
        row.append(InlineKeyboardButton(label, callback_data=f"set_{kind}_{k}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ Kembali", callback_data="opt_back")])
    return InlineKeyboardMarkup(rows)


def expiry_kb(prefix: str, code: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(label, callback_data=f"{prefix}:{code}:{token}")]
        for token, label in EXPIRY_OPTS
    ]
    rows.append([InlineKeyboardButton(BTN_CANCEL, callback_data="cancel_mode")])
    return InlineKeyboardMarkup(rows)


def myqr_kb(items: list) -> InlineKeyboardMarkup:
    rows = []
    for it in items[:12]:
        st = "🚫" if it.get("status") == "revoked" else ("⌛" if it.get("status") == "expired" else "✅")
        title = (it.get("title") or it.get("kind") or "qr")[:18]
        rows.append([InlineKeyboardButton(
            f"{st} {title} · {it['code']}",
            callback_data=f"openqr:{it['code']}",
        )])
    rows.append([InlineKeyboardButton(BTN_MENU, callback_data="open_menu")])
    return InlineKeyboardMarkup(rows)


def qr_detail_kb(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📤 Generate ulang", callback_data=f"regen:{code}"),
            InlineKeyboardButton("✏️ Edit isi", callback_data=f"editqr:{code}"),
        ],
        [
            InlineKeyboardButton("⏳ Set expiry", callback_data=f"expqr:{code}"),
            InlineKeyboardButton("🚫 Revoke", callback_data=f"revqr:{code}"),
        ],
        [InlineKeyboardButton("◀️ My QR", callback_data="menu_myqr")],
    ])


# ── Force sub / welcome / menu ────────────────────────────────────

async def require_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    uid = update.effective_user.id
    if await is_member(context.bot, uid):
        return True
    text = (
        f"🔒 *Akses terkunci*\n\n"
        f"Sebelum pakai *{BRAND_NAME}*, join channel dulu:\n"
        f"👉 [@{CHANNEL_USERNAME}](https://t.me/{CHANNEL_USERNAME})\n\n"
        f"Setelah join, tap *Saya sudah join*."
    )
    kb = force_sub_kb()
    if update.callback_query:
        try:
            await update.callback_query.answer()
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb, disable_web_page_preview=True,
            )
        except BadRequest:
            await update.effective_message.reply_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb, disable_web_page_preview=True,
            )
    else:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb, disable_web_page_preview=True,
        )
    return False


def display_name(user_row: Optional[dict], tg_user) -> str:
    if user_row and user_row.get("name"):
        return user_row["name"]
    return tg_user.full_name or tg_user.first_name or "teman"


async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    u = update.effective_user
    user = get_user(u.id)
    name = display_name(user, u)
    text = (
        f"👋 Halo *{name}*!\n\n"
        f"Selamat datang di *{BRAND_NAME}*.\n"
        f"QR · Short link · Logo · vCard · Location · Calendar · Bulk · Expiry.\n\n"
        f"Tap tombol di bawah untuk mulai ✨"
    )
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=welcome_kb(),
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=welcome_kb(),
    )


async def send_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    text = f"🏠 *Menu {BRAND_NAME}*\n\nPilih fitur:"
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
            )
        except BadRequest:
            await update.effective_message.reply_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
            )
    else:
        await update.effective_message.reply_text(
            text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
        )
    await update.effective_message.reply_text("Atau pakai keyboard 👇", reply_markup=reply_menu_kb())


# ── Core QR send ──────────────────────────────────────────────────

async def send_qr(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    content: str,
    kind: str = "text",
    title: str = "",
    fill=(0, 100, 200),
    back=(255, 255, 255),
    size: str = "medium",
    style: str = "rounded",
    ec: str = "H",
    gradient: bool = True,
    logo_bytes: Optional[bytes] = None,
    caption_extra: str = "",
    save: bool = True,
    edit_msg=None,
):
    uid = update.effective_user.id
    msg = edit_msg or await update.effective_message.reply_text("⏳ Bikin QR...")
    try:
        if logo_bytes:
            png = make_qr_with_logo(
                content, logo_bytes, fill=fill, back=back, size=size or "large",
                style=style, gradient=gradient,
            )
        else:
            png = make_qr_png(
                content, fill=fill, back=back, size=size, ec_level=ec,
                style=style, gradient=gradient,
            )
        bump_qr(uid, content, len(png))
        code = None
        if save:
            opts = context.user_data.get("qr_opts", default_opts())
            hours = parse_expiry_token(opts.get("expiry", "never"))
            item = create_qr_item(uid, content, kind=kind, title=title or kind, expires_hours=hours)
            code = item["code"]
        try:
            await msg.delete()
        except Exception:
            pass
        cap = f"📱 *QR siap*"
        if code:
            cap += f" · code `{code}`"
        cap += f"\n\n`{content[:240]}`"
        if caption_extra:
            cap += f"\n\n{caption_extra}"
        await update.effective_message.reply_photo(
            photo=InputFile(BytesIO(png), filename="qr.png"),
            caption=cap,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=after_result_kb(code=code),
        )
    except Exception as e:
        log.exception("qr fail")
        try:
            await msg.edit_text(f"❌ Gagal bikin QR: {e}")
        except Exception:
            await update.effective_message.reply_text(f"❌ Gagal bikin QR: {e}")


async def do_short(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    expires_hours: Optional[int] = None,
) -> Optional[str]:
    uid = update.effective_user.id
    if not URL_RE.match(url):
        url = "https://" + url
    wait = await update.effective_message.reply_text("⏳ Shorten...")
    try:
        short = shorten_via_tinyurl(url)
        bump_short(uid, url, short)
        opts = context.user_data.get("qr_opts", default_opts())
        hours = expires_hours if expires_hours is not None else parse_expiry_token(opts.get("expiry", "never"))
        item = create_short_item(uid, url, short, expires_hours=hours)
        exp_txt = f"\n⏳ Expiry: `{opts.get('expiry', 'never')}`" if hours else "\n⏳ Expiry: never"
        await wait.edit_text(
            f"🔗 *Short URL siap* · code `{item['code']}`\n\n"
            f"Asli:\n`{url}`\n\nPendek:\n`{short}`{exp_txt}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=after_result_kb(code=item["code"], short_url=short),
            disable_web_page_preview=True,
        )
        return short
    except Exception as e:
        log.exception("short fail")
        await wait.edit_text(f"❌ Gagal shorten: {e}")
        return None


# ── Mode entry helpers ────────────────────────────────────────────

async def enter_mode(update, context, mode: str, prompt: str, edit: bool = False):
    context.user_data["mode"] = mode
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                prompt, parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_inline_kb(),
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(
        prompt, parse_mode=ParseMode.MARKDOWN, reply_markup=cancel_inline_kb(),
    )


async def open_custom_panel(update, context, edit: bool = False):
    opts = context.user_data.setdefault("qr_opts", default_opts())
    context.user_data["mode"] = "custom_setup"
    text = (
        f"🎨 *Custom QR*\n\nSetting:\n`{opts_summary(opts)}`\n\n"
        f"Atur opsi, lalu tap *Lanjut*."
    )
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=custom_panel_kb(opts),
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=custom_panel_kb(opts),
    )


# ── Handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username or "", u.full_name or "")
    context.user_data.clear()
    if not await require_sub(update, context):
        return
    await send_welcome(update, context)


async def cb_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    upsert_user(u.id, u.username or "", u.full_name or "")
    if not await is_member(context.bot, u.id):
        await q.answer("Belum terdeteksi join channel 😅", show_alert=True)
        return
    await send_welcome(update, context, edit=True)


async def cb_open_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    context.user_data.clear()
    await send_menu(update, context, edit=True)


async def cb_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer("Dibatalkan")
    context.user_data.clear()
    await send_menu(update, context, edit=True)


async def cb_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    data = q.data
    prompts = {
        "menu_qr": ("qr_wait_content", "📱 *Buat QR*\n\nKirim URL atau teks."),
        "menu_short": ("short", "🔗 *Short URL*\n\nKirim URL panjang.\n\nOpsional expiry:\n`https://... | 24h`"),
        "menu_qrshort": ("qrshort", "✨ *QR + Short*\n\nKirim URL."),
        "menu_wifi": ("wifi", "📶 *QR WiFi*\n\n`SSID | password | WPA`"),
        "menu_pay": ("pay", "💳 *QR Payment*\n\n`penerima | jumlah | catatan`"),
        "menu_logo": ("logo_content", "🖼 *QR Logo*\n\n1) Kirim URL/teks dulu\n2) Lalu kirim foto logo"),
        "menu_vcard": ("vcard", "👤 *vCard*\n\n`Nama | telp | email | org | website`"),
        "menu_loc": ("loc", "📍 *Location*\n\n`lat,lon | label`\natau\n`alamat / nama tempat`"),
        "menu_event": ("event", "📅 *Calendar*\n\n`Judul | YYYY-MM-DD HH:MM | YYYY-MM-DD HH:MM | lokasi | deskripsi`\n\nEnd opsional."),
        "menu_bulk": ("bulk", "📦 *Bulk QR*\n\nKirim banyak baris (maks 20):\n```\nhttps://a.com\nhttps://b.com\nNama | 0812\n```"),
    }
    if data in prompts:
        mode, prompt = prompts[data]
        await enter_mode(update, context, mode, prompt, edit=True)
        return
    if data == "menu_custom":
        await open_custom_panel(update, context, edit=True)
    elif data == "menu_myqr":
        await show_my_qr(update, context, edit=True)
    elif data == "menu_history":
        await show_history(update, context, edit=True)
    elif data == "menu_help":
        await show_help(update, context, edit=True)


async def cb_opt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    opts = context.user_data.setdefault("qr_opts", default_opts())
    data = q.data
    if data == "opt_color":
        await q.edit_message_text("Pilih warna:", reply_markup=pick_kb("color", COLOR_LABELS))
    elif data == "opt_size":
        await q.edit_message_text("Pilih ukuran:", reply_markup=pick_kb("size", SIZE_LABELS))
    elif data == "opt_style":
        await q.edit_message_text("Pilih style:", reply_markup=pick_kb("style", STYLE_LABELS))
    elif data == "opt_ec":
        await q.edit_message_text("Error correction:", reply_markup=pick_kb("ec", EC_LABELS))
    elif data == "opt_expiry":
        rows = [[InlineKeyboardButton(label, callback_data=f"set_expiry_{token}")]
                for token, label in EXPIRY_OPTS]
        rows.append([InlineKeyboardButton("◀️ Kembali", callback_data="opt_back")])
        await q.edit_message_text("Default expiry QR/short baru:", reply_markup=InlineKeyboardMarkup(rows))
    elif data == "opt_toggle_grad":
        opts["gradient"] = not opts.get("gradient", True)
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)
    elif data == "opt_ready":
        context.user_data["mode"] = "custom_content"
        await q.edit_message_text(
            f"✅ Setting: `{opts_summary(opts)}`\n\nKirim URL/teks sekarang.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_inline_kb(),
        )
    elif data == "opt_back":
        await open_custom_panel(update, context, edit=True)
    elif data.startswith("set_color_"):
        opts["color"] = data.replace("set_color_", "")
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)
    elif data.startswith("set_size_"):
        opts["size"] = data.replace("set_size_", "")
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)
    elif data.startswith("set_style_"):
        opts["style"] = data.replace("set_style_", "")
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)
    elif data.startswith("set_ec_"):
        opts["ec"] = data.replace("set_ec_", "")
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)
    elif data.startswith("set_expiry_"):
        opts["expiry"] = data.replace("set_expiry_", "")
        context.user_data["qr_opts"] = opts
        await open_custom_panel(update, context, edit=True)


async def cb_quick_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    key = q.data.replace("qcolor_", "", 1)
    content = context.user_data.get("pending_qr")
    kind = context.user_data.get("pending_kind", "text")
    title = context.user_data.get("pending_title", kind)
    logo_bytes = context.user_data.get("pending_logo")
    if not content or key not in COLOR_PRESETS:
        await q.edit_message_text("Sesi habis. Mulai dari menu.", reply_markup=menu_inline_kb())
        return
    fill, back = COLOR_PRESETS[key]
    opts = context.user_data.get("qr_opts", default_opts())
    await q.edit_message_text(f"⏳ Bikin QR {COLOR_LABELS.get(key, key)}...")
    await send_qr(
        update, context, content,
        kind=kind, title=title,
        fill=fill, back=back,
        size=opts.get("size", "medium" if not logo_bytes else "large"),
        style=opts.get("style", "rounded"),
        ec=opts.get("ec", "H"),
        gradient=opts.get("gradient", True),
        logo_bytes=logo_bytes,
        edit_msg=q.message,
    )
    for k in ("pending_qr", "pending_kind", "pending_title", "pending_logo", "mode"):
        context.user_data.pop(k, None)


async def cb_qr_from(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    url = q.data.split("qr_from:", 1)[-1]
    context.user_data["pending_qr"] = url
    context.user_data["pending_kind"] = "url"
    context.user_data["mode"] = "qr_pick_color"
    await q.edit_message_text(
        f"Pilih warna QR:\n`{url}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=quick_color_kb(),
    )


async def cb_myqr_actions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    if not await require_sub(update, context):
        return
    uid = q.from_user.id
    data = q.data

    if data.startswith("openqr:"):
        code = data.split(":", 1)[1]
        item = get_qr_item(code, uid)
        if not item:
            await q.answer("QR tidak ditemukan", show_alert=True)
            return
        await q.edit_message_text(
            f"🗂 *QR `{code}`*\n"
            f"Status: {item_status_label(item)}\n"
            f"Jenis: `{item.get('kind')}`\n"
            f"Judul: {item.get('title') or '—'}\n"
            f"Isi:\n`{item.get('content', '')[:300]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=qr_detail_kb(code),
        )
        return

    if data.startswith("regen:"):
        code = data.split(":", 1)[1]
        item = get_qr_item(code, uid)
        if not item or item.get("status") != "active":
            await q.answer("QR tidak aktif / expired / revoked", show_alert=True)
            return
        context.user_data["pending_qr"] = item["content"]
        context.user_data["pending_kind"] = item.get("kind", "text")
        context.user_data["pending_title"] = item.get("title") or item.get("kind")
        context.user_data["mode"] = "qr_pick_color"
        await q.edit_message_text("Pilih warna untuk regenerate:", reply_markup=quick_color_kb())
        return

    if data.startswith("editqr:"):
        code = data.split(":", 1)[1]
        item = get_qr_item(code, uid)
        if not item:
            await q.answer("Tidak ditemukan", show_alert=True)
            return
        context.user_data["mode"] = "edit_qr"
        context.user_data["edit_code"] = code
        await q.edit_message_text(
            f"✏️ Edit QR `{code}`\n\nKirim *isi baru*:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_inline_kb(),
        )
        return

    if data.startswith("expqr:"):
        code = data.split(":", 1)[1]
        await q.edit_message_text(
            f"⏳ Set expiry QR `{code}`:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=expiry_kb("doexpqr", code),
        )
        return

    if data.startswith("doexpqr:"):
        _, code, token = data.split(":", 2)
        hours = parse_expiry_token(token)
        item = set_qr_expiry(code, uid, hours)
        if not item:
            await q.answer("Gagal", show_alert=True)
            return
        await q.edit_message_text(
            f"✅ Expiry QR `{code}` di-set: *{token}*\n{item_status_label(item)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=qr_detail_kb(code),
        )
        return

    if data.startswith("revqr:"):
        code = data.split(":", 1)[1]
        ok = revoke_qr_item(code, uid)
        await q.edit_message_text(
            f"{'🚫 QR revoked' if ok else 'Gagal revoke'} `{code}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_inline_kb(),
        )
        return

    if data.startswith("expsh:"):
        code = data.split(":", 1)[1]
        await q.edit_message_text(
            f"⏳ Set expiry short `{code}`:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=expiry_kb("doexpsh", code),
        )
        return

    if data.startswith("doexpsh:"):
        _, code, token = data.split(":", 2)
        hours = parse_expiry_token(token)
        item = set_short_expiry(code, uid, hours)
        if not item:
            await q.answer("Gagal", show_alert=True)
            return
        await q.edit_message_text(
            f"✅ Expiry short `{code}`: *{token}*\n{item_status_label(item)}",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_inline_kb(),
        )
        return

    if data.startswith("revsh:"):
        code = data.split(":", 1)[1]
        ok = revoke_short_item(code, uid)
        await q.edit_message_text(
            f"{'🚫 Short revoked' if ok else 'Gagal'} `{code}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_inline_kb(),
        )
        return


async def show_my_qr(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    uid = update.effective_user.id
    items = list_qr_items(uid, 20)
    shorts = list_short_items(uid, 10)
    if not items and not shorts:
        text = "🗂 *My QR*\n\nBelum ada QR tersimpan.\nBuat dulu via menu 📱"
        kb = menu_inline_kb()
    else:
        lines = ["🗂 *My QR / Short*", "──────────────"]
        for it in items[:10]:
            lines.append(
                f"{'🚫' if it['status']=='revoked' else '✅'} `{it['code']}` · {it.get('kind')} · {it.get('title','')[:20]}"
            )
        if shorts:
            lines.append("\n*Short:*")
            for s in shorts[:5]:
                lines.append(f"{'🚫' if s['status']=='revoked' else '🔗'} `{s['code']}` → {s['shortened']}")
        text = "\n".join(lines)
        kb = myqr_kb(items) if items else menu_inline_kb()
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb,
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)


async def show_history(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    from modules.db import get_conn
    uid = update.effective_user.id
    c = get_conn()
    qrs = c.execute(
        "SELECT content FROM qr_logs WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)
    ).fetchall()
    shorts = c.execute(
        "SELECT shortened FROM short_logs WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid,)
    ).fetchall()
    c.close()
    user = get_user(uid) or {}
    lines = [
        f"🕘 *Riwayat*",
        f"QR gen: {user.get('qr_count',0)} · Short: {user.get('short_count',0)}",
        "──────────────",
        "*QR log:*",
    ]
    lines += [f"• `{r['content'][:60]}`" for r in qrs] or ["_kosong_"]
    lines.append("\n*Short log:*")
    lines += [f"• `{r['shortened']}`" for r in shorts] or ["_kosong_"]
    text = "\n".join(lines)
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
    )


async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    text = (
        f"ℹ️ *Bantuan {BRAND_NAME}*\n\n"
        f"1. Join [@{CHANNEL_USERNAME}](https://t.me/{CHANNEL_USERNAME})\n"
        f"2. `/start` → welcome → menu\n\n"
        f"*Fitur*\n"
        f"📱 QR · 🔗 Short · ✨ QR+Short · 🖼 Logo\n"
        f"👤 vCard · 📍 Location · 📅 Calendar\n"
        f"💳 Payment · 📶 WiFi · 📦 Bulk\n"
        f"🗂 My QR · ✏️ Edit · ⏳ Expiry · 🚫 Revoke\n"
        f"🎨 Custom (warna/ukuran/style/EC/gradient)\n\n"
        f"*Command*\n"
        f"`/qr` `/short` `/qrshort` `/logo` `/vcard`\n"
        f"`/loc` `/event` `/pay` `/bulk` `/myqr` `/custom` `/menu`"
    )
    if is_admin(update.effective_user.id):
        text += "\n\n*Admin*\n`/users` `/setname` `/stats` `/broadcast`"
    if edit and update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
                disable_web_page_preview=True,
            )
            return
        except BadRequest:
            pass
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_inline_kb(),
        disable_web_page_preview=True,
    )


# ── Commands ──────────────────────────────────────────────────────

async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_sub(update, context):
        return
    context.user_data.clear()
    await send_menu(update, context)


async def cmd_simple_mode(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, prompt: str):
    if not await require_sub(update, context):
        return
    if context.args:
        await handle_mode_text(update, context, mode, " ".join(context.args))
        return
    await enter_mode(update, context, mode, prompt)


async def cmd_qr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "qr_wait_content", "📱 Kirim URL/teks:")


async def cmd_short(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "short", "🔗 Kirim URL: `url | 24h`")


async def cmd_qrshort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "qrshort", "✨ Kirim URL:")


async def cmd_logo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "logo_content", "🖼 Kirim URL/teks dulu, lalu foto logo")


async def cmd_vcard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "vcard", "👤 `Nama | telp | email | org | website`")


async def cmd_loc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "loc", "📍 `lat,lon | label` atau alamat")


async def cmd_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(
        update, context, "event",
        "📅 `Judul | start | end | lokasi | deskripsi`",
    )


async def cmd_pay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "pay", "💳 `penerima | jumlah | catatan`")


async def cmd_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await cmd_simple_mode(update, context, "bulk", "📦 Kirim multi-baris (maks 20)")


async def cmd_myqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_sub(update, context):
        return
    await show_my_qr(update, context)


async def cmd_custom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_sub(update, context):
        return
    await open_custom_panel(update, context)


# ── Text mode processing ──────────────────────────────────────────

async def handle_mode_text(update, context, mode: str, text: str):
    opts = context.user_data.get("qr_opts", default_opts())

    if mode == "qr_wait_content":
        context.user_data["pending_qr"] = text
        context.user_data["pending_kind"] = "text"
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text(
            f"Pilih warna:\n`{text[:120]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=quick_color_kb(),
        )
        return

    if mode == "custom_content":
        fill, back = COLOR_PRESETS.get(opts.get("color", "blue"), COLOR_PRESETS["blue"])
        context.user_data["mode"] = None
        await send_qr(
            update, context, text, kind="custom", title="custom",
            fill=fill, back=back,
            size=opts.get("size", "medium"),
            style=opts.get("style", "rounded"),
            ec=opts.get("ec", "H"),
            gradient=opts.get("gradient", True),
            caption_extra=f"⚙️ `{opts_summary(opts)}`",
        )
        return

    if mode == "short":
        context.user_data["mode"] = None
        parts = split_pipe(text)
        url = parts[0]
        hours = parse_expiry_token(parts[1]) if len(parts) > 1 else None
        await do_short(update, context, url, expires_hours=hours)
        return

    if mode == "qrshort":
        context.user_data["mode"] = None
        short = await do_short(update, context, text)
        if short:
            context.user_data["pending_qr"] = short
            context.user_data["pending_kind"] = "url"
            context.user_data["mode"] = "qr_pick_color"
            await update.effective_message.reply_text(
                f"Pilih warna QR:\n`{short}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=quick_color_kb(),
            )
        return

    if mode == "logo_content":
        context.user_data["pending_qr"] = text
        context.user_data["pending_kind"] = "logo"
        context.user_data["mode"] = "logo_photo"
        await update.effective_message.reply_text(
            "✅ Konten disimpan.\nSekarang *kirim foto logo* (bukan file dokumen).",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_inline_kb(),
        )
        return

    if mode == "vcard":
        parts = split_pipe(text)
        if not parts or not parts[0]:
            await update.effective_message.reply_text(
                "Format: `Nama | telp | email | org | website`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_inline_kb(),
            )
            return
        payload = make_vcard(
            name=parts[0],
            phone=parts[1] if len(parts) > 1 else "",
            email=parts[2] if len(parts) > 2 else "",
            org=parts[3] if len(parts) > 3 else "",
            website=parts[4] if len(parts) > 4 else "",
        )
        context.user_data["pending_qr"] = payload
        context.user_data["pending_kind"] = "vcard"
        context.user_data["pending_title"] = parts[0]
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text(
            f"👤 vCard *{parts[0]}* siap. Pilih warna:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=quick_color_kb(),
        )
        return

    if mode == "loc":
        parts = split_pipe(text)
        raw = parts[0]
        label = parts[1] if len(parts) > 1 else ""
        if "," in raw and all(p.replace(".", "", 1).replace("-", "", 1).isdigit() for p in raw.split(",")[:2]):
            try:
                lat_s, lon_s = [x.strip() for x in raw.split(",", 1)]
                payload = make_geo(float(lat_s), float(lon_s), label)
            except Exception:
                payload = make_maps_query(raw)
        else:
            payload = make_maps_query(raw if not label else f"{raw} {label}")
        context.user_data["pending_qr"] = payload
        context.user_data["pending_kind"] = "location"
        context.user_data["pending_title"] = label or raw[:30]
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text(
            "📍 Location QR siap. Pilih warna:",
            reply_markup=quick_color_kb(),
        )
        return

    if mode == "event":
        parts = split_pipe(text)
        if len(parts) < 2:
            await update.effective_message.reply_text(
                "Format: `Judul | start | end | lokasi | deskripsi`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_inline_kb(),
            )
            return
        start = parse_dt(parts[1])
        if not start:
            await update.effective_message.reply_text(
                "Tanggal start invalid. Pakai `YYYY-MM-DD HH:MM`",
                reply_markup=cancel_inline_kb(),
            )
            return
        end = parse_dt(parts[2]) if len(parts) > 2 and parts[2] else None
        payload = make_calendar(
            title=parts[0],
            start=start,
            end=end,
            location=parts[3] if len(parts) > 3 else "",
            description=parts[4] if len(parts) > 4 else "",
        )
        context.user_data["pending_qr"] = payload
        context.user_data["pending_kind"] = "calendar"
        context.user_data["pending_title"] = parts[0]
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text(
            f"📅 Event *{parts[0]}* siap. Pilih warna:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=quick_color_kb(),
        )
        return

    if mode == "wifi":
        parts = split_pipe(text)
        if not parts or not parts[0]:
            await update.effective_message.reply_text(
                "Format: `SSID | password | WPA`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_inline_kb(),
            )
            return
        ssid = parts[0]
        password = parts[1] if len(parts) > 1 else ""
        enc = (parts[2] if len(parts) > 2 else "WPA").upper()
        if enc not in ("WPA", "WEP", "NOPASS"):
            enc = "WPA"
        payload = f"WIFI:T:nopass;S:{ssid};;" if enc == "NOPASS" else f"WIFI:T:{enc};S:{ssid};P:{password};;"
        context.user_data["pending_qr"] = payload
        context.user_data["pending_kind"] = "wifi"
        context.user_data["pending_title"] = ssid
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text("📶 Pilih warna QR WiFi:", reply_markup=quick_color_kb())
        return

    if mode == "pay":
        parts = split_pipe(text)
        if not parts or not parts[0]:
            await update.effective_message.reply_text(
                "Format: `penerima | jumlah | catatan`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_inline_kb(),
            )
            return
        lines = ["PAYMENT", f"Recipient: {parts[0]}"]
        if len(parts) > 1 and parts[1]:
            lines.append(f"Amount: IDR {parts[1]}")
        if len(parts) > 2 and parts[2]:
            lines.append(f"Note: {parts[2]}")
        payload = "\n".join(lines)
        context.user_data["pending_qr"] = payload
        context.user_data["pending_kind"] = "payment"
        context.user_data["pending_title"] = parts[0][:30]
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text(
            f"💳 Payment *{parts[0]}* siap. Pilih warna:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=quick_color_kb(),
        )
        return

    if mode == "bulk":
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:20]
        if not lines:
            await update.effective_message.reply_text("Kosong. Kirim multi-baris.")
            return
        context.user_data["mode"] = None
        wait = await update.effective_message.reply_text(f"📦 Generate {len(lines)} QR...")
        fill, back = COLOR_PRESETS.get(opts.get("color", "blue"), COLOR_PRESETS["blue"])
        ok = 0
        for i, line in enumerate(lines, 1):
            try:
                await send_qr(
                    update, context, line,
                    kind="bulk", title=f"bulk-{i}",
                    fill=fill, back=back,
                    size="small",
                    style=opts.get("style", "rounded"),
                    ec=opts.get("ec", "H"),
                    gradient=opts.get("gradient", True),
                )
                ok += 1
            except Exception:
                log.exception("bulk item fail")
        try:
            await wait.edit_text(f"✅ Bulk selesai: {ok}/{len(lines)} QR")
        except Exception:
            pass
        return

    if mode == "edit_qr":
        code = context.user_data.get("edit_code")
        context.user_data["mode"] = None
        if not code:
            await update.effective_message.reply_text("Sesi edit habis.")
            return
        item = edit_qr_item(code, update.effective_user.id, text)
        if not item:
            await update.effective_message.reply_text("Gagal edit / tidak ditemukan.")
            return
        await update.effective_message.reply_text(
            f"✅ QR `{code}` diupdate.\nIsi baru:\n`{text[:200]}`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=qr_detail_kb(code),
        )
        # also regenerate preview
        context.user_data["pending_qr"] = text
        context.user_data["pending_kind"] = item.get("kind", "text")
        context.user_data["pending_title"] = item.get("title") or code
        context.user_data["mode"] = "qr_pick_color"
        await update.effective_message.reply_text("Generate ulang? Pilih warna:", reply_markup=quick_color_kb())
        return

    context.user_data.clear()
    await update.effective_message.reply_text("Sesi habis. Buka menu lagi.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_sub(update, context):
        return
    text = (update.message.text or "").strip()
    uid = update.effective_user.id
    upsert_user(uid, update.effective_user.username or "", update.effective_user.full_name or "")

    mapping = {
        BTN_QR: ("qr_wait_content", "📱 Kirim URL/teks:"),
        BTN_SHORT: ("short", "🔗 Kirim URL (`url | 24h`):"),
        BTN_QRSHORT: ("qrshort", "✨ Kirim URL:"),
        BTN_LOGO: ("logo_content", "🖼 Kirim URL/teks dulu, lalu foto logo"),
        BTN_VCARD: ("vcard", "👤 `Nama | telp | email | org | website`"),
        BTN_LOC: ("loc", "📍 `lat,lon | label` atau alamat"),
        BTN_EVENT: ("event", "📅 `Judul | start | end | lokasi | deskripsi`"),
        BTN_PAY: ("pay", "💳 `penerima | jumlah | catatan`"),
        BTN_WIFI: ("wifi", "📶 `SSID | password | WPA`"),
        BTN_BULK: ("bulk", "📦 Kirim multi-baris (maks 20)"),
    }
    if text in mapping:
        mode, prompt = mapping[text]
        await enter_mode(update, context, mode, prompt)
        return
    if text == BTN_MYQR:
        await show_my_qr(update, context)
        return
    if text == BTN_HISTORY:
        await show_history(update, context)
        return
    if text == BTN_HELP:
        await show_help(update, context)
        return
    if text in (BTN_CANCEL, BTN_MENU):
        context.user_data.clear()
        await send_menu(update, context)
        return

    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text("Pilih fitur dulu 👇", reply_markup=reply_menu_kb())
        await send_menu(update, context)
        return
    await handle_mode_text(update, context, mode, text)


async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await require_sub(update, context):
        return
    mode = context.user_data.get("mode")
    if mode != "logo_photo":
        await update.message.reply_text(
            "Foto logo dipakai di mode 🖼 QR Logo.\nPilih menu *QR Logo* dulu.",
            reply_markup=reply_menu_kb(),
        )
        return
    content = context.user_data.get("pending_qr")
    if not content:
        context.user_data["mode"] = "logo_content"
        await update.message.reply_text("Kirim URL/teks dulu, baru foto logo.")
        return
    photo = update.message.photo[-1]
    f = await context.bot.get_file(photo.file_id)
    bio = BytesIO()
    await f.download_to_memory(out=bio)
    logo_bytes = bio.getvalue()
    context.user_data["pending_logo"] = logo_bytes
    context.user_data["pending_kind"] = "logo"
    context.user_data["mode"] = "qr_pick_color"
    await update.message.reply_text(
        "✅ Logo diterima. Pilih warna QR:",
        reply_markup=quick_color_kb(),
    )


# ── Admin ─────────────────────────────────────────────────────────

async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    rows = all_users()
    st = stats()
    lines = [
        f"👥 *Users* ({st['users']}) · QR {st['qr']} · Short {st['short']}",
        f"Active items: QR {st['qr_active']} · Short {st['short_active']}",
        "──────────────",
    ]
    for r in rows[:50]:
        un = f"@{r['username']}" if r.get("username") else "—"
        name = r.get("name") or r.get("full_name") or "—"
        lines.append(
            f"`{r['user_id']}` · {un}\n  📝 {name} · qr:{r.get('qr_count',0)} short:{r.get('short_count',0)}"
        )
    lines.append("\n`/setname <id> <nama>`")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def cmd_setname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/setname <user_id> <nama>`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("user_id harus angka")
        return
    name = " ".join(context.args[1:])
    if not get_user(uid):
        upsert_user(uid, "", name)
    set_user_name(uid, name)
    u2 = get_user(uid) or {}
    await update.message.reply_text(
        f"✅ ID `{uid}` · @{u2.get('username') or '—'} · nama *{name}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    st = stats()
    await update.message.reply_text(
        f"📊 *Stats*\nUsers: {st['users']}\nQR gen: {st['qr']}\nShort gen: {st['short']}\n"
        f"QR aktif: {st['qr_active']}\nShort aktif: {st['short_active']}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/broadcast pesan...`", parse_mode=ParseMode.MARKDOWN)
        return
    msg = " ".join(context.args)
    ok = fail = 0
    for r in all_users():
        try:
            await context.bot.send_message(r["user_id"], f"📢 {msg}")
            ok += 1
        except Exception:
            fail += 1
    await update.message.reply_text(f"Broadcast: ✅{ok} ❌{fail}")


def main():
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN missing")
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("menu", cmd_menu))
    app.add_handler(CommandHandler("qr", cmd_qr))
    app.add_handler(CommandHandler("short", cmd_short))
    app.add_handler(CommandHandler("qrshort", cmd_qrshort))
    app.add_handler(CommandHandler("logo", cmd_logo))
    app.add_handler(CommandHandler("vcard", cmd_vcard))
    app.add_handler(CommandHandler("loc", cmd_loc))
    app.add_handler(CommandHandler("event", cmd_event))
    app.add_handler(CommandHandler("pay", cmd_pay))
    app.add_handler(CommandHandler("bulk", cmd_bulk))
    app.add_handler(CommandHandler("myqr", cmd_myqr))
    app.add_handler(CommandHandler("custom", cmd_custom))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("setname", cmd_setname))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))

    app.add_handler(CallbackQueryHandler(cb_check_sub, pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(cb_open_menu, pattern="^open_menu$"))
    app.add_handler(CallbackQueryHandler(cb_cancel, pattern="^cancel_mode$"))
    app.add_handler(CallbackQueryHandler(cb_menu, pattern="^menu_"))
    app.add_handler(CallbackQueryHandler(cb_opt, pattern="^(opt_|set_)"))
    app.add_handler(CallbackQueryHandler(cb_quick_color, pattern="^qcolor_"))
    app.add_handler(CallbackQueryHandler(cb_qr_from, pattern="^qr_from:"))
    app.add_handler(CallbackQueryHandler(
        cb_myqr_actions,
        pattern="^(openqr:|regen:|editqr:|expqr:|doexpqr:|revqr:|expsh:|doexpsh:|revsh:)",
    ))

    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    log.info("%s starting...", BRAND_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
