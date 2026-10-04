# Chạy trên VPS Ubuntu/Debian (root), server.py cùng thư mục:
#   sudo python3 setup_server.py panel.2z2.top 'MatKhauAdmin'
# Cần: DNS A record của domain trỏ về VPS, mở port 80/443 (Caddy tự cấp HTTPS).
import sys, os, shutil, secrets, subprocess

domain = sys.argv[1]
pw = sys.argv[2] if len(sys.argv) > 2 else secrets.token_urlsafe(14)
sh = lambda *a: subprocess.check_call(a)

sh("apt-get", "update", "-y")
sh("apt-get", "install", "-y", "python3-venv", "caddy")
os.makedirs("/opt/panel", exist_ok=True)
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py"), "/opt/panel/")
sh("python3", "-m", "venv", "/opt/panel/venv")
sh("/opt/panel/venv/bin/pip", "install", "-q", "flask", "waitress")

open("/etc/systemd/system/panel.service", "w").write(f"""[Unit]
Description=Win User Panel
After=network.target
[Service]
WorkingDirectory=/opt/panel
Environment=ADMIN_USER=admin
Environment=ADMIN_PASS={pw}
Environment=HOST=127.0.0.1
ExecStart=/opt/panel/venv/bin/python server.py
Restart=always
[Install]
WantedBy=multi-user.target
""")
open("/etc/caddy/Caddyfile", "w").write(f"{domain} {{ reverse_proxy 127.0.0.1:8080 }}\n")
sh("systemctl", "daemon-reload")
sh("systemctl", "enable", "--now", "panel")
sh("systemctl", "restart", "caddy")
print(f"\nWeb:  https://{domain}\nUser: admin\nPass: {pw}")
