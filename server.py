# pip install flask waitress
# Chạy: ADMIN_USER=admin ADMIN_PASS=matkhau python server.py   (đặt sau reverse proxy HTTPS: Caddy/nginx)
import os, sqlite3, secrets, time
from flask import Flask, request, jsonify, Response, render_template_string, redirect

app = Flask(__name__)
DB = "panel.db"
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "changeme")

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

with db() as c:
    c.executescript("""
    CREATE TABLE IF NOT EXISTS agents(id INTEGER PRIMARY KEY, name TEXT UNIQUE, token TEXT, last_seen REAL);
    CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, agent_id INTEGER, action TEXT, username TEXT,
        password TEXT, status TEXT DEFAULT 'pending', result TEXT, created REAL);
    """)
    # migration cho DB cũ
    for col in ("hours REAL DEFAULT 0", "expires REAL", "handled INTEGER DEFAULT 0"):
        try: c.execute("ALTER TABLE jobs ADD COLUMN " + col)
        except sqlite3.OperationalError: pass

def need_admin():
    a = request.authorization
    if not a or not (secrets.compare_digest(a.username, ADMIN_USER) and secrets.compare_digest(a.password, ADMIN_PASS)):
        return Response("Auth", 401, {"WWW-Authenticate": 'Basic realm="panel"'})

def agent_from_token():
    t = request.headers.get("X-Token", "")
    with db() as c:
        return c.execute("SELECT * FROM agents WHERE token=?", (t,)).fetchone()

PAGE = """
<!doctype html><meta charset=utf-8><title>Win User Panel</title>
<style>body{font:14px sans-serif;max-width:1000px;margin:20px auto}td,th{border:1px solid #ccc;padding:4px 8px}input,select{padding:4px}</style>
<h2>Agents</h2>
<table><tr><th>Name</th><th>Status</th><th>Token</th></tr>
{% for a in agents %}<tr><td>{{a.name}}</td><td>{{ 'online' if now-(a.last_seen or 0)<20 else 'offline' }}</td><td><code>{{a.token}}</code></td></tr>{% endfor %}</table>
<form method=post action=/agents><input name=name placeholder="tên agent/server"><button>Thêm agent</button></form>
<h2>Tạo / Xoá user</h2>
<form method=post action=/jobs>
<select name=agent_id>{% for a in agents %}<option value={{a.id}}>{{a.name}}</option>{% endfor %}</select>
<input name=username placeholder=username required pattern="[A-Za-z0-9_.\\-]{3,20}">
<input name=password placeholder="password (khi tạo)" type=password>
<input name=hours type=number step=0.5 min=0 placeholder="tự xoá sau N giờ (0=không)" style="width:210px">
<button name=action value=create>Tạo</button><button name=action value=delete>Xoá</button></form>
<h2>Jobs</h2>
<table><tr><th>#</th><th>Action</th><th>User</th><th>Status</th><th>Tự xoá lúc</th><th>Result</th></tr>
{% for j in jobs %}<tr><td>{{j.id}}</td><td>{{j.action}}</td><td>{{j.username}}</td><td>{{j.status}}</td>
<td>{{ j.expires | ts }}</td><td>{{j.result}}</td></tr>{% endfor %}</table>
"""

@app.template_filter("ts")
def ts(v):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(v)) if v else ""

@app.get("/")
def index():
    if (r := need_admin()): return r
    with db() as c:
        return render_template_string(PAGE, agents=c.execute("SELECT * FROM agents").fetchall(),
            jobs=c.execute("SELECT * FROM jobs ORDER BY id DESC LIMIT 50").fetchall(), now=time.time())

@app.post("/agents")
def add_agent():
    if (r := need_admin()): return r
    with db() as c:
        c.execute("INSERT INTO agents(name,token) VALUES(?,?)", (request.form["name"], secrets.token_urlsafe(32)))
    return redirect("/")

@app.post("/jobs")
def add_job():
    if (r := need_admin()): return r
    f = request.form
    with db() as c:
        c.execute("INSERT INTO jobs(agent_id,action,username,password,created,hours) VALUES(?,?,?,?,?,?)",
                  (f["agent_id"], f["action"], f["username"], f.get("password", ""), time.time(),
                   float(f.get("hours") or 0)))
    return redirect("/")

# ---- API cho agent (agent chủ động gọi ra, không cần mở port inbound trên Windows) ----
@app.get("/api/jobs")
def api_jobs():
    a = agent_from_token()
    if not a: return jsonify(error="bad token"), 401
    now = time.time()
    with db() as c:
        c.execute("UPDATE agents SET last_seen=? WHERE id=?", (now, a["id"]))
        # user hết hạn -> tự sinh job delete (agent offline thì chạy khi online lại)
        for e in c.execute("SELECT * FROM jobs WHERE agent_id=? AND action='create' AND status='done' "
                           "AND handled=0 AND expires IS NOT NULL AND expires<?", (a["id"], now)).fetchall():
            c.execute("INSERT INTO jobs(agent_id,action,username,created) VALUES(?,?,?,?)",
                      (a["id"], "delete", e["username"], now))
            c.execute("UPDATE jobs SET handled=1 WHERE id=?", (e["id"],))
        rows = c.execute("SELECT id,action,username,password FROM jobs WHERE agent_id=? AND status='pending'",
                         (a["id"],)).fetchall()
        for r in rows: c.execute("UPDATE jobs SET status='running' WHERE id=?", (r["id"],))
    return jsonify([dict(r) for r in rows])

@app.post("/api/result")
def api_result():
    a = agent_from_token()
    if not a: return jsonify(error="bad token"), 401
    d = request.json
    now = time.time()
    with db() as c:
        c.execute("UPDATE jobs SET status=?, result=?, password='' WHERE id=? AND agent_id=?",
                  ("done" if d["ok"] else "failed", d["msg"][:500], d["id"], a["id"]))
        j = c.execute("SELECT action,username,hours FROM jobs WHERE id=?", (d["id"],)).fetchone()
        if d["ok"] and j:
            if j["action"] == "create" and (j["hours"] or 0) > 0:
                c.execute("UPDATE jobs SET expires=? WHERE id=?", (now + j["hours"] * 3600, d["id"]))
            elif j["action"] == "delete":  # đã xoá (tay hoặc tự động) -> huỷ lịch auto-delete
                c.execute("UPDATE jobs SET handled=1 WHERE agent_id=? AND username=? AND action='create'",
                          (a["id"], j["username"]))
    return jsonify(ok=True)

if __name__ == "__main__":
    from waitress import serve   # pip install waitress (thuần Python, chạy được cả Windows/Linux)
    serve(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8080)), threads=4)
