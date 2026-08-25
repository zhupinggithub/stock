from __future__ import annotations
import argparse
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];RUNTIME=ROOT/".runtime";PID_FILE=RUNTIME/"web.pid"

def alive(pid:int)->bool:
    if os.name=="nt":
        import ctypes
        handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,pid)
        if not handle:return False
        ctypes.windll.kernel32.CloseHandle(handle);return True
    try: os.kill(pid,0);return True
    except OSError:return False

def start()->int:
    RUNTIME.mkdir(exist_ok=True)
    if PID_FILE.exists():
        try: pid=int(PID_FILE.read_text().strip())
        except ValueError: pid=0
        if pid and alive(pid): print(f"Web service is already running. PID={pid} URL=http://127.0.0.1:6688");return 0
        PID_FILE.unlink(missing_ok=True)
    out=(RUNTIME/"web.out.log").open("ab");err=(RUNTIME/"web.error.log").open("ab")
    kwargs={"cwd":ROOT,"stdout":out,"stderr":err,"stdin":subprocess.DEVNULL,"close_fds":True}
    if os.name=="nt": kwargs["creationflags"]=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
    else: kwargs["start_new_session"]=True
    port=os.getenv("STOCK_APP_PORT","6688")
    process=subprocess.Popen([sys.executable,"-m","uvicorn","backend.app.main:app","--host",os.getenv("STOCK_APP_HOST","127.0.0.1"),"--port",port],**kwargs)
    PID_FILE.write_text(str(process.pid),encoding="ascii")
    for _ in range(60):
        if process.poll() is not None: PID_FILE.unlink(missing_ok=True);print("Web service failed to start; see .runtime/web.error.log",file=sys.stderr);return 1
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health",timeout=.5).close()
            print(f"Web service started. PID={process.pid} URL=http://127.0.0.1:{port}");return 0
        except Exception: time.sleep(.5)
    print(f"Web process started but health check timed out. PID={process.pid}",file=sys.stderr);return 1

def stop()->int:
    if not PID_FILE.exists(): print("Web service is not running or PID file is missing.");return 0
    try: pid=int(PID_FILE.read_text().strip())
    except ValueError: PID_FILE.unlink(missing_ok=True);print("Invalid PID file removed.");return 0
    if alive(pid):
        if os.name=="nt":
            import ctypes
            handle=ctypes.windll.kernel32.OpenProcess(0x0001|0x00100000,False,pid)
            if handle:
                ctypes.windll.kernel32.TerminateProcess(handle,0)
                ctypes.windll.kernel32.WaitForSingleObject(handle,5000)
                ctypes.windll.kernel32.CloseHandle(handle)
        else:
            try: os.killpg(pid,signal.SIGTERM)
            except ProcessLookupError: pass
        for _ in range(20):
            if not alive(pid): break
            time.sleep(.25)
        print(f"Web service stopped. PID={pid}")
    else: print(f"Recorded process is no longer running. PID={pid}")
    PID_FILE.unlink(missing_ok=True);return 0

def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("action",choices=("start","stop","status"));args=parser.parse_args()
    if args.action=="start":return start()
    if args.action=="stop":return stop()
    if PID_FILE.exists() and alive(int(PID_FILE.read_text().strip())):print(f"running PID={PID_FILE.read_text().strip()}");return 0
    print("stopped");return 1
if __name__=="__main__":raise SystemExit(main())
