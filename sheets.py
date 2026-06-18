import os, json
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
import pytz

SCOPES   = ["https://www.googleapis.com/auth/spreadsheets"]
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
CREDS    = os.environ.get("GOOGLE_CREDS_JSON", "credentials.json")
TH_TZ    = pytz.timezone("Asia/Bangkok")

# คอลัมน์: ID | ชื่องาน | จากใคร | Deadline | สถานะ | วันที่บันทึก
HEADERS  = ["ID", "ชื่องาน", "จากใคร", "Deadline", "สถานะ", "วันที่บันทึก"]

_ws = None

def _sheet():
    global _ws
    if _ws: return _ws
    if isinstance(CREDS, str) and CREDS.endswith(".json"):
        creds = Credentials.from_service_account_file(CREDS, scopes=SCOPES)
    else:
        creds = Credentials.from_service_account_info(json.loads(CREDS), scopes=SCOPES)
    gc  = gspread.authorize(creds)
    wb  = gc.open_by_key(SHEET_ID)
    try:
        _ws = wb.worksheet("Tasks")
    except:
        _ws = wb.add_worksheet("Tasks", rows=500, cols=8)
        _ws.append_row(HEADERS)
        _ws.format("A1:F1", {
            "backgroundColor": {"red":0.2,"green":0.4,"blue":0.8},
            "textFormat": {"foregroundColor":{"red":1,"green":1,"blue":1},"bold":True}
        })
        _ws.freeze(rows=1)
    return _ws

def _rows():
    ws = _sheet()
    return ws.get_all_records()

def _next_id():
    ids = [r["ID"] for r in _rows() if str(r["ID"]).isdigit()]
    return max((int(i) for i in ids), default=0) + 1

def add_task(name, from_who="", deadline=""):
    ws  = _sheet()
    tid = _next_id()
    now = datetime.now(TH_TZ).strftime("%Y-%m-%d %H:%M")
    ws.append_row([tid, name, from_who, deadline, "รอทำ", now])
    # สีแถวตามสถานะ
    row_num = len(_rows()) + 1
    ws.format(f"A{row_num}:F{row_num}", {"backgroundColor": STATUS_COLOR["รอทำ"]})
    return tid

def get_tasks():
    result = []
    for i, r in enumerate(_rows(), start=2):
        if not r.get("ชื่องาน"): continue
        result.append({
            "row":      i,
            "id":       r["ID"],
            "name":     r["ชื่องาน"],
            "from_who": r.get("จากใคร",""),
            "deadline": r.get("Deadline",""),
            "status":   r.get("สถานะ","รอทำ"),
        })
    return result

def set_status(task_id, new_status):
    ws   = _sheet()
    rows = get_tasks()
    t    = next((r for r in rows if str(r["id"]) == str(task_id)), None)
    if not t: return False
    ws.update_cell(t["row"], 5, new_status)
    ws.format(f"A{t['row']}:F{t['row']}", {"backgroundColor": STATUS_COLOR[new_status]})
    return True

def delete_task(task_id):
    ws   = _sheet()
    rows = get_tasks()
    t    = next((r for r in rows if str(r["id"]) == str(task_id)), None)
    if not t: return False
    ws.delete_rows(t["row"])
    return True

STATUS_COLOR = {
    "รอทำ":      {"red":0.95, "green":0.95, "blue":1.0},   # ฟ้าอ่อน
    "กำลังทำ":  {"red":1.0,  "green":0.95, "blue":0.8},    # เหลืองอ่อน
    "รอคนอื่น": {"red":1.0,  "green":0.88, "blue":0.7},    # ส้มอ่อน
    "เสร็จ":    {"red":0.85, "green":0.95, "blue":0.85},   # เขียวอ่อน
}
