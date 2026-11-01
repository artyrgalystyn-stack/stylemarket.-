import os, re, time, html, random, hmac, sqlite3
from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
import main, launch
from server import app, db, L, auth, pget, rid, err
from gate import subscribed, CHANNEL

PRICE = int(os.getenv("CLAN_PRICE", "100"))  # цена создания клана в Telegram Stars
MAXM = 30  # максимум участников
tg, SECRET, BASE = main.tg, main.SECRET, main.BASE

db.executescript("""
create table if not exists clans(id integer primary key autoincrement,name text unique collate nocase,owner text,created int,wins int default 0);
create table if not exists cm(uid text primary key,clan int);
create table if not exists pend(id text primary key,uid text,name text,ts int);
create table if not exists pays(charge text primary key);
create table if not exists wars(id integer primary key autoincrement,week text,a int,b int,bs int default 0,done int default 0);
""")

now = lambda: int(time.time())
week = lambda: time.strftime("%G-%V", time.gmtime())


def left():  # секунд до понедельника 00:00 UTC
    t = time.gmtime()
    return ((7 - t.tm_wday) % 7 or 7) * 86400 - (t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec)


def one(q, *a):
    r = db.execute(q, a).fetchone()
    return r[0] if r else None


cscore = lambda c: one("select coalesce(sum(p.score),0) from cm join p on p.id=cm.uid where cm.clan=?", c) or 0
my_clan = lambda u: one("select clan from cm where uid=?", u)
csize = lambda c: one("select count(*) from cm where clan=?", c)


def bot_score():
    rows = [cscore(r[0]) for r in db.execute("select id from clans").fetchall()]
    return int(max(20000, sum(rows) / len(rows) if rows else 0) * random.uniform(.8, 1.2))


def war_tick():  # итоги прошлых недель и пары на текущую
    w = week()
    for wid, a, b, bs in db.execute("select id,a,b,bs from wars where done=0 and week<>?", (w,)).fetchall():
        sa, sb = cscore(a), (cscore(b) if b else bs)
        win = a if sa >= sb else b
        if win: db.execute("update clans set wins=wins+1 where id=?", (win,))
        db.execute("update wars set done=1 where id=?", (wid,))
    if not one("select 1 from wars where week=?", w):
        ids = [r[0] for r in db.execute("select id from clans").fetchall()]
        random.shuffle(ids)
        for k in range(0, len(ids), 2):
            b = ids[k + 1] if k + 1 < len(ids) else None
            db.execute("insert into wars(week,a,b,bs) values(?,?,?,?)", (w, ids[k], b, 0 if b else bot_score()))
    db.commit()


def make_clan(uid, name):
    try:
        c = db.execute("insert into clans(name,owner,created) values(?,?,?)", (name, uid, now())).lastrowid
        db.execute("insert into cm values(?,?)", (uid, c))
        db.execute("insert into wars(week,a,b,bs) values(?,?,NULL,?)", (week(), c, bot_score()))
        db.commit()
    except Exception:
        db.rollback(); raise


def vname(n):
    n = re.sub(r"\s+", " ", (n or "").strip())
    if not re.fullmatch(r"[\w .\-]{3,20}", n): err("Название: 3-20 символов, буквы, цифры, пробел . _ -")
    return n


def info(u):
    c = my_clan(u); out = {"price": PRICE, "max": MAXM, "clan": None, "war": None}
    if c:
        name, owner, wins = db.execute("select name,owner,wins from clans where id=?", (c,)).fetchone()
        top = db.execute("select p.name,p.score,p.id from cm join p on p.id=cm.uid where cm.clan=? order by p.score desc limit 15", (c,)).fetchall()
        out["clan"] = {"id": c, "name": name, "members": csize(c), "score": cscore(c), "wins": wins, "owner": owner == u,
                       "top": [{"n": r[0] or "Игрок", "s": r[1], "o": r[2] == owner} for r in top]}
        r = db.execute("select a,b,bs from wars where week=? and (a=? or b=?)", (week(), c, c)).fetchone()
        if r:
            opp = r[1] if r[0] == c else r[0]
            out["war"] = {"opp": one("select name from clans where id=?", opp) if opp else "Street Bots",
                          "my": cscore(c), "their": cscore(opp) if opp else r[2], "left": left()}
    else:
        out["top"] = [{"id": r[0], "n": r[1], "m": r[2], "s": r[3]} for r in db.execute(
            "select c.id,c.name,(select count(*) from cm where clan=c.id) m,"
            "(select coalesce(sum(p.score),0) from cm join p on p.id=cm.uid where cm.clan=c.id) s "
            "from clans c order by s desc limit 15").fetchall()]
    return out


class Cl(BaseModel):
    a: str
    name: str = ""
    id: int = 0


@app.post("/api/clan")
def clan_api(b: Cl, x_init: str = Header("")):
    uid, _ = auth(x_init)
    if not subscribed(uid): return JSONResponse({"detail": "sub", "ch": CHANNEL}, status_code=403)
    with L:
        if not pget(uid): err("Сначала откройте игру")
        war_tick(); c = my_clan(uid); ex = {}
        if b.a == "join":
            if c: err("Вы уже в клане")
            if not one("select 1 from clans where id=?", b.id): err("Клан не найден")
            if csize(b.id) >= MAXM: err("В клане нет мест")
            db.execute("insert into cm values(?,?)", (uid, b.id)); db.commit()
        elif b.a == "leave":
            if not c: err("Вы не в клане")
            db.execute("delete from cm where uid=?", (uid,))
            nxt = one("select uid from cm where clan=? order by rowid limit 1", c)
            if not nxt:
                db.execute("delete from clans where id=?", (c,)); db.execute("delete from wars where (a=? or b=?) and done=0", (c, c))
            elif one("select owner from clans where id=?", c) == uid:
                db.execute("update clans set owner=? where id=?", (nxt, c))
            db.commit()
        elif b.a == "buy":
            if c: err("Вы уже в клане")
            n = vname(b.name)
            if one("select 1 from clans where name=?", n): err("Название занято")
            pid = rid()
            db.execute("delete from pend where uid=?", (uid,))
            db.execute("insert into pend values(?,?,?,?)", (pid, uid, n, now())); db.commit()
            r = tg("createInvoiceLink", title="Создание клана", description="Клан «%s»" % n, payload="clan:" + pid,
                   currency="XTR", prices=[{"label": "Создание клана", "amount": PRICE}])
            if not r or not r.get("ok"): err("Не удалось создать счёт, попробуйте позже")
            ex = {"link": r["result"]}
        elif b.a != "info": err("Неизвестное действие")
        return {**info(uid), **ex}


# ---------- оплата Stars (вебхук Telegram) ----------
def on_precheckout(q):
    row = db.execute("select uid,name from pend where id=?", (q.get("invoice_payload", "")[5:],)).fetchone()
    msg = ""
    if not row or str(q["from"]["id"]) != row[0]: msg = "Счёт устарел"
    elif q.get("currency") != "XTR" or q.get("total_amount") != PRICE: msg = "Неверная сумма"
    elif one("select 1 from clans where name=?", row[1]): msg = "Это название уже занято"
    elif my_clan(row[0]): msg = "Вы уже в клане"
    tg("answerPreCheckoutQuery", pre_checkout_query_id=q["id"], ok=not msg, **({"error_message": msg} if msg else {}))


def on_paid(m):
    sp = m["successful_payment"]; uid = str(m["from"]["id"]); ch = sp["telegram_payment_charge_id"]; pl = sp.get("invoice_payload", "")
    if not pl.startswith("clan:") or one("select 1 from pays where charge=?", ch): return
    db.execute("insert into pays values(?)", (ch,)); db.commit()
    row = db.execute("select uid,name from pend where id=?", (pl[5:],)).fetchone()
    try:
        if not row or row[0] != uid: raise ValueError("pending")
        make_clan(uid, row[1]); db.execute("delete from pend where id=?", (pl[5:],)); db.commit()
        tg("sendMessage", chat_id=m["chat"]["id"], text="🛡 Клан «%s» создан! Откройте игру, вкладка «Друзья»." % html.escape(row[1]))
    except Exception:
        tg("refundStarPayment", user_id=int(uid), telegram_payment_charge_id=ch)
        tg("sendMessage", chat_id=m["chat"]["id"], text="Не удалось создать клан, Stars возвращены.")


app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in ("/tg", "/patch.js")]


@app.post("/tg")
def webhook2(u: dict, x_telegram_bot_api_secret_token: str = Header("")):
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, SECRET): raise HTTPException(403, "forbidden")
    with L:
        if "pre_checkout_query" in u: on_precheckout(u["pre_checkout_query"]); return {"ok": True}
        m = u.get("message") or {}
        if m.get("successful_payment"): on_paid(m); return {"ok": True}
    return main.webhook(u, x_telegram_bot_api_secret_token)


@app.on_event("startup")
def hook2():  # повторно ставим вебхук, добавив события оплаты
    if main.TOKEN and BASE:
        tg("setWebhook", url=BASE + "/tg", secret_token=SECRET, allowed_updates=["message", "pre_checkout_query"])


@app.get("/patch.js")
def patch_js():
    js = launch.read("patch.js") + launch.GATE_JS + "\n" + launch.read("ui.js") + "\n" + launch.read("clans.js")
    return Response(js, media_type="application/javascript")
