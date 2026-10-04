# Win User Panel (bản công khai, 1 user / 75 phút)

Web **công khai, không cần đăng nhập**: khách bấm "Tạo tài khoản" để nhận 1 user Windows tạm (không phải admin) qua RDP.
Tối đa **1 user cùng lúc**. Sau **75 phút** hệ thống tự **logoff, xoá user và toàn bộ dữ liệu** (profile).
Toàn bộ viết bằng Python.

```
 Khách ──HTTPS──> Web (server.py, VPS) <──poll mỗi 5s (outbound HTTPS)── Agent (agent.py, Windows Server)
```
Agent chủ động gọi ra web nên Windows không cần mở thêm port cho web (khách chỉ cần vào được cổng RDP 3389).

## Các file

| File | Chạy ở đâu | Việc |
|---|---|---|
| `server.py` | VPS | Web công khai + API cho agent (Flask + waitress, SQLite) |
| `setup_server.py` | VPS Linux (root) | Cài một lệnh: venv, systemd, HTTPS qua Caddy, sinh token agent |
| `agent.py` | Windows Server | Tạo/xoá user bằng `pywin32` (không dùng PowerShell) |
| `setup_agent.py` | Windows Server (Admin) | Cài agent thành scheduled task chạy ẩn bằng SYSTEM |

## Cài đặt

### 1. Web (VPS Ubuntu/Debian)
DNS A record của domain trỏ về VPS, mở port 80/443.
```bash
sudo python3 setup_server.py panel.example.com --rdp rdp.example.com
```
Tuỳ chọn: `--ttl 75` (phút/phiên), `--cooldown 120` (phút chờ giữa 2 lần tạo của cùng 1 IP, 0 = tắt),
`--admin-pass XXX` (bật trang `/admin`, user `admin`), `--rdp` (host/IP RDP hiển thị cho khách).

Script in ra **Token agent** và sẵn lệnh cài agent. Chạy lại script thì token được giữ nguyên.

Test local: `pip install flask waitress` rồi
`AGENT_TOKEN=abc TTL_MIN=75 python server.py` (mở http://localhost:8080).

### 2. Agent (Windows Server, cmd Admin)
Cần Python 3 cài **for all users** (vd `C:\Program Files\Python312`) để SYSTEM chạy được.
```
python setup_agent.py https://panel.example.com <TOKEN>
```

## Cách hoạt động

1. Khách mở web, bấm **Tạo tài khoản**. Server sinh username ngẫu nhiên (`u` + 6 ký tự) và password 14 ký tự.
2. Agent nhận job, tạo user (nhóm *Remote Desktop Users*, không admin). Trang hiện host, user, password và đồng hồ đếm ngược. Thông tin chỉ hiện cho trình duyệt của người tạo (cookie).
3. Người khác vào web khi đang có phiên sẽ thấy "Đang có người sử dụng, còn khoảng X phút".
4. Hết giờ: logoff session RDP, xoá user, xoá profile (`C:\Users\<user>` + registry hive). Xoá lỗi thì thử lại mỗi 60 giây và slot vẫn bị giữ cho tới khi xoá được.
5. Agent offline thì web từ chối tạo mới ("Máy chủ chưa sẵn sàng").

## Lớp bảo vệ

- 1 user cùng lúc (khoá ghi SQLite), cooldown theo IP (mặc định 120 phút).
- Không bao giờ thêm user vào Administrators. Agent chỉ xoá user do panel tạo (comment `webpanel`), từ chối admin/Administrator/Guest.
- Agent có **failsafe cục bộ** (`state.json`): tự xoá user khi quá hạn + 2 phút, kể cả khi server web chết.
- Password phiên bị xoá khỏi DB khi phiên kết thúc. API của agent bảo vệ bằng token.
- `/admin` chỉ bật khi đặt `--admin-pass`. Có nút "Kết thúc phiên hiện tại ngay".

## Rủi ro cần biết (web công khai)

Bất kỳ ai cũng lấy được một tài khoản RDP trên máy này. User thường vẫn chạy được chương trình, dùng GPU/CPU (ví dụ đào coin), truy cập mạng ra ngoài và thử khai thác lỗ hổng leo thang quyền. Khuyến nghị:
- Dùng một máy/VM **riêng**, không chứa dữ liệu nhạy cảm, không join domain, không có khoá/credential của hệ thống khác.
- Firewall chặn truy cập từ VM này vào mạng nội bộ; cân nhắc giới hạn đường ra.
- Giữ cooldown theo IP; cân nhắc thêm captcha (Cloudflare Turnstile) trước nút tạo.
- Cập nhật Windows thường xuyên, đặt giới hạn tài nguyên/quota cho nhóm user tạm.

## Quản lý

Windows (agent):
```
schtasks /Query /TN WinUserAgent /V /FO LIST
schtasks /End /TN WinUserAgent
schtasks /Run /TN WinUserAgent
schtasks /Delete /TN WinUserAgent /F
```
VPS (web): `systemctl status panel`, `journalctl -u panel -f`, `systemctl restart panel`. Dữ liệu ở `/opt/panel/panel.db`.
Đổi TTL/cooldown: sửa `Environment=` trong `/etc/systemd/system/panel.service`, rồi `systemctl daemon-reload && systemctl restart panel`.

## Lưu ý
- Agent chưa được test trên Windows thật: hãy thử với phiên ngắn (`--ttl 2`), RDP vào, chờ hết giờ và kiểm tra `C:\Users\<user>` đã biến mất.
- Dữ liệu ngoài profile (vd `D:\data\<user>`) không bị xoá. Cần thì thêm vào hàm `delete()` trong `agent.py`.
- Chế độ này dùng 1 agent duy nhất (token đặt qua biến môi trường).
