# Agent thuần Python cho Windows Server (không gọi PowerShell).
# Cài:  python setup_agent.py https://panel.2z2.top <TOKEN>
# Chạy tay:  python agent.py https://panel.2z2.top <TOKEN>   (cần quyền Administrator/SYSTEM)
import sys, os, re, time, shutil, winreg, requests
import pywintypes, win32net, win32netcon, win32security, win32profile, win32ts

URL, TOKEN = sys.argv[1].rstrip("/"), sys.argv[2]
H = {"X-Token": TOKEN}
USER_RE = re.compile(r"^[A-Za-z0-9_.-]{3,20}$")
RESERVED = {"administrator", "guest", "defaultaccount", "wdagutilityaccount"}
MARK = "webpanel"            # chỉ xoá user do panel tạo (comment = webpanel)
SID_ADMINS, SID_RDP = "S-1-5-32-544", "S-1-5-32-555"   # dùng SID nên không phụ thuộc ngôn ngữ Windows

def group_name(sid_str):
    return win32security.LookupAccountSid(None, win32security.ConvertStringSidToSid(sid_str))[0]

def get_user(u):
    try:
        return win32net.NetUserGetInfo(None, u, 1)
    except pywintypes.error as e:
        if e.winerror == 2221:   # NERR_UserNotFound
            return None
        raise

def create(u, pw):
    if not pw or len(pw) < 8:
        return False, "password >= 8 ky tu"
    if get_user(u):
        return False, "user da ton tai"
    win32net.NetUserAdd(None, 1, {
        "name": u, "password": pw, "priv": win32netcon.USER_PRIV_USER,
        "home_dir": None, "comment": MARK, "script_path": None,
        "flags": win32netcon.UF_SCRIPT | win32netcon.UF_DONT_EXPIRE_PASSWD | win32netcon.UF_PASSWD_CANT_CHANGE,
    })
    # chỉ vào Remote Desktop Users, KHÔNG thêm Administrators
    win32net.NetLocalGroupAddMembers(None, group_name(SID_RDP), 3, [{"domainandname": u}])
    return True, "created " + u

def is_admin(u):
    members, _, _ = win32net.NetLocalGroupGetMembers(None, group_name(SID_ADMINS), 1)
    return any(m["name"].lower().endswith("\\" + u.lower()) for m in members)

def logoff_sessions(u):
    for s in win32ts.WTSEnumerateSessions(None):
        sid = s["SessionId"]
        try:
            if win32ts.WTSQuerySessionInformation(None, sid, win32ts.WTSUserName).lower() == u.lower():
                win32ts.WTSLogoffSession(None, sid, True)
        except pywintypes.error:
            pass

def profile_path(sid_str):
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\ProfileList\\" + sid_str) as k:
            return winreg.QueryValueEx(k, "ProfileImagePath")[0]
    except OSError:
        return None

def delete(u):
    info = get_user(u)
    if not info:
        return False, "user khong ton tai"
    if info["comment"] != MARK:
        return False, "khong phai user do panel tao"
    if is_admin(u):
        return False, "user la admin"
    sid = win32security.LookupAccountName(None, u)[0]
    sid_str = win32security.ConvertSidToStringSid(sid)
    path = profile_path(sid_str)
    logoff_sessions(u)           # 1) đá session RDP
    time.sleep(3)
    win32net.NetUserDel(None, u)  # 2) xoá user
    try:
        win32profile.DeleteProfile(sid_str)   # 3) xoá profile + registry hive
    except pywintypes.error:
        pass
    if path and os.path.isdir(path):          # 4) dọn nốt thư mục nếu còn sót
        shutil.rmtree(path, ignore_errors=True)
    return True, "deleted %s (+profile)" % u

def run(j):
    u = j["username"]
    if not USER_RE.match(u) or u.lower() in RESERVED:
        return False, "username khong hop le"
    try:
        if j["action"] == "create":
            return create(u, j["password"])
        if j["action"] == "delete":
            return delete(u)
        return False, "action la"
    except Exception as e:
        return False, "loi: %s" % e

while True:
    try:
        for j in requests.get(URL + "/api/jobs", headers=H, timeout=15).json():
            ok, msg = run(j)
            requests.post(URL + "/api/result", headers=H, json={"id": j["id"], "ok": ok, "msg": msg}, timeout=15)
    except Exception as e:
        print("err:", e)
    time.sleep(5)
