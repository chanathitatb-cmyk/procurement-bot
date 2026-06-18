"""
Google Sheets layer  —  ใช้ gspread + service account
Sheet structure:
  Sheet1 "Tasks"    → ข้อมูลงาน
  Sheet2 "Dashboard" → สูตร / กราฟ (สร้างอัตโนมัติ)
"""

import os
import json
from datetime import datetime
from typing import Optional
import gspread
from google.oauth2.service_account import Credentials
import pytz

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
SHEET_ID  = os.environ.get("GOOGLE_SHEET_ID", "YOUR_SHEET_ID")
CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON", "credentials.json")
TH_TZ      = pytz.timezone("Asia/Bangkok")

HEADERS = [
    "ID", "ชื่องาน", "ได้จากใคร", "วันที่รับ",
    "มูลค่า (บ.)", "สถานะ", "วันที่อัปเดต", "หมายเหตุ"
]
TASK_SHEET  = "Tasks"
DASH_SHEET  = "Dashboard"

_gc     = None
_sheet  = None


def _get_sheet():
    global _gc, _sheet
    if _sheet:
        return _sheet
    if isinstance(CREDS_JSON, str) and CREDS_JSON.endswith(".json"):
        creds = Credentials.from_service_account_file(CREDS_JSON, scopes=SCOPES)
    else:
        info  = json.loads(CREDS_JSON)
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    _gc    = gspread.authorize(creds)
    wb     = _gc.open_by_key(SHEET_ID)
    try:
        _sheet = wb.worksheet(TASK_SHEET)
    except gspread.WorksheetNotFound:
        _sheet = wb.add_worksheet(TASK_SHEET, rows=1000, cols=10)
        _sheet.append_row(HEADERS)
        _format_header(_sheet)
        _ensure_dashboard(wb)
    return _sheet


def _format_header(ws):
    """ทำให้ header row ดูโดดเด่น"""
    try:
        ws.format("A1:H1", {
            "backgroundColor": {"red": 0.18, "green": 0.34, "blue": 0.62},
            "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                           "bold": True, "fontSize": 11},
            "horizontalAlignment": "CENTER"
        })
        ws.freeze(rows=1)
    except Exception:
        pass


def _ensure_dashboard(wb):
    """สร้าง Dashboard sheet พร้อมสูตรอัตโนมัติ"""
    try:
        dash = wb.worksheet(DASH_SHEET)
    except gspread.WorksheetNotFound:
        dash = wb.add_worksheet(DASH_SHEET, rows=50, cols=10)

    dash.clear()
    now_month = datetime.now(TH_TZ).strftime("%Y-%m")

    rows = [
        ["📊 PROCUREMENT DASHBOARD", "", "", ""],
        ["", "", "", ""],
        ["สรุปงานทั้งหมด", "", "สรุปเดือนนี้", ""],
        ["งานทั้งหมด",    "=COUNTA(Tasks!A:A)-1",  "เดือน", f'=TEXT(TODAY(),"MMMM YYYY")'],
        ["เสร็จสิ้น",     '=COUNTIF(Tasks!F:F,"เสร็จสิ้น")', "งานเดือนนี้",
         f'=COUNTIFS(Tasks!D:D,">="&DATE(YEAR(TODAY()),MONTH(TODAY()),1),Tasks!D:D,"<="&EOMONTH(TODAY(),0))'],
        ["ยังดำเนินการ",  '=COUNTA(Tasks!A:A)-1-COUNTIF(Tasks!F:F,"เสร็จสิ้น")', "เสร็จเดือนนี้",
         f'=COUNTIFS(Tasks!F:F,"เสร็จสิ้น",Tasks!G:G,">="&DATE(YEAR(TODAY()),MONTH(TODAY()),1))'],
        ["มูลค่ารวม (บ.)", "=SUM(Tasks!E:E)", "มูลค่าเดือนนี้",
         f'=SUMIFS(Tasks!E:E,Tasks!D:D,">="&DATE(YEAR(TODAY()),MONTH(TODAY()),1))'],
        ["", "", "", ""],
        ["แยกตามสถานะ", "จำนวน", "", ""],
        ["จัดทำ Draft",        '=COUNTIF(Tasks!F:F,"จัดทำ Draft")',         "", ""],
        ["ส่ง Draft แล้ว",    '=COUNTIF(Tasks!F:F,"ส่ง Draft แล้ว")',      "", ""],
        ["สืบราคา",            '=COUNTIF(Tasks!F:F,"สืบราคา")',             "", ""],
        ["รอ ผอ. เซ็น",       '=COUNTIF(Tasks!F:F,"รอ ผอ. เซ็น")',        "", ""],
        ["รอ MD เซ็น",        '=COUNTIF(Tasks!F:F,"รอ MD เซ็น")',         "", ""],
        ["ต้องการ Draft ใหม่", '=COUNTIF(Tasks!F:F,"ต้องการ Draft ใหม่")', "", ""],
        ["อยู่ที่ Supplier",  '=COUNTIF(Tasks!F:F,"อยู่ที่ Supplier")',   "", ""],
        ["กำลังผลิต",          '=COUNTIF(Tasks!F:F,"กำลังผลิต")',           "", ""],
        ["เสร็จสิ้น",          '=COUNTIF(Tasks!F:F,"เสร็จสิ้น")',           "", ""],
    ]
    dash.update("A1", rows)

    dash.format("A1:D1", {
        "backgroundColor": {"red": 0.11, "green": 0.21, "blue": 0.4},
        "textFormat": {"foregroundColor": {"red": 1, "green": 1, "blue": 1},
                       "bold": True, "fontSize": 14},
        "horizontalAlignment": "CENTER"
    })
    dash.merge_cells("A1:D1")

    dash.format("A3:D3", {
        "backgroundColor": {"red": 0.85, "green": 0.89, "blue": 0.95},
        "textFormat": {"bold": True, "fontSize": 11},
        "horizontalAlignment": "CENTER"
    })
    dash.format("A9:B9", {
        "backgroundColor": {"red": 0.85, "green": 0.89, "blue": 0.95},
        "textFormat": {"bold": True},
    })

    colors = [
        {"red": 0.94, "green": 0.97, "blue": 1.0},
        {"red": 1.0,  "green": 1.0,  "blue": 1.0},
    ]
    for i, row_num in enumerate(range(4, 8)):
        dash.format(f"A{row_num}:D{row_num}", {
            "backgroundColor": colors[i % 2]
        })
    for i, row_num in enumerate(range(10, 19)):
        dash.format(f"A{row_num}:B{row_num}", {
            "backgroundColor": colors[i % 2]
        })

    dash.set_column_width(1, 200)
    dash.set_column_width(2, 140)
    dash.set_column_width(3, 160)
    dash.set_column_width(4, 140)


def _next_id(ws) -> int:
    ids = ws.col_values(1)[1:]
    nums = [int(x) for x in ids if x.isdigit()]
    return max(nums, default=0) + 1


def _all_rows(ws) -> list[dict]:
    records = ws.get_all_records()
    result  = []
    for i, r in enumerate(records, start=2):
        result.append({
            "row":       i,
            "id":        r.get("ID", ""),
            "name":      r.get("ชื่องาน", ""),
            "from_who":  r.get("ได้จากใคร", ""),
            "date":      r.get("วันที่รับ", ""),
            "budget":    r.get("มูลค่า (บ.)", ""),
            "status":    r.get("สถานะ", ""),
            "updated":   r.get("วันที่อัปเดต", ""),
            "note":      r.get("หมายเหตุ", ""),
        })
    return result


def add_task(name: str, from_who: str = "", budget: str = "") -> int:
    ws     = _get_sheet()
    new_id = _next_id(ws)
    now    = datetime.now(TH_TZ).strftime("%Y-%m-%d")
    row    = [new_id, name, from_who, now, budget or "", "จัดทำ Draft", now, ""]
    ws.append_row(row, value_input_option="USER_ENTERED")
    _color_status_row(ws, ws.row_count, "จัดทำ Draft")
    return new_id


def get_all_tasks() -> list[dict]:
    return _all_rows(_get_sheet())


def get_task_by_id(task_id: int) -> Optional[dict]:
    rows = _all_rows(_get_sheet())
    for r in rows:
        if str(r["id"]) == str(task_id):
            return r
    return None


def update_status(task_id: int, new_status: str = None,
                  budget_only: float = None, delete: bool = False) -> bool:
    ws   = _get_sheet()
    rows = _all_rows(ws)
    target = next((r for r in rows if str(r["id"]) == str(task_id)), None)
    if not target:
        return False
    row_num = target["row"]
    now     = datetime.now(TH_TZ).strftime("%Y-%m-%d")

    if delete:
        ws.delete_rows(row_num)
        return True
    if budget_only is not None:
        ws.update_cell(row_num, 5, budget_only)
        ws.update_cell(row_num, 7, now)
        return True
    if new_status:
        ws.update_cell(row_num, 6, new_status)
        ws.update_cell(row_num, 7, now)
        _color_status_row(ws, row_num, new_status)
        return True
    return False


STATUS_COLORS = {
    "จัดทำ Draft":          {"red": 0.85, "green": 0.91, "blue": 1.0},
    "ส่ง Draft แล้ว":      {"red": 0.78, "green": 0.85, "blue": 0.98},
    "สืบราคา":              {"red": 1.0,  "green": 0.95, "blue": 0.8},
    "รอ ผอ. เซ็น":         {"red": 1.0,  "green": 0.88, "blue": 0.7},
    "รอ MD เซ็น":          {"red": 1.0,  "green": 0.82, "blue": 0.6},
    "ต้องการ Draft ใหม่":  {"red": 1.0,  "green": 0.75, "blue": 0.75},
    "อยู่ที่ Supplier":    {"red": 0.84, "green": 0.95, "blue": 0.84},
    "กำลังผลิต":            {"red": 0.76, "green": 0.93, "blue": 0.78},
    "เสร็จสิ้น":            {"red": 0.73, "green": 0.92, "blue": 0.73},
}


def _color_status_row(ws, row_num: int, status: str):
    color = STATUS_COLORS.get(status, {"red": 1, "green": 1, "blue": 1})
    try:
        ws.format(f"A{row_num}:H{row_num}", {"backgroundColor": color})
    except Exception:
        pass


def get_pending_tasks() -> list[dict]:
    return [t for t in get_all_tasks() if t.get("status") != "เสร็จสิ้น"]


def get_monthly_summary() -> dict:
    tasks = get_all_tasks()
    now   = datetime.now(TH_TZ)
    month_tasks = [
        t for t in tasks
        if t.get("date", "").startswith(now.strftime("%Y-%m"))
    ]
    done    = [t for t in tasks if t.get("status") == "เสร็จสิ้น"]
    pending = [t for t in tasks if t.get("status") != "เสร็จสิ้น"]
    total_budget = sum(float(t["budget"]) for t in tasks if t.get("budget"))

    by_status = {}
    for t in tasks:
        s = t.get("status", "")
        if s:
            by_status[s] = by_status.get(s, 0) + 1

    return {
        "total":        len(tasks),
        "done":         len(done),
        "pending":      len(pending),
        "month_total":  len(month_tasks),
        "total_budget": total_budget,
        "by_status":    by_status,
    }
