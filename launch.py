import os
from fastapi.responses import Response
from server import DIR
from gate import app, GATE_JS


def read(name):
    p = os.path.join(DIR, name)
    if not os.path.exists(p): return ""
    with open(p, encoding="utf-8") as fh: return fh.read()


# patch.js отдаётся вместе с экраном подписки (GATE_JS) и оформлением (ui.js)
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/patch.js"]


@app.get("/patch.js")
def patch_js():
    return Response(read("patch.js") + GATE_JS + "\n" + read("ui.js"), media_type="application/javascript")
