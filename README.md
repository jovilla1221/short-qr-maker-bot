# Aonagi QR Tools

Bot Telegram: **QR Code + URL Shortener** + force-sub channel + admin registry.

## Fitur
- 🔒 Force sub ke `@botunlverse`
- 👋 Welcome dengan nama (admin set via `/setname`)
- 📱 `/qr <url|text>` — generate QR (blue gradient, rounded)
- 🔗 `/short <url>` — TinyURL shortener
- ✨ `/qrshort <url>` — short dulu, QR-nya dikirim
- 👑 Admin: `/users`, `/setname <id> <nama>`, `/stats`, `/broadcast`

## Setup
```bash
cd /home/filla_saputro/qr-short-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# isi BOT_TOKEN dari @BotFather
python bot.py
```

## Env
| Key | Contoh |
|-----|--------|
| BOT_TOKEN | dari @BotFather |
| ADMIN_IDS | 6247336698,1015145644 |
| CHANNEL_USERNAME | botunlverse |
| CHANNEL_ID | -1002720892156 |
| BRAND_NAME | Aonagi QR Tools |

## Catatan
- Bot **harus admin** di channel `@botunlverse` biar force-sub `getChatMember` jalan.
- TinyURL free, no key.
