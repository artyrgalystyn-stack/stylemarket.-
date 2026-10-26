import os, re, json, time, hmac, hashlib, random, sqlite3, threading
from urllib.parse import parse_qsl
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USER = os.getenv("BOT_USER", "")
DEV = os.getenv("DEV") == "1"  # DEV=1 разрешает запуск без Telegram
DIR = os.path.dirname(os.path.abspath(__file__))
RW = [55, 25, 12, 5.5, 2, .5]
CATS = {"sneaker", "hoodie", "tee", "jacket", "jeans", "bag", "cap", "watch"}
# (бренд+название, категория, редкость, базовая цена)
I = [("NVRST Basic Tee", "tee", 0, 1500), ("DRIPZONE Daily Cap", "cap", 0, 1800),
     ("BLVCKFORM Straight Jeans", "jeans", 0, 3200), ("NVRST Street Low", "sneaker", 0, 5500),
     ("DRIPZONE Cloud Hoodie", "hoodie", 1, 6500), ("AERONIX Track Jacket", "jacket", 1, 8500),
     ("NORTHLINE Trail Pack", "bag", 1, 7000), ("DRIPZONE Graphic Tee", "tee", 1, 3800),
     ("AERONIX Pulse Runner", "sneaker", 2, 14000), ("BLVCKFORM Raw Denim", "jeans", 2, 12000),
     ("NORTHLINE Storm Parka", "jacket", 2, 24000), ("VELTRIX Apex Runner", "sneaker", 3, 29000),
     ("MONTEVO Studio Tote", "bag", 3, 38000), ("MONTEVO Noir Coat", "jacket", 4, 120000),
     ("MONTEVO Chrono Gold", "watch", 4, 180000), ("RARESTEP Genesis 1", "sneaker", 5, 480000),
     ("BLVCKFORM Core Hoodie", "hoodie", 2, 13000), ("NVRST Logo Cap", "cap", 1, 2900)]
BN = ["Vlad", "Mira", "Kenji", "Dasha", "Alex", "Nika"]

L = threading.RLock()
db = sqlite3.connect(os.path.join(DIR, "game.db"), check_same_thread=False)
db.executescript("create table if not exists p(id text primary key,st text,score int default 0,name text);"
                 "create table if not exists kv(k text primary key,v text)")
now = lambda: int(time.time() * 1000)
rd = lambda x: int(x + .5)
rid = lambda: "%x%x" % (random.getrandbits(40), now())
day = lambda: time.strftime("%Y-%m-%d", time.gmtime())


def err(m): raise HTTPException(400, m)


def kget(k, d):
    r = db.execute("select v from kv where k=?", (k,)).fetchone()
    return json.loads(r[0]) if r else d


G = kget("g", {"mk": [], "mt": 0, "au": []})  # общий рынок и аукционы


def fresh():
    return {"bal": 50000, "xp": 0, "inv": [], "opened": 0, "sold": 0, "bought": 0, "free": 5, "fd": day(),
            "daily": "", "t": {"o": 0, "s": 0, "b": 0, "c": {}}, "h": [], "refs": 0}


def pget(u):
    r = db.execute("select st from p where id=?", (u,)).fetchone()
    if not r: return None
    s = json.loads(r[0])
    if s["fd"] != day(): s.update(free=5, fd=day(), t={"o": 0, "s": 0, "b": 0, "c": {}})
    return s


def pput(u, s, name=None):
    db.execute("insert into p(id,st,score,name) values(?,?,?,?) on conflict(id) do update set "
               "st=excluded.st,score=excluded.score,name=coalesce(excluded.name,name)",
               (u, json.dumps(s), sum(x["val"] for x in s["inv"]), name))
    db.commit()


def edit(u, fn):
    s = pget(u)
    if s: fn(s); pput(u, s)


def log(s, m, d): s["h"].insert(0, {"t": now(), "m": m, "d": d}); del s["h"][60:]
def note(s, m): s.setdefault("ev", []).append(m)


def nm(u):
    r = db.execute("select name from p where id=?", (u,)).fetchone()
    return (r and r[0]) or "Игрок"


# ---------- логика игры (порт из клиента) ----------
def pool(m, c): return [i for i, x in enumerate(I) if (c == "all" or x[1] == c) and x[2] >= m]


def probs(m, c):
    rs = sorted({I[i][2] for i in pool(m, c)}); s = sum(RW[r] for r in rs)
    return [(r, RW[r] / s * 100) for r in rs]


def box_cost(m, c):
    p = pool(m, c)
    if not p: return 0
    rs = sorted({I[i][2] for i in p}); t = sum(RW[r] for r in rs); o = []
    for r in rs:
        it = [i for i in p if I[i][2] == r]
        o += [(RW[r] / t / len(it), I[i][3] * 1.025 * .9) for i in it]
    ev = sum(a * b for a, b in o); q60 = max(v for _, v in o); cu = 0
    for pr, v in sorted(o, key=lambda x: x[1]):
        cu += pr
        if cu >= .6: q60 = v; break
    return max(1000, rd(min(max(q60, ev / 1.5), ev / 1.1) / 500) * 500)


def roll(m, c):
    pr = probs(m, c); x = random.random() * 100; r = pr[-1][0]
    for k, p in pr:
        if x < p: r = k; break
        x -= p
    i = random.choice([i for i in pool(m, c) if I[i][2] == r])
    return {"uid": rid(), "i": i, "val": rd(I[i][3] * (.9 + random.random() * .25) / 10) * 10, "t": now()}


def mk_tick(t):
    if t - G["mt"] > 6e5 or len(G["mk"]) < 4:
        G["mt"] = t
        G["mk"] = [{"id": rid(), "i": i, "p": rd(I[i][3] * (.95 + random.random() * .4) / 10) * 10, "n": k}
                   for k, i in enumerate(random.randrange(len(I)) for _ in range(12))]


def step(c): return max(100, rd(c * .05 / 10) * 10)
def min_bid(a): return a["cur"] + step(a["cur"]) if a["bids"] else a["start"]


def new_au():
    i = random.randrange(len(I)); b = I[i][3]; t = now(); sp = rd(b * .6 / 10) * 10
    return {"id": rid(), "i": i, "val": rd(b * (.9 + random.random() * .25) / 10) * 10, "own": None, "start": sp,
            "cur": sp, "lead": "", "bids": [], "end": t + int((3 + random.random() * 22) * 6e4),
            "nb": t + int((5 + random.random() * 25) * 1e3), "mx": rd(b * (1.05 + random.random() * .5) / 10) * 10,
            "done": False}


def finish(a, t):
    a["done"] = True; a["fin"] = t; n = I[a["i"]][0]; s = a["own"]; w = a["lead"]
    if s:
        if a["bids"]:
            g = rd(a["cur"] * .9)
            def f(x):
                x["bal"] += g; x["sold"] += 1; x["t"]["s"] += 1; x["xp"] += 15
                log(x, "Аукцион: продано " + n, g); note(x, "Лот продан: +%d ₽" % g)
        else:
            def f(x):
                x["inv"].append({"uid": a["uid"], "i": a["i"], "val": a["val"], "t": t})
                log(x, "Аукцион без ставок: " + n, 0); note(x, "Лот вернулся в гардероб")
        edit(s, f)
    if w and w not in BN:
        def f(x):
            x["inv"].append({"uid": rid(), "i": a["i"], "val": a["val"], "t": t})
            x["bought"] += 1; x["t"]["b"] += 1; x["xp"] += 25
            log(x, "Выиграно на аукционе: " + n, 0); note(x, "Вы выиграли: " + n)
        edit(w, f)


def settle():
    t = now(); mk_tick(t)
    for a in G["au"]:
        if a["done"]: continue
        while a["nb"] <= min(t, a["end"]):
            mb = min_bid(a); hl = a["lead"] and a["lead"] not in BN
            if mb <= a["mx"] and (not hl or random.random() < .85) and (not a["lead"] or hl or random.random() < .5):
                if hl:
                    def f(x, c=a["cur"]): x["bal"] += c; log(x, "Ставка перебита", c); note(x, "Вашу ставку перебили")
                    edit(a["lead"], f)
                w = random.choice(BN); a["cur"] = mb; a["lead"] = w; a["bids"].append({"w": w, "p": mb, "t": a["nb"]})
                if a["end"] - a["nb"] < 2e4: a["end"] = int(a["nb"] + 2e4)
            a["nb"] += int((6 + random.random() * 30) * 1e3)
        if t >= a["end"]: finish(a, t)
    G["au"] = [a for a in G["au"] if not a["done"] or t - a["fin"] < 3.6e6]
    while sum(1 for a in G["au"] if not a["done"] and not a["own"]) < 5: G["au"].append(new_au())


def vau(a, u):
    f = lambda w: "me" if w == u else (nm(w) if w and w not in BN else w)
    r = {k: a[k] for k in ("id", "i", "val", "start", "cur", "end", "done")}
    return {**r, "own": a["own"] == u, "lead": f(a["lead"]),
            "bids": [{"w": f(x["w"]), "p": x["p"], "t": x["t"]} for x in a["bids"]]}


def view(u, s):
    v = {k: x for k, x in s.items() if k not in ("daily", "fd", "ev")}
    v.update(dc=s["daily"] == day(), mk=G["mk"], au=[vau(a, u) for a in G["au"]], ev=s.pop("ev", []))
    if BOT_USER: v["bot"] = BOT_USER
    return v


# ---------- авторизация через Telegram initData ----------
def auth(init):
    if not init:
        if DEV: return "local", {"name": "Dev"}
        raise HTTPException(401, "Откройте игру через Telegram")
    d = dict(parse_qsl(init)); h = d.pop("hash", "")
    chk = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    key = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    ok = hmac.compare_digest(hmac.new(key, chk.encode(), hashlib.sha256).hexdigest(), h)
    if not ok or time.time() - int(d.get("auth_date", 0)) > 86400: raise HTTPException(401, "Сессия устарела, перезапустите игру")
    u = json.loads(d["user"])
    return str(u["id"]), {"name": re.sub(r"[<>&\"'`]", "", u.get("first_name", "Игрок"))[:20] or "Игрок",
                          "start": d.get("start_param", "")}


class Act(BaseModel):
    a: str
    m: int = 0
    c: str = "all"
    n: int = 1
    ids: list[str] = []
    id: str = ""
    amt: float = 0
    k: str = ""
    u: str = ""
    sp: float = 0
    d: int = 5


app = FastAPI()


@app.post("/api/act")
def act(b: Act, x_init: str = Header("")):
    uid, info = auth(x_init)
    with L:
        settle()  # до загрузки игрока: settle может менять его баланс
        s = pget(uid)
        if not s:
            s = fresh(); pput(uid, s, info.get("name")); ref = info.get("start", "")
            if ref.startswith("ref_") and ref[4:] != uid:
                def f(x): x["bal"] += 20000; x["refs"] = x.get("refs", 0) + 1; log(x, "Друг в игре", 20000); note(x, "Друг присоединился: +20 000 ₽")
                edit(ref[4:], f)
        ex = {}; a = b.a
        if a == "open":
            if b.m not in range(6) or b.n not in (1, 5, 10) or (b.c != "all" and b.c not in CATS): err("Неверные параметры")
            if not pool(b.m, b.c): err("Нет таких предметов")
            fr = min(s["free"], b.n) if b.m == 0 else 0; cost = (b.n - fr) * box_cost(b.m, b.c)
            if s["bal"] < cost: err("Не хватает ₽")
            s["bal"] -= cost; s["free"] -= fr; res = [roll(b.m, b.c) for _ in range(b.n)]
            s["inv"] += res; s["opened"] += b.n; s["t"]["o"] += b.n; s["xp"] += 20 * b.n
            log(s, "Открыто контейнеров: %d" % b.n, -cost); ex = {"res": res, "cost": cost}
        elif a == "sell":
            g = c = 0
            for u in set(b.ids):
                k = next((j for j, x in enumerate(s["inv"]) if x["uid"] == u), None)
                if k is not None: g += rd(s["inv"].pop(k)["val"] * .9); c += 1
            if not c: err("Нечего продавать")
            s["bal"] += g; s["sold"] += c; s["t"]["s"] += c; s["xp"] += 5 * c
            log(s, "Продано предметов: %d" % c, g); ex = {"g": g}
        elif a == "buy":
            l = next((x for x in G["mk"] if x["id"] == b.id), None)
            if not l: err("Лот уже продан")
            if s["bal"] < l["p"]: err("Не хватает ₽")
            s["bal"] -= l["p"]; G["mk"].remove(l)
            s["inv"].append({"uid": rid(), "i": l["i"], "val": l["p"], "t": now()})
            s["bought"] += 1; s["t"]["b"] += 1; s["xp"] += 10; log(s, "Покупка: " + I[l["i"]][0], -l["p"])
        elif a == "daily":
            if s["daily"] == day(): err("Уже получено сегодня")
            s["daily"] = day(); s["bal"] += 10000; log(s, "Ежедневная награда", 10000)
        elif a == "claim":
            T = {"o": 3, "s": 1, "b": 1}; r = {"o": 5000, "s": 3000, "b": 3000}
            if b.k not in T or s["t"][b.k] < T[b.k] or s["t"]["c"].get(b.k): err("Задание не выполнено")
            s["t"]["c"][b.k] = 1; s["bal"] += r[b.k]; s["xp"] += 30; log(s, "Награда за задание", r[b.k])
        elif a == "auc":
            x = next((y for y in s["inv"] if y["uid"] == b.u), None); sp = rd(b.sp)
            if not x: err("Предмет недоступен")
            if sp < 100: err("Минимум 100 ₽")
            if b.d not in (5, 15, 60): err("Неверная длительность")
            s["inv"].remove(x); t = now()
            G["au"].append({"id": rid(), "i": x["i"], "uid": x["uid"], "val": x["val"], "own": uid, "start": sp, "cur": sp,
                            "lead": "", "bids": [], "end": t + b.d * 60000, "nb": t + int((4 + random.random() * 10) * 1e3),
                            "mx": rd(x["val"] * (.8 + random.random() * .6) / 10) * 10, "done": False})
        elif a == "bid":
            x = next((y for y in G["au"] if y["id"] == b.id), None)
            if not x or x["done"]: err("Торги завершены")
            if x["own"] == uid: err("Нельзя ставить на свой лот")
            amt = rd(b.amt); mb = min_bid(x)
            if amt < mb: err("Минимум %d ₽" % mb)
            need = amt - (x["cur"] if x["lead"] == uid else 0)
            if s["bal"] < need: err("Не хватает ₽")
            if x["lead"] and x["lead"] != uid and x["lead"] not in BN:
                def f(y, c=x["cur"]): y["bal"] += c; log(y, "Ставка перебита", c); note(y, "Вашу ставку перебили")
                edit(x["lead"], f)
            s["bal"] -= need; x["cur"] = amt; x["lead"] = uid; t = now()
            x["bids"].append({"w": uid, "p": amt, "t": t})
            if x["end"] - t < 2e4: x["end"] = t + 20000
            log(s, "Ставка: " + I[x["i"]][0], -need)
        elif a == "top":
            ex = {"top": [{"n": r[0] or "Игрок", "s": r[1], "me": r[2] == uid} for r in
                          db.execute("select name,score,id from p order by score desc limit 20")]}
        elif a == "reset":
            keep = {k: s[k] for k in ("free", "fd", "daily", "t", "refs")}
            s.clear(); s.update(fresh(), **keep)
        elif a != "state": err("Неизвестное действие")
        out = {**view(uid, s), **ex}
        pput(uid, s, info.get("name"))
        db.execute("replace into kv values('g',?)", (json.dumps(G),)); db.commit()
        return out


@app.get("/")
def index(): return FileResponse(os.path.join(DIR, "index.html"))


@app.get("/patch.js")
def patch(): return FileResponse(os.path.join(DIR, "patch.js"), media_type="application/javascript")
