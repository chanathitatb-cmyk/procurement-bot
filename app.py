import os, re
from datetime import datetime, date
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from apscheduler.schedulers.background import BackgroundScheduler
from sheets import add_task, get_tasks, set_status, delete_task
import pytz

app    = Flask(__name__)
TH_TZ  = pytz.timezone("Asia/Bangkok")
api    = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handle = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
MY_ID  = os.environ.get("LINE_USER_ID", "")

STATUS = {"1":"รอทำ", "2":"กำลังทำ", "3":"รอคนอื่น", "4":"เสร็จ"}
EMOJI  = {"รอทำ":"⏳", "กำลังทำ":"🔄", "รอคนอื่น":"🕐", "เสร็จ":"✅"}

# ── helpers ────────────────────────────────────────────────────

def fmt_task(t):
    e    = EMOJI.get(t["status"], "•")
    dead = ""
    if t.get("deadline"):
        try:
            d    = datetime.strptime(t["deadline"], "%Y-%m-%d").date()
            diff = (d - date.today()).days
            warn = " ⚠️" if 0 <= diff <= 2 else (" 🔴" if diff < 0 else "")
            dead = f"\n   📅 {t['deadline']}{warn}"
        except: pass
    who = f" (จาก {t['from_who']})" if t.get("from_who") else ""
    return f"{e} [{t['id']}] {t['name']}{who}{dead}"

def tasks_text(tasks, title):
    if not tasks: return f"{title}\n—— ไม่มีงาน ——"
    lines = [title]
    for t in tasks: lines.append(fmt_task(t))
    return "\n".join(lines)

# ── morning report ─────────────────────────────────────────────

def morning_report():
    all_tasks = get_tasks()
    pending   = [t for t in all_tasks if t["status"] != "เสร็จ"]
    today     = datetime.now(TH_TZ).strftime("%d/%m/%Y")

    if not pending:
        msg = f"🌅 {today}\n\nไม่มีงานค้าง 🎉\nหยุดพักได้บ้างนะ"
    else:
        overdue  = [t for t in pending if _is_overdue(t)]
        today_dl = [t for t in pending if _is_today(t)]
        rest     = [t for t in pending if not _is_overdue(t) and not _is_today(t)]

        lines = [f"🌅 สวัสดีตอนเช้า! {today}",
                 f"📋 เหลืองาน {len(pending)} รายการ", ""]

        if overdue:
            lines.append(f"🔴 เลยกำหนดแล้ว ({len(overdue)})")
            for t in overdue: lines.append(f"  {fmt_task(t)}")
            lines.append("")
        if today_dl:
            lines.append(f"⚠️ ครบกำหนดวันนี้ ({len(today_dl)})")
            for t in today_dl: lines.append(f"  {fmt_task(t)}")
            lines.append("")
        if rest:
            lines.append(f"📌 งานที่เหลือ ({len(rest)})")
            for t in rest: lines.append(f"  {fmt_task(t)}")
        msg = "\n".join(lines)

    if MY_ID: api.push_message(MY_ID, TextSendMessage(text=msg))

def _is_overdue(t):
    try: return datetime.strptime(t["deadline"], "%Y-%m-%d").date() < date.today()
    except: return False

def _is_today(t):
    try: return datetime.strptime(t["deadline"], "%Y-%m-%d").date() == date.today()
    except: return False

# ── LINE handler ───────────────────────────────────────────────

@app.route("/callback", methods=["POST"])
def callback():
    sig  = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try: handle.handle(body, sig)
    except InvalidSignatureError: abort(400)
    return "OK"

@handle.add(MessageEvent, message=TextMessage)
def on_message(event):
    text = event.message.text.strip()
    tl   = text.lower().replace(" ", "")
    reply = route(text, tl)
    api.reply_message(event.reply_token, TextSendMessage(text=reply))

def route(text, tl):
    # ── เพิ่มงาน ─────────────────────────────────────────
    # รูปแบบ: ชื่องาน | ใครให้มา | DD/MM หรือ DD/MM/YY
    if text.startswith("+ ") or text.startswith("เพิ่ม "):
        raw   = text.split(" ", 1)[1].strip()
        parts = [p.strip() for p in raw.split("|")]
        name     = parts[0]
        from_who = parts[1] if len(parts) > 1 else ""
        deadline = ""
        if len(parts) > 2:
            deadline = parse_date(parts[2])
        if not name:
            return '⚠️ ระบุชื่องานด้วย\nตย: + ทำรายงาน | หัวหน้า | 25/6'
        tid = add_task(name, from_who, deadline)
        dl_txt = f"\n📅 deadline: {deadline}" if deadline else ""
        who_txt = f"\n👤 จาก: {from_who}" if from_who else ""
        return f"✅ บันทึกงาน #{tid}\n📝 {name}{who_txt}{dl_txt}\nสถานะ: ⏳ รอทำ"

    # ── ดูงาน ─────────────────────────────────────────────
    elif tl in ["งาน", "ดูงาน", "list", "หน้าที่"]:
        all_tasks = get_tasks()
        pending   = [t for t in all_tasks if t["status"] != "เสร็จ"]
        if not pending:
            return "✅ ไม่มีงานค้างเลย เยี่ยม!"
        by = {"รอทำ":[], "กำลังทำ":[], "รอคนอื่น":[]}
        for t in pending: by[t["status"]].append(t)
        lines = [f"📋 งานค้าง {len(pending)} รายการ"]
        for status, icon in [("กำลังทำ","🔄"),("รอทำ","⏳"),("รอคนอื่น","🕐")]:
            if by[status]:
                lines.append(f"\n{icon} {status}")
                for t in by[status]: lines.append(f"  {fmt_task(t)}")
        lines.append('\n💡 พิมพ์ "เสร็จ [เลข]" เมื่อทำเสร็จ')
        return "\n".join(lines)

    # ── อัปเดตสถานะ shortcut ──────────────────────────────
    elif re.match(r"^(ทำ|เริ่ม) \d+$", text):
        return _set(int(text.split()[1]), "กำลังทำ")

    elif re.match(r"^รอ \d+$", text):
        return _set(int(text.split()[1]), "รอคนอื่น")

    elif re.match(r"^เสร็จ \d+$", text):
        return _set(int(text.split()[1]), "เสร็จ")

    elif re.match(r"^ยัง \d+$", text):
        return _set(int(text.split()[1]), "รอทำ")

    # ── ลบ ────────────────────────────────────────────────
    elif re.match(r"^ลบ \d+$", text):
        ok = delete_task(int(text.split()[1]))
        return f"🗑️ ลบงาน #{text.split()[1]} แล้ว" if ok else "⚠️ ไม่พบงานนั้น"

    # ── สรุป ──────────────────────────────────────────────
    elif tl in ["สรุป", "รีพอร์ต", "report"]:
        all_tasks = get_tasks()
        pending   = [t for t in all_tasks if t["status"] != "เสร็จ"]
        done      = [t for t in all_tasks if t["status"] == "เสร็จ"]
        overdue   = [t for t in pending if _is_overdue(t)]
        lines = [
            f"📊 สรุปงาน",
            f"⏳ รอทำ:      {sum(1 for t in pending if t['status']=='รอทำ')}",
            f"🔄 กำลังทำ:   {sum(1 for t in pending if t['status']=='กำลังทำ')}",
            f"🕐 รอคนอื่น:  {sum(1 for t in pending if t['status']=='รอคนอื่น')}",
            f"✅ เสร็จแล้ว: {len(done)}",
        ]
        if overdue: lines.append(f"🔴 เลยกำหนด:  {len(overdue)}")
        return "\n".join(lines)

    # ── ช่วย ──────────────────────────────────────────────
    elif tl in ["ช่วย", "help", "?"]:
        return """📖 วิธีใช้บอทบันทึกงาน

➕ เพิ่มงาน:
+ [ชื่องาน] | [จากใคร] | [วันส่ง]
ตย: + ทำรายงาน | หัวหน้า | 25/6

📋 ดูงาน:  งาน
📊 สรุป:   สรุป

🔄 อัปเดต:
ทำ [เลข]   → กำลังทำ
รอ [เลข]   → รอคนอื่น
เสร็จ [เลข] → เสร็จแล้ว
ยัง [เลข]  → กลับไปรอทำ
ลบ [เลข]   → ลบออก"""

    else:
        return 'ไม่เข้าใจครับ\nพิมพ์ "ช่วย" เพื่อดูวิธีใช้'

def _set(tid, status):
    ok = set_status(tid, status)
    return f"{EMOJI[status]} งาน #{tid} → {status}" if ok else f"⚠️ ไม่พบงาน #{tid}"

def parse_date(raw):
    """แปลง 25/6, 25/6/25, 25/06/2025 → YYYY-MM-DD"""
    raw = raw.strip()
    for fmt in ["%d/%m/%Y", "%d/%m/%y", "%d/%m"]:
        try:
            d = datetime.strptime(raw, fmt)
            if fmt == "%d/%m":
                d = d.replace(year=date.today().year)
                if d.date() < date.today(): d = d.replace(year=d.year + 1)
            return d.strftime("%Y-%m-%d")
        except: pass
    return ""

if __name__ == "__main__":
    sched = BackgroundScheduler(timezone=TH_TZ)
    sched.add_job(morning_report, "cron", hour=8, minute=0)
    sched.start()
    print("🤖 Task Bot พร้อมแล้ว")
    app.run(host="0.0.0.0", port=5000)
