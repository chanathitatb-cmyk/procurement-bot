import os
import re
from datetime import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from apscheduler.schedulers.background import BackgroundScheduler
from sheets import (
    add_task, get_all_tasks, update_status, get_task_by_id,
    get_pending_tasks, get_monthly_summary
)
import pytz

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "YOUR_TOKEN")
LINE_CHANNEL_SECRET       = os.environ.get("LINE_CHANNEL_SECRET", "YOUR_SECRET")
MY_USER_ID                = os.environ.get("LINE_USER_ID", "")   # ไว้ส่ง morning report

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler      = WebhookHandler(LINE_CHANNEL_SECRET)
TH_TZ        = pytz.timezone("Asia/Bangkok")

STATUSES = {
    "สืบราคา":      "สืบราคา",
    "รอผอ":         "รอ ผอ. เซ็น",
    "รอmd":         "รอ MD เซ็น",
    "draftใหม่":    "ต้องการ Draft ใหม่",
    "supplier":     "อยู่ที่ Supplier",
    "ผลิต":         "กำลังผลิต",
    "เสร็จ":        "เสร็จสิ้น",
    "draft":        "จัดทำ Draft",
    "ส่งdraft":     "ส่ง Draft แล้ว",
}

STATUS_EMOJI = {
    "สืบราคา":           "🔍",
    "รอ ผอ. เซ็น":       "✍️",
    "รอ MD เซ็น":        "📋",
    "ต้องการ Draft ใหม่": "🔄",
    "อยู่ที่ Supplier":  "🏭",
    "กำลังผลิต":         "⚙️",
    "เสร็จสิ้น":         "✅",
    "จัดทำ Draft":       "📝",
    "ส่ง Draft แล้ว":    "📤",
}

HELP_TEXT = """🤖 บอทติดตามงานจัดซื้อ

➕ เพิ่มงานใหม่:
  เพิ่ม [ชื่องาน] | [ได้จากใคร] | [มูลค่า]
  ตย: เพิ่ม ซื้อโต๊ะ 10 ตัว | ฝ่ายบุคคล | 50000

📋 ดูรายการ:  งาน
📊 รีพอร์ต:   รีพอร์ต

🔄 อัปเดตสถานะ:
  สถานะ [เลข] [สถานะ]
  ตย: สถานะ 3 รอผอ

สถานะที่ใช้ได้:
  draft / ส่งdraft / สืบราคา / รอผอ
  รอmd / draftใหม่ / supplier / ผลิต / เสร็จ

💰 เพิ่มมูลค่าทีหลัง:
  มูลค่า [เลข] [จำนวน]
  ตย: มูลค่า 3 75000

🗑️ ลบ: ลบ [เลข]"""


def format_task_line(t):
    emoji = STATUS_EMOJI.get(t.get("status", ""), "📌")
    budget = f"  💰 {int(float(t['budget'])):,} บ." if t.get("budget") else ""
    return (
        f"{t['id']}. {emoji} {t['name']}\n"
        f"   จาก: {t.get('from_who','—')}  |  รับ: {t.get('date','—')}\n"
        f"   สถานะ: {t.get('status','—')}{budget}"
    )


def morning_report():
    pending = get_pending_tasks()
    now_str = datetime.now(TH_TZ).strftime("%d/%m/%Y")
    if not pending:
        msg = f"🌅 {now_str}\n✅ ไม่มีงานค้างอยู่ เยี่ยมมาก!"
    else:
        lines = [f"🌅 รีพอร์ตงานประจำวัน {now_str}", "─" * 28]
        by_status = {}
        for t in pending:
            s = t.get("status", "อื่นๆ")
            by_status.setdefault(s, []).append(t)
        for status, tasks in by_status.items():
            emoji = STATUS_EMOJI.get(status, "📌")
            lines.append(f"\n{emoji} {status} ({len(tasks)} งาน)")
            for t in tasks:
                budget = f" | {int(float(t['budget'])):,} บ." if t.get("budget") else ""
                lines.append(f"  • [{t['id']}] {t['name']}{budget}")
        lines.append(f"\n📊 รวม {len(pending)} งานที่ยังไม่เสร็จ")
        msg = "\n".join(lines)
    if MY_USER_ID:
        line_bot_api.push_message(MY_USER_ID, TextSendMessage(text=msg))


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    tl   = text.lower().replace(" ", "")

    # ── เพิ่มงาน ──────────────────────────────────────────────────
    if text.startswith("เพิ่ม "):
        parts = text[6:].split("|")
        name     = parts[0].strip()
        from_who = parts[1].strip() if len(parts) > 1 else ""
        budget   = parts[2].strip() if len(parts) > 2 else ""
        if not name:
            reply = "⚠️ ระบุชื่องานด้วยครับ\nตย: เพิ่ม ซื้อโต๊ะ | ฝ่ายบุคคล | 50000"
        else:
            row_id = add_task(name, from_who, budget)
            budget_txt = f"\n💰 มูลค่า: {int(float(budget)):,} บ." if budget else ""
            reply = (
                f"✅ เพิ่มงาน #{row_id} แล้ว\n"
                f"📋 {name}\n"
                f"👤 จาก: {from_who or '—'}{budget_txt}\n"
                f"สถานะ: จัดทำ Draft"
            )

    # ── ดูรายการ ──────────────────────────────────────────────────
    elif tl in ["งาน", "รายการ", "list"]:
        tasks = get_all_tasks()
        if not tasks:
            reply = "📭 ยังไม่มีงานในระบบ"
        else:
            pending = [t for t in tasks if t.get("status") != "เสร็จสิ้น"]
            done    = [t for t in tasks if t.get("status") == "เสร็จสิ้น"]
            lines   = [f"📋 งานทั้งหมด ({len(tasks)} งาน)", "─" * 28]
            if pending:
                lines.append(f"\n🔄 ยังดำเนินการ ({len(pending)} งาน)")
                for t in pending:
                    lines.append(format_task_line(t))
            if done:
                lines.append(f"\n✅ เสร็จแล้ว ({len(done)} งาน)")
                for t in done:
                    lines.append(format_task_line(t))
            reply = "\n".join(lines)

    # ── อัปเดตสถานะ ────────────────────────────────────────────────
    elif text.lower().startswith("สถานะ "):
        parts = text[6:].strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            reply = "⚠️ รูปแบบ: สถานะ [เลข] [สถานะ]\nตย: สถานะ 3 รอผอ"
        else:
            task_id    = int(parts[0])
            status_key = parts[1].strip().lower().replace(" ", "")
            new_status = STATUSES.get(status_key)
            if not new_status:
                opts = "  " + "\n  ".join(STATUSES.keys())
                reply = f"⚠️ ไม่รู้จักสถานะ '{parts[1]}'\nใช้: \n{opts}"
            else:
                ok = update_status(task_id, new_status)
                if ok:
                    emoji = STATUS_EMOJI.get(new_status, "📌")
                    reply = f"{emoji} งาน #{task_id} → {new_status}"
                else:
                    reply = f"⚠️ ไม่พบงาน #{task_id}"

    # ── อัปเดตมูลค่า ────────────────────────────────────────────────
    elif text.lower().startswith("มูลค่า "):
        parts = text[7:].strip().split(None, 1)
        if len(parts) < 2 or not parts[0].isdigit():
            reply = "⚠️ รูปแบบ: มูลค่า [เลข] [จำนวน]\nตย: มูลค่า 3 75000"
        else:
            task_id = int(parts[0])
            budget  = parts[1].strip().replace(",", "")
            ok = update_status(task_id, budget_only=float(budget))
            reply = f"💰 อัปเดตมูลค่างาน #{task_id} → {int(float(budget)):,} บ." if ok else f"⚠️ ไม่พบงาน #{task_id}"

    # ── ลบงาน ─────────────────────────────────────────────────────
    elif re.match(r"^ลบ \d+$", text):
        task_id = int(text.split()[1])
        ok = update_status(task_id, delete=True)
        reply = f"🗑️ ลบงาน #{task_id} แล้ว" if ok else f"⚠️ ไม่พบงาน #{task_id}"

    # ── รีพอร์ต ────────────────────────────────────────────────────
    elif tl in ["รีพอร์ต", "report", "สรุป"]:
        summary = get_monthly_summary()
        now_str = datetime.now(TH_TZ).strftime("%B %Y")
        lines = [f"📊 สรุปงานเดือน {now_str}", "─" * 28]
        lines.append(f"📁 งานทั้งหมด:    {summary['total']} งาน")
        lines.append(f"✅ เสร็จสิ้น:      {summary['done']} งาน")
        lines.append(f"🔄 กำลังดำเนินการ: {summary['pending']} งาน")
        if summary.get("total_budget"):
            lines.append(f"💰 มูลค่ารวม:     {int(summary['total_budget']):,} บ.")
        if summary.get("by_status"):
            lines.append("\nแยกตามสถานะ:")
            for s, count in summary["by_status"].items():
                e = STATUS_EMOJI.get(s, "📌")
                lines.append(f"  {e} {s}: {count} งาน")
        reply = "\n".join(lines)

    # ── ช่วยเหลือ ─────────────────────────────────────────────────
    elif tl in ["ช่วย", "help", "?"]:
        reply = HELP_TEXT

    else:
        reply = 'ไม่เข้าใจคำสั่ง 🤔\nพิมพ์ "ช่วย" เพื่อดูคำสั่งทั้งหมด'

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))


if __name__ == "__main__":
    scheduler = BackgroundScheduler(timezone=TH_TZ)
    scheduler.add_job(morning_report, "cron", hour=8, minute=0)
    scheduler.start()
    print("🤖 Procurement Bot เริ่มทำงาน...")
    app.run(host="0.0.0.0", port=5000, debug=False)
