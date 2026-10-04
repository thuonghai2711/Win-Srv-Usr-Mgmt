# Chạy trên VPS Ubuntu/Debian (root), server.py cùng thư mục:
#   sudo python3 setup_server.py panel.example.com --rdp rdp.example.com [--ttl 75] [--cooldown 120] [--admin-pass XXX]
# Cần: DNS A record của domain trỏ về VPS, mở port 80/443 (Caddy tự cấp HTTPS).
import argparse, os, re, shutil, secrets, subprocess

ap = argparse.ArgumentParser()
ap.add_argument("domain")
ap.add_argument("--rdp", default="", help="host/IP RDP hiển thị cho người dùng (mặc định: tên miền của web)")
ap.add_argument("--ttl", default="75", help="số phút mỗi phiên")
ap.add_argument("--cooldown", default="120", help="phút chờ giữa 2 lần tạo của cùng 1 IP (0 = tắt)")
ap.add_argument("--admin-pass", default="", help="đặt thì bật trang /admin (user: admin)")
a = ap.parse_args()
sh = lambda *x: subprocess.check_call(x)
UNIT = "/etc/systemd/system/panel.service"

token = None
if os.path.exists(UNIT):   # chạy lại script thì giữ nguyên token cũ
    m = re.search(r'AGENT_TOKEN=([^"\n]+)', open(UNIT).read())
    token = m.group(1) if m else None
token = token or secrets.token_urlsafe(32)

sh("apt-get", "update", "-y")
sh("apt-get", "install", "-y", "python3-venv", "caddy")
os.makedirs("/opt/panel", exist_ok=True)
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"), "/opt/panel/")
sh("python3", "-m", "venv", "/opt/panel/venv")
sh("/opt/panel/venv/bin/pip", "install", "-q", "flask", "waitress")

env = {"AGENT_TOKEN": token, "RDP_HOST": a.rdp, "TTL_MIN": a.ttl, "COOLDOWN_MIN": a.cooldown, "HOST": "127.0.0.1"}
if a.admin_pass: env["ADMIN_PASS"] = a.admin_pass
open(UNIT, "w").write("[Unit]\nDescription=Win User Panel\nAfter=network.target\n[Service]\nWorkingDirectory=/opt/panel\n"
    + "".join('Environment="%s=%s"\n' % kv for kv in env.items())
    + "ExecStart=/opt/panel/venv/bin/python server.py\nRestart=always\n[Install]\nWantedBy=multi-user.target\n")
open("/etc/caddy/Caddyfile", "w").write(f"{a.domain} {{ reverse_proxy 127.0.0.1:8080 }}\n")
sh("systemctl", "daemon-reload"); sh("systemctl", "enable", "--now", "panel")
sh("systemctl", "restart", "panel"); sh("systemctl", "restart", "caddy")
print(f"\nWeb:    https://{a.domain}" + (f"\nAdmin:  https://{a.domain}/admin (user admin)" if a.admin_pass else ""))
print(f"Token agent: {token}")
print(f"Cai agent tren Windows:  python setup_agent.py https://{a.domain} {token}")
