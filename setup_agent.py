# Chạy trên Windows Server (cmd Admin), agent.py cùng thư mục:
#   python setup_agent.py https://panel.2z2.top <TOKEN>
# Lưu ý: dùng Python cài "for all users" (vd C:\Program Files\Python312) để tài khoản SYSTEM chạy được.
import sys, os, shutil, subprocess, tempfile
from xml.sax.saxutils import escape

url, token = sys.argv[1], sys.argv[2]
d = r"C:\winuser-agent"
os.makedirs(d, exist_ok=True)
shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.py"), d)
subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests", "pywin32"])
if "\\users\\" in sys.executable.lower():
    print("CANH BAO: Python nam trong thu muc user, SYSTEM co the khong chay duoc. Hay cai Python for all users.")

# Task XML: chạy SYSTEM lúc boot, ẩn, KHÔNG giới hạn thời gian (mặc định schtasks kill sau 72h), tự restart khi crash
xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="A"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Hidden>true</Hidden><Enabled>true</Enabled>
  </Settings>
  <Actions Context="A"><Exec>
    <Command>{escape(sys.executable)}</Command>
    <Arguments>{escape('"%s\\agent.py" %s %s' % (d, url, token))}</Arguments>
    <WorkingDirectory>{escape(d)}</WorkingDirectory>
  </Exec></Actions>
</Task>"""
p = os.path.join(tempfile.gettempdir(), "winuser-agent-task.xml")
open(p, "w", encoding="utf-16").write(xml)
subprocess.check_call(["schtasks", "/Create", "/TN", "WinUserAgent", "/XML", p, "/F"])
os.remove(p)   # file XML chứa token, xoá đi
subprocess.check_call(["schtasks", "/Run", "/TN", "WinUserAgent"])
print("Xong: WinUserAgent chay an bang SYSTEM, tu khoi dong cung Windows, tu restart khi loi.")
