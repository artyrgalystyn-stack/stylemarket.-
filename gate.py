import os, time
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from server import auth, DIR
from main import app, tg

CHANNEL = os.getenv("CHANNEL", "").strip().lstrip("@")  # username публичного канала без @
_ok = {}  # uid -> до какого времени подписка считается подтверждённой


def subscribed(uid):
    if not CHANNEL or uid == "local": return True
    t = time.time()
    if _ok.get(uid, 0) > t: return True
    r = tg("getChatMember", chat_id="@" + CHANNEL, user_id=int(uid))
    if not r or not r.get("ok"): return True  # сбой Telegram или бот не админ канала: не блокируем, смотрите логи
    res = r["result"]
    ok = res["status"] in ("creator", "administrator", "member") or (res["status"] == "restricted" and res.get("is_member"))
    if ok: _ok[uid] = t + 120
    return ok


@app.middleware("http")
async def sub_gate(request, call_next):
    if CHANNEL and request.method == "POST" and request.url.path == "/api/act":
        try: uid, _ = auth(request.headers.get("x-init", ""))
        except Exception: uid = None
        if uid and not await run_in_threadpool(subscribed, uid):
            return JSONResponse({"detail": "sub", "ch": CHANNEL}, status_code=403)
    return await call_next(request)


GATE_JS = r"""
(()=>{const f=window.fetch;let g=null;
window.fetch=async(...a)=>{const r=await f(...a);
 if(String(a[0]).includes("/api/act")){
  if(r.status==403){const j=await r.clone().json().catch(()=>({}));
   if(j.detail=="sub"&&!g){g=document.createElement("div");
    g.style.cssText="position:fixed;inset:0;z-index:99999;background:#0b0b0f;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:24px;text-align:center;font:16px system-ui";
    g.innerHTML='<div style="font-size:48px">📢</div><div style="font-size:20px;font-weight:700">Подпишитесь на канал</div><div style="opacity:.7">Чтобы играть, подпишитесь на наш канал, затем нажмите «Я подписался».</div><a href="https://t.me/'+j.ch+'" target="_blank" style="background:#2ed573;color:#000;padding:14px 28px;border-radius:12px;font-weight:700;text-decoration:none">Подписаться</a><button id="gk" style="background:#222;color:#fff;border:0;padding:14px 28px;border-radius:12px;font-size:16px">Я подписался</button>';
    document.body.appendChild(g);g.querySelector("#gk").onclick=()=>location.reload()}}
  else if(r.ok&&g){g.remove();g=null}}
 return r}})();
"""

# заменяем отдачу patch.js: оригинальный файл + экран подписки
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/patch.js"]


@app.get("/patch.js")
def patch_js():
    with open(os.path.join(DIR, "patch.js"), encoding="utf-8") as fh:
        return Response(fh.read() + GATE_JS, media_type="application/javascript")
