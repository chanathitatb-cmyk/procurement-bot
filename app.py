import os, json
from datetime import datetime, date
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from apscheduler.schedulers.background import BackgroundScheduler
import anthropic
from sheets import get_tasks, add_task, set_status, delete_task
import pytz

app    = Flask(__name__)
TH_TZ  = pytz.timezone("Asia/Bangkok")
line   = LineBotApi(os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
handle = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
MY_ID  = os.environ.get("LINE_USER_ID", "")
ai     = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

# เก็บ conversation history ต่อ user (in-memory, สั้นๆ)
_history = {}

# ── System prompt ──────────────────────────────────────────────

def build_system(tasks):
    today    = datetime.now(TH_TZ).strftime("%d/%m/%Y")
    pending  = [t for t in tasks if t["status"] != "เสร็จ"]
    done_cnt = sum(1 for t in tasks if t["status"] == "เสร็จ")

    tasks_json = json.dumps(pending, ensure_ascii=False, indent=2)

    return f"""คุณคือผู้ช่วยบันทึกงานส่วนตัวใน LINE วันนี้คือ {today}

งานที่มีอยู่ตอนนี้ ({len(pending)} งานค้าง, เสร็จแล้ว {done_cnt} งาน):
{tasks_json}

สถานะที่มี: รอทำ / กำลังทำ / รอคนอื่น / เสร็จ

ความสามารถของคุณ:
1. บันทึกงานใหม่เมื่อผู้ใช้บอกว่าได้รับงาน
2. อัปเดตสถานะงานเมื่อมีความคืบหน้า
3. แนะนำว่าควรทำอะไรก่อน (ดู deadline และความสำคัญ)
4. วิเคราะห์ workload และแจ้งเตือนถ้างานเยอะหรือใกล้ deadline
5. ลบงานที่ไม่ต้องการ
6. ตอบคำถามทั่วไปเกี่ยวกับงาน

กฎสำคัญ:
- ตอบสั้น กระชับ ภาษาไทยเป็นกันเอง
- ถ้าผู้ใช้บอกงานใหม่แบบไม่ครบ ให้ถามกลับเฉพาะที่จำเป็น (deadline สำคัญที่สุด)
- ถ้าจะทำ action (เพิ่ม/แก้/ลบ) ให้บอก action ที่จะทำในรูปแบบ JSON ท้ายข้อความ
- ห้ามแต่งข้อมูลงานที่ไม่มีอยู่จริง
- ถ้าไม่แน่ใจว่าผู้ใช้หมายถึงงานไหน ให้ถามก่อน

รูปแบบ JSON action (ใส่ท้ายสุดของ response เสมอถ้ามี action):
{"action": "add", "name": "...", "from_who": "...", "deadline": "YYYY-MM-DD"}
{"action": "set_status", "id": 1, "status": "กำลังทำ"}
{"action": "delete", "id": 1}
{"action": "none"}
"""

# ── AI call ────────────────────────────────────────────────────

def ask_ai(user_id, user_msg):
    tasks = get_tasks()

    if user_id not in _history:
        _history[user_id] = []

    _history[user_id].append({"role": "user", "content": user_msg})

    # เก็บแค่ 10 ข้อความล่าสุด
    history = _history[user_id][-10:]

    resp = ai.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        system=build_system(tasks),
        messages=history
    )

    ai_text = resp.content[0].text
    _history[user_id].append({"role": "assistant", "content": ai_text})

    # แยก action JSON กับข้อความปกติ
    reply, action = parse_response(ai_text)

    # ทำ action
    result_msg = execute_action(action) if action else ""

    return reply + (f"\n\n{result_msg}" if result_msg else "")


def parse_response(text):
    """แยก JSON action ออกจากข้อความ"""
    import re
    pattern = r'\{[^{}]*"action"[^{}]*\}'
    match   = re.search(pattern, text)
    if not match:
        return text.strip(), None
    try:
        action    = json.loads(match.group())
        clean_txt = text[:match.start()].strip()
        return clean_txt, action
    except:
        return text.strip(), None


def execute_action(action):
    a = action.get("action")
    if a == "add":
        tid = add_task(
            action.get("name", ""),
            action.get("from_who", ""),
            action.get("deadline", "")
        )
        dl = f" (ส่ง {action['deadline']})" if action.get("deadline") else ""
        return f"✅ บันทึกงาน #{tid}{dl} แล้วครับ"

    elif a == "set_status":
        ok     = set_status(action["id"], action["status"])
        emoji  = {"รอทำ":"⏳","กำลังทำ":"🔄","รอคนอื่น":"🕐","เสร็จ":"✅"}.get(action["status"],"")
        return f"{emoji} งาน #{action['id']} → {action['status']}" if ok else ""

    elif a == "delete":
        ok = delete_task(action["id"])
        return f"🗑️ ลบงาน #{action['id']} แล้ว" if ok else ""

    return ""

# ── Morning report (ยังใช้ AI) ────────────────────────────────

def morning_report():
    tasks   = get_tasks()
    pending = [t for t in tasks if t["status"] != "เสร็จ"]
    if not pending:
        msg = "🌅 สวัสดีตอนเช้า!\n\nไม่มีงานค้างเลย 🎉"
    else:
        today = datetime.now(TH_TZ).strftime("%d/%m/%Y")
        tasks_str = "\n".join(
            f"- [{t['id']}] {t['name']} | {t['status']}"
            + (f" | deadline {t['deadline']}" if t.get("deadline") else "")
            for t in pending
        )
        prompt = f"""วันนี้ {today} มีงานค้าง {len(pending)} รายการ:
{tasks_str}

สรุปรายงานเช้าแบบกระชับ บอกว่าวันนี้ควรโฟกัสงานอะไรก่อน เน้น deadline ที่ใกล้หรือเลยแล้ว ใช้ emoji ให้ดูง่าย ตอบเป็นภาษาไทย ไม่เกิน 15 บรรทัด"""
        resp = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        msg = "🌅 รายงานงานประจำวัน\n\n" + resp.content[0].text

    if MY_ID:
        line.push_message(MY_ID, TextSendMessage(text=msg))

# ── LINE webhook ───────────────────────────────────────────────

@app.route("/callback", methods=["POST"])
def callback():
    sig  = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try: handle.handle(body, sig)
    except InvalidSignatureError: abort(400)
    return "OK"

@handle.add(MessageEvent, message=TextMessage)
def on_message(event):
    user_id = event.source.user_id
    text    = event.message.text.strip()
    try:
        reply = ask_ai(user_id, text)
    except Exception as e:
        reply = f"เกิดข้อผิดพลาด: {str(e)}"
    line.reply_message(event.reply_token, TextSendMessage(text=reply))


if __name__ == "__main__":
    sched = BackgroundScheduler(timezone=TH_TZ)
    sched.add_job(morning_report, "cron", hour=8, minute=0)
    sched.start()
    print("🤖 AI Task Bot พร้อมแล้ว")
    app.run(host="0.0.0.0", port=5000)
