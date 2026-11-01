import os, re, json, hmac, hashlib, html, urllib.request
from fastapi import Header, HTTPException
from server import app, TOKEN, BOT_USER

# Render сам задаёт RENDER_EXTERNAL_URL; для другого хостинга укажите PUBLIC_URL
BASE = (os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PUBLIC_URL") or "").rstrip("/")
SECRET = hashlib.sha256(("wh:" + TOKEN).encode()).hexdigest()[:40]


def tg(method, **p):
    try:
        req = urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", json.dumps(p).encode(),
                                     {"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=10))
    except Exception as e:
        print("telegram error:", method, e)


@app.on_event("startup")
def set_hook():
    if TOKEN and BASE:
        tg("setWebhook", url=BASE + "/tg", secret_token=SECRET, allowed_updates=["message"])


def welcome(m):
    name = html.escape(m.get("from", {}).get("first_name", "друг"))[:30]
    text = (m.get("text") or "").strip()
    payload = re.sub(r"[^A-Za-z0-9_-]", "", text[6:].strip())[:64] if text.startswith("/start") else ""
    btn = {"text": "🎮 Играть"}
    if payload and BOT_USER:  # переход по реферальной ссылке: передаём ref_… в Mini App
        btn["url"] = f"https://t.me/{BOT_USER}?startapp={payload}"
    else:
        btn["web_app"] = {"url": BASE}
    msg = (f"👋 Привет, {name}!\n\n<b>STYLE MARKET</b>: открывай контейнеры, собирай гардероб, "
           "торгуй на рынке и аукционе и поднимайся в рейтинге.\n\n"
           "🎁 Каждый день: награда и бесплатные контейнеры.\n"
           "👥 За каждого приглашённого друга: +20 000 ₽.\n\nЖми «Играть».")
    tg("sendMessage", chat_id=m["chat"]["id"], text=msg, parse_mode="HTML",
       reply_markup={"inline_keyboard": [[btn]]} if BASE else None)


@app.post("/tg")
def webhook(u: dict, x_telegram_bot_api_secret_token: str = Header("")):
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, SECRET):
        raise HTTPException(403, "forbidden")
    m = u.get("message") or {}
    if m.get("chat", {}).get("type") == "private":
        welcome(m)
    return {"ok": True}
