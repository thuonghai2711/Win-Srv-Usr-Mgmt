# pip install flask waitress
# Web công khai (không login): bấm nút -> tạo 1 user tạm, tối đa 1 user cùng lúc, hết TTL tự logoff + xoá user + data.
# Biến môi trường: AGENT_TOKEN (bắt buộc), RDP_HOST, TTL_MIN (75), COOLDOWN_MIN (120, 0=tắt),
#                  ADMIN_PASS (đặt thì bật /admin, user "admin"), HOST, PORT, DB_PATH
import os, sys, time, math, html, string, sqlite3, secrets
from contextlib import contextmanager
from flask import Flask, request, jsonify, Response, redirect

app = Flask(__name__)
DB = os.environ.get("DB_PATH", "panel.db")
AGENT_TOKEN = os.environ.get("AGENT_TOKEN", "")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
RDP_HOST = os.environ.get("RDP_HOST", "")
TTL = float(os.environ.get("TTL_MIN", 75)) * 60
COOLDOWN = float(os.environ.get("COOLDOWN_MIN", 120)) * 60
AGENT_ONLINE = 30          # giây: agent poll gần nhất trong khoảng này thì coi là online
BUSY = ("pending", "creating", "active", "expiring", "deleting")   # trạng thái đang chiếm "slot"

@contextmanager
def conn():
    c = sqlite3.connect(DB, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    try: yield c
    finally: c.close()

with conn() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS sessions(id INTEGER PRIMARY KEY, username TEXT, password TEXT, status TEXT,
        ip TEXT, cookie TEXT, created REAL, started REAL, expires REAL, sent REAL, retry_at REAL, result TEXT);
    CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
    """)

def client_ip():
    xf = request.headers.get("X-Forwarded-For", "")
    return xf.split(",")[0].strip() if xf and request.remote_addr in ("127.0.0.1", "::1") else request.remote_addr

def current(c):
    return c.execute("SELECT * FROM sessions WHERE status IN (%s) ORDER BY id DESC LIMIT 1"
                     % ",".join("'%s'" % s for s in BUSY)).fetchone()

def agent_seen(c):
    r = c.execute("SELECT v FROM kv WHERE k='agent_seen'").fetchone()
    return float(r["v"]) if r else 0.0

def maintenance(c, now):
    c.execute("UPDATE sessions SET status='failed', result='Agent khong phan hoi', password='' "
              "WHERE status='pending' AND created<?", (now - 90,))
    c.execute("UPDATE sessions SET status='expiring', result='create timeout' WHERE status='creating' AND sent<?", (now - 120,))
    c.execute("UPDATE sessions SET status='expiring' WHERE status='active' AND expires<=?", (now,))
    c.execute("UPDATE sessions SET status='expiring' WHERE status='deleting' AND sent<?", (now - 120,))

def cooldown_wait(c, ip, now):
    if COOLDOWN <= 0: return 0
    r = c.execute("SELECT created FROM sessions WHERE ip=? AND status!='failed' ORDER BY id DESC LIMIT 1", (ip,)).fetchone()
    return max(0, COOLDOWN - (now - r["created"])) if r else 0

def state_for(c, cookie, ip):
    now = time.time(); maintenance(c, now)
    cur = current(c)
    st = {"agent_online": now - agent_seen(c) < AGENT_ONLINE, "ttl_min": TTL / 60, "busy": bool(cur),
          "mine": False, "status": None, "remaining": None, "rdp_host": RDP_HOST, "wait": 0}
    if cur:
        st["status"] = cur["status"]
        if cur["expires"]: st["remaining"] = max(0, int(cur["expires"] - now))
        if cookie and cur["cookie"] == cookie:
            st["mine"] = True
            if cur["status"] == "active":
                st["username"], st["password"] = cur["username"], cur["password"]
    else:
        if cookie:
            last = c.execute("SELECT status,result FROM sessions WHERE cookie=? ORDER BY id DESC LIMIT 1", (cookie,)).fetchone()
            if last and last["status"] == "done": st["ended"] = True
            if last and last["status"] == "failed": st["error"] = "Tạo tài khoản thất bại: %s" % (last["result"] or "")
        st["wait"] = int(cooldown_wait(c, ip, now))
    return st

def gen_user():
    return "u" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))

def gen_password():
    a = string.ascii_letters + string.digits
    while True:
        p = "".join(secrets.choice(a) for _ in range(14))
        if any(x.islower() for x in p) and any(x.isupper() for x in p) and any(x.isdigit() for x in p):
            return p

PAGE = """<!doctype html><html lang=vi><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Tài khoản dùng thử</title>
<style>
body{font:16px system-ui,sans-serif;max-width:520px;margin:40px auto;padding:0 16px;color:#222}
.card{border:1px solid #ddd;border-radius:12px;padding:20px}
button{font:inherit;padding:10px 18px;border:0;border-radius:8px;background:#2563eb;color:#fff;cursor:pointer}
button:disabled{background:#999}
code{background:#f3f4f6;padding:2px 6px;border-radius:4px;user-select:all}
.err{color:#b91c1c}.muted{color:#666}
</style>
<h2>Tài khoản dùng thử (__TTL__ phút)</h2>
<div class=card id=box>Đang tải…</div>
<script>
let st=null,t0=0;
const $=s=>document.getElementById(s);
const fmt=s=>{s=Math.max(0,Math.floor(s));return Math.floor(s/60)+":"+String(s%60).padStart(2,"0")};
const esc=x=>String(x).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function render(){
  if(!st)return;
  const left=st.remaining!=null?st.remaining-(Date.now()-t0)/1000:null;
  let h="";
  if(st.error)h+=`<p class=err>${esc(st.error)}</p>`;
  if(st.busy&&st.mine&&st.status=="active"){
    h+=`<p>Tài khoản của bạn đã sẵn sàng. Kết nối Remote Desktop (RDP):</p>
    <p>Máy chủ: <code>${esc(st.rdp_host||location.hostname)}</code><br>User: <code>${esc(st.username)}</code><br>Password: <code>${esc(st.password)}</code></p>
    <p>Còn lại: <b>${fmt(left)}</b>. Hết giờ hệ thống tự đăng xuất và xoá tài khoản cùng toàn bộ dữ liệu, hãy sao lưu trước.</p>`;
  }else if(st.busy&&st.mine){h+="<p>Đang xử lý…</p>";}
  else if(st.busy){h+=`<p>Đang có người sử dụng${left!=null?`, còn khoảng ${Math.ceil(left/60)} phút`:""}. Vui lòng quay lại sau.</p>`;}
  else{
    if(st.ended)h+="<p>Phiên trước của bạn đã kết thúc, tài khoản và dữ liệu đã bị xoá.</p>";
    if(!st.agent_online)h+="<p class=muted>Máy chủ chưa sẵn sàng, thử lại sau.</p>";
    else if(st.wait>0)h+=`<p class=muted>Bạn vừa dùng gần đây, thử lại sau ${Math.ceil(st.wait/60)} phút.</p>`;
    else h+="<button id=go onclick=start()>Tạo tài khoản</button>";
  }
  $("box").innerHTML=h;
}
async function load(){const r=await fetch("/api/state");st=await r.json();t0=Date.now();render()}
async function start(){$("go").disabled=true;const r=await fetch("/api/start",{method:"POST",headers:{"X-Requested-With":"fetch"}});st=await r.json();t0=Date.now();render()}
load();setInterval(load,4000);setInterval(render,1000);
</script></html>"""

@app.get("/")
def index():
    return Response(PAGE.replace("__TTL__", "%g" % (TTL / 60)), mimetype="text/html")

@app.get("/api/state")
def api_state():
    with conn() as c:
        return jsonify(state_for(c, request.cookies.get("sid"), client_ip()))

@app.post("/api/start")
def api_start():
    if request.headers.get("X-Requested-With") != "fetch":
        return jsonify(error="bad request"), 400
    ip = client_ip(); cookie = request.cookies.get("sid") or secrets.token_urlsafe(16)
    now = time.time(); err = None
    with conn() as c:
        c.execute("BEGIN IMMEDIATE")          # khoá ghi: đảm bảo tối đa 1 session cùng lúc
        try:
            maintenance(c, now)
            if current(c): err = "Đang có người sử dụng, vui lòng quay lại sau."
            elif now - agent_seen(c) >= AGENT_ONLINE: err = "Máy chủ chưa sẵn sàng, thử lại sau."
            elif (w := cooldown_wait(c, ip, now)) > 0: err = "Bạn vừa dùng gần đây, thử lại sau %d phút." % math.ceil(w / 60)
            else:
                c.execute("INSERT INTO sessions(username,password,status,ip,cookie,created) VALUES(?,?,?,?,?,?)",
                          (gen_user(), gen_password(), "pending", ip, cookie, now))
        finally:
            c.execute("COMMIT")
        st = state_for(c, cookie, ip)
    if err: st["error"] = err
    resp = jsonify(st)
    if err: resp.status_code = 409
    resp.set_cookie("sid", cookie, max_age=7 * 86400, httponly=True, samesite="Lax",
                    secure=request.headers.get("X-Forwarded-Proto") == "https")
    return resp

# ---- API cho agent (agent chủ động gọi ra) ----
def agent_ok():
    t = request.headers.get("X-Token", "")
    return bool(AGENT_TOKEN) and secrets.compare_digest(t.encode(), AGENT_TOKEN.encode())

@app.get("/api/jobs")
def api_jobs():
    if not agent_ok(): return jsonify(error="bad token"), 401
    now = time.time(); jobs = []
    with conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES('agent_seen',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (str(now),))
        maintenance(c, now)
        s = current(c)
        if s and s["status"] == "pending":
            jobs.append({"id": s["id"], "action": "create", "username": s["username"],
                         "password": s["password"], "ttl_min": TTL / 60})
            c.execute("UPDATE sessions SET status='creating', sent=? WHERE id=?", (now, s["id"]))
        elif s and s["status"] == "expiring" and (s["retry_at"] or 0) <= now:
            jobs.append({"id": s["id"], "action": "delete", "username": s["username"]})
            c.execute("UPDATE sessions SET status='deleting', sent=? WHERE id=?", (now, s["id"]))
    return jsonify(jobs)

@app.post("/api/result")
def api_result():
    if not agent_ok(): return jsonify(error="bad token"), 401
    d = request.json; now = time.time(); msg = str(d.get("msg", ""))[:300]
    with conn() as c:
        if d["action"] == "create":
            if d["ok"]:
                c.execute("UPDATE sessions SET status='active', started=?, expires=?, result=? WHERE id=? AND status='creating'",
                          (now, now + TTL, msg, d["id"]))
            else:
                c.execute("UPDATE sessions SET status='failed', result=?, password='' WHERE id=?", (msg, d["id"]))
        elif d["action"] == "delete":
            if d["ok"]:
                c.execute("UPDATE sessions SET status='done', result=?, password='' WHERE id=?", (msg, d["id"]))
            else:   # xoá lỗi -> giữ slot, thử lại sau 60s
                c.execute("UPDATE sessions SET status='expiring', result=?, retry_at=? WHERE id=?", (msg, now + 60, d["id"]))
    return jsonify(ok=True)

# ---- /admin (chỉ bật khi đặt ADMIN_PASS) ----
def admin_denied():
    if not ADMIN_PASS: return Response("Not found", 404)
    a = request.authorization
    if not a or not (secrets.compare_digest(a.username.encode(), b"admin") and
                     secrets.compare_digest((a.password or "").encode(), ADMIN_PASS.encode())):
        return Response("Auth", 401, {"WWW-Authenticate": 'Basic realm="admin"'})

@app.get("/admin")
def admin():
    if (r := admin_denied()): return r
    with conn() as c:
        rows = c.execute("SELECT id,username,status,ip,created,expires,result FROM sessions ORDER BY id DESC LIMIT 30").fetchall()
    t = lambda v: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v)) if v else ""
    body = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % html.escape(str(x)) for x in
                   (r["id"], r["username"], r["status"], r["ip"], t(r["created"]), t(r["expires"]), r["result"] or ""))
                   for r in rows)
    return Response("<meta charset=utf-8><body style='font:14px sans-serif'><h2>Sessions</h2>"
                    "<form method=post action=/admin/end><button>Kết thúc phiên hiện tại ngay</button></form>"
                    "<table border=1 cellpadding=4><tr><th>#</th><th>User</th><th>Status</th><th>IP</th><th>Tạo</th>"
                    "<th>Hết hạn</th><th>Result</th></tr>" + body + "</table>", mimetype="text/html")

@app.post("/admin/end")
def admin_end():
    if (r := admin_denied()): return r
    with conn() as c:
        c.execute("UPDATE sessions SET status='expiring', retry_at=NULL WHERE status='active'")
    return redirect("/admin")

if __name__ == "__main__":
    if not AGENT_TOKEN:
        sys.exit("Thieu AGENT_TOKEN (vd: AGENT_TOKEN=$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))') )")
    from waitress import serve
    serve(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8080)), threads=4)
