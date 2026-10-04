# Win User Panel

Web quản lý tạo/xoá user **không phải admin** trên Windows Server. Toàn bộ viết bằng Python.

```
 Trình duyệt ──HTTPS──> Web (server.py, VPS)  <──poll mỗi 5s (outbound HTTPS)── Agent (agent.py, Windows Server)
```

Agent chủ động gọi ra web nên **Windows không cần mở port inbound**.

## Các file

| File | Chạy ở đâu | Việc |
|---|---|---|
| `server.py` | VPS | Web quản lý (Flask + waitress, SQLite `panel.db`) |
| `setup_server.py` | VPS Linux (root) | Cài một lệnh: venv, systemd service, HTTPS qua Caddy |
| `agent.py` | Windows Server | Tạo/xoá user bằng `pywin32` |
| `setup_agent.py` | Windows Server (Admin) | Cài agent thành scheduled task chạy ẩn bằng SYSTEM |

## Cài đặt

### 1. Web (VPS Ubuntu/Debian)
Yêu cầu: DNS A record của domain trỏ về VPS, mở port 80/443.
```bash
sudo python3 setup_server.py panel.example.com 'MatKhauAdmin'
```
Script in ra URL, user (`admin`) và mật khẩu. Bỏ trống mật khẩu thì tự sinh ngẫu nhiên.

Test nhanh trên máy local:
```bash
pip install flask waitress
ADMIN_USER=admin ADMIN_PASS=matkhau python server.py   # http://localhost:8080
```
Biến môi trường: `ADMIN_USER`, `ADMIN_PASS`, `HOST` (mặc định 0.0.0.0), `PORT` (mặc định 8080).

### 2. Lấy token
Vào web, mục **Agents**, nhập tên server rồi bấm **Thêm agent**. Copy token.

### 3. Agent (Windows Server, cmd Admin)
Yêu cầu: Python 3 cài **for all users** (vd `C:\Program Files\Python312`) để tài khoản SYSTEM chạy được.
```
python setup_agent.py https://panel.example.com <TOKEN>
```
Cột Agents trên web hiện `online` là xong.

## Sử dụng

Form **Tạo / Xoá user**: chọn agent, nhập username, password (>= 8 ký tự, khi tạo) và số giờ tự xoá (0 = không tự xoá).

- **Tạo**: user vào nhóm *Remote Desktop Users*, password không hết hạn, user không tự đổi được password.
- **Xoá**: logoff mọi session RDP, xoá user, xoá profile (`C:\Users\<user>` + registry hive).
- **Tự xoá sau N giờ**: hết hạn thì server tự sinh job xoá. Agent offline lúc hết hạn thì xoá khi online lại. Xoá tay trước hạn sẽ huỷ lịch tự xoá.

Username hợp lệ: `A-Z a-z 0-9 _ . -`, dài 3-20 ký tự.

## Bảo mật

- Không bao giờ thêm user vào Administrators.
- Chỉ xoá được user do panel tạo (đánh dấu comment `webpanel`). Từ chối xoá user admin, `Administrator`, `Guest`, `DefaultAccount`, `WDAGUtilityAccount`.
- Mỗi agent một token riêng. Web dùng HTTP Basic Auth, bắt buộc đi qua HTTPS.
- Password lưu trong DB chỉ tới khi agent xử lý xong, sau đó bị xoá.
- Nên giới hạn IP truy cập trang admin (firewall hoặc Cloudflare Access) và dùng mật khẩu admin mạnh.
- Token nằm trong lệnh của scheduled task, chỉ Administrator đọc được.

## Quản lý agent trên Windows
```
schtasks /Query /TN WinUserAgent /V /FO LIST   :: xem trạng thái
schtasks /End /TN WinUserAgent                 :: dừng
schtasks /Run /TN WinUserAgent                 :: chạy lại
schtasks /Delete /TN WinUserAgent /F           :: gỡ
```
Task chạy ẩn bằng SYSTEM lúc boot, không giới hạn thời gian, tự restart sau 1 phút khi crash.

## Quản lý web trên VPS
```bash
systemctl status panel      # trạng thái
journalctl -u panel -f      # log
systemctl restart panel     # restart
```
Dữ liệu ở `/opt/panel/panel.db`.

## Lưu ý

- Phần agent chưa được test trên Windows thật. Hãy thử với user test: tạo, RDP vào, đặt hạn ngắn (vd 0.05 giờ) và kiểm tra `C:\Users\<user>` có bị xoá sạch.
- Thư mục dữ liệu ngoài profile (vd `D:\data\<user>`) không bị xoá. Cần thì thêm vào hàm `delete()` trong `agent.py`.
- SQLite chỉ phù hợp quy mô nhỏ, `server.py` chạy một process nhiều thread là đủ.
