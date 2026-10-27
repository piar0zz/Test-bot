#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Бэкенд + бот БЕЗ внешних зависимостей (только стандартная библиотека Python)."""
import hashlib, hmac, json, os, sqlite3, threading, time
import urllib.parse, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = os.getenv("BOT_TOKEN") or "7974686617:AAHrsTn8qf7PajoEkoKKlMydlxLj1BJ3asA"
BOT_USERNAME = "tedsafwgbot"
WEB_APP_URL = "https://piar0zz.github.io/Test-bot/"
API = f"https://api.telegram.org/bot{TOKEN}/"

REF_BONUS = 150
STORY_REWARD = 100
STORY_MIN_DELAY = 10
STORY_DAILY_LIMIT = 3

DB_LOCK = threading.Lock()
conn = sqlite3.connect("secure_ask.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, name TEXT,
    coins INTEGER DEFAULT 150, referred_by INTEGER DEFAULT NULL)""")
cur.execute("""CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, target_user_id INTEGER, sender_id INTEGER,
    question_text TEXT, answer_text TEXT DEFAULT NULL, status TEXT DEFAULT 'pending')""")
cur.execute("""CREATE TABLE IF NOT EXISTS story_claims (
    user_id INTEGER, key TEXT, started_at REAL, claimed INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, key))""")
cur.execute("""CREATE TABLE IF NOT EXISTS contacts (
    owner_id INTEGER, contact_id INTEGER, name TEXT, username TEXT,
    PRIMARY KEY (owner_id, contact_id))""")
conn.commit()

last_request_time = {}

# ---------- Telegram Bot API ----------
def tg(method, **payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(API + method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        print("TG API error:", method, e)
        return None

def send_message(chat_id, text, reply_markup=None):
    p = {"chat_id": chat_id, "text": text}
    if reply_markup:
        p["reply_markup"] = reply_markup
    return tg("sendMessage", **p)

# ---------- База ----------
def db(q, args=(), fetch=None):
    with DB_LOCK:
        c = conn.execute(q, args)
        res = None
        if fetch == "one": res = c.fetchone()
        elif fetch == "all": res = c.fetchall()
        elif fetch == "rowcount": res = c.rowcount
        conn.commit()
        return res

def user_exists(uid):
    return db("SELECT 1 FROM users WHERE user_id = ?", (uid,), "one") is not None

def register_user(user_id, name, referrer_id):
    if user_exists(user_id):
        return False, None
    ref = referrer_id if referrer_id and referrer_id != user_id and user_exists(referrer_id) else None
    coins = 150 + (REF_BONUS if ref else 0)
    db("INSERT INTO users (user_id, name, coins, referred_by) VALUES (?, ?, ?, ?)",
       (user_id, name, coins, ref))
    if ref:
        db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (REF_BONUS, ref))
    return True, ref

# ---------- Проверка initData ----------
def auth(init_data):
    try:
        parsed = dict(urllib.parse.parse_qsl(init_data or "", keep_blank_values=True))
        received_hash = parsed.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received_hash):
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > 86400:
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None

# ---------- Нижнее меню бота (постоянная клавиатура) ----------
def menu_keyboard(web_app_url=WEB_APP_URL):
    return {"keyboard": [
        [{"text": "🚀 Открыть приложение", "web_app": {"url": web_app_url}}],
        [{"text": "📇 Добавить контакты",
          "request_users": {"request_id": 1, "user_is_bot": False, "max_quantity": 50,
                            "request_name": True, "request_username": True}}],
        [{"text": "👥 Мои друзья"}, {"text": "🔗 Моя ссылка"}],
        [{"text": "📖 Справка"}],
    ], "resize_keyboard": True, "is_persistent": True}

def on_start(msg):
    user = msg.get("from") or {}
    uid = user.get("id")
    name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or f"ID {uid}"
    parts = (msg.get("text") or "").split()
    referrer_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
    is_new, ref = register_user(uid, name, referrer_id)
    if ref:
        send_message(ref, f"🎉 По твоей ссылке зарегистрировался друг ({name})!\n\n🎁 +{REF_BONUS} монет 🪙")
    url = f"{WEB_APP_URL}?startapp={referrer_id}" if referrer_id and referrer_id != uid else WEB_APP_URL
    text = ("👋 Добро пожаловать! Твой сервис анонимных вопросов запущен.\n\n"
            "👇 ВНИЗУ всегда есть кнопки меню:\n"
            "🚀 Открыть приложение — твоя стена вопросов\n"
            "📇 Добавить контакты — импортировать друзей из Telegram\n"
            "👥 Мои друзья — кого позвал и кого пригласил\n"
            "🔗 Моя ссылка — реферальная ссылка (+150 монет обоим)\n\n"
            "Начни с кнопки «📇 Добавить контакты» — и друзья появятся во вкладке «Друзья» в приложении 🙂")
    send_message(uid, text, reply_markup=menu_keyboard(url))

def on_friends(msg):
    uid = (msg.get("from") or {}).get("id")
    friends = db("SELECT user_id, name FROM users WHERE referred_by = ?", (uid,), "all")
    contacts = db("SELECT contact_id, name, username FROM contacts WHERE owner_id = ?", (uid,), "all")
    lines = []
    if friends:
        lines.append("🟢 Зарегистрировались по твоей ссылке:")
        lines += [f"   • {n}" for _, n in friends]
    if contacts:
        lines.append("📇 Твои контакты из Telegram:")
        for cid, n, un in contacts:
            status = "🟢 в боте" if user_exists(cid) else ("⚪ не в боте, @" + un if un else "⚪ не в боте")
            lines.append(f"   • {n} — {status}")
    if not lines:
        lines.append("Пока пусто. Нажми «📇 Добавить контакты» внизу, чтобы импортировать друзей из Telegram.")
    lines.append("\n💡 Приглашай друзей кнопкой «🔗 Моя ссылка» — за каждого +150 монет обоим.")
    send_message(uid, "\n".join(lines), reply_markup=menu_keyboard())

def on_link(msg):
    uid = (msg.get("from") or {}).get("id")
    link = f"https://t.me/{BOT_USERNAME}?start={uid}"
    send_message(uid, f"🔗 Твоя реферальная ссылка:\n{link}\n\nОтправь её другу. Когда он нажмёт START — вы оба получите по +150 монет.",
                 reply_markup=menu_keyboard())

def on_help(msg):
    uid = (msg.get("from") or {}).get("id")
    send_message(uid, ("📖 Как это работает:\n"
                       "1️⃣ Делись ссылкой — друг жмёт START — оба +150 монет.\n"
                       "2️⃣ Тебе шлют анонимные вопросы — отвечай в приложении во вкладке «Сообщения».\n"
                       "3️⃣ Публикуй ответы в истории Telegram — +100 монет за сторис (до 3 в день).\n"
                       "4️⃣ Монеты тратятся на раскрытие автора вопроса (500 🪙)."),
                 reply_markup=menu_keyboard())

def on_users_shared(msg):
    owner = (msg.get("from") or {}).get("id")
    users = (msg.get("users_shared") or {}).get("users") or []
    for u in users:
        cid = u.get("user_id")
        if cid == owner:
            continue
        name = " ".join(filter(None, [u.get("first_name"), u.get("last_name")])) or f"ID {cid}"
        db("INSERT OR REPLACE INTO contacts (owner_id, contact_id, name, username) VALUES (?, ?, ?, ?)",
           (owner, cid, name, u.get("username") or ""))
    send_message(owner, f"✅ Контакты добавлены ({len(users)} шт.)!\n\nОни уже во вкладке «Друзья» в приложении: кого нет в боте — тому можно отправить приглашение.",
                 reply_markup=menu_keyboard())

def bot_loop():
    offset = None
    while True:
        p = {"timeout": 30, "allowed_updates": ["message"]}
        if offset is not None:
            p["offset"] = offset
        resp = tg("getUpdates", **p)
        if not resp or not resp.get("ok"):
            time.sleep(3)
            continue
        for u in resp.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            try:
                if "users_shared" in msg:
                    on_users_shared(msg)
                else:
                    text = (msg.get("text") or "").strip()
                    if text.startswith("/start"):
                        on_start(msg)
                    elif text == "👥 Мои друзья":
                        on_friends(msg)
                    elif text == "🔗 Моя ссылка":
                        on_link(msg)
                    elif text == "📖 Справка":
                        on_help(msg)
                    elif text:
                        send_message((msg.get("from") or {}).get("id"),
                                     "Я понимаю только кнопки меню внизу 👇",
                                     reply_markup=menu_keyboard())
            except Exception as e:
                print("update error:", e)

# ---------- HTTP эндпоинты мини-аппа ----------
def read_user(data):
    return auth(data.get("initData", ""))

def h_send_question(data):
    user = read_user(data)
    if not user: return 401, {"status": "error", "reason": "Unauthorized"}
    sender_id = user["id"]
    target_id, question = data.get("target_id"), data.get("question")
    if not str(target_id).isdigit() or not question:
        return 400, {"status": "error", "reason": "Пустые данные"}
    target_id = int(target_id)
    if not user_exists(target_id):
        return 404, {"status": "error", "reason": "Получатель не найден"}
    now = time.time()
    with DB_LOCK:
        if now - last_request_time.get(sender_id, 0) < 5:
            return 429, {"status": "error", "reason": "Слишком частые запросы."}
        last_request_time[sender_id] = now
    db("INSERT INTO questions (target_user_id, sender_id, question_text) VALUES (?, ?, ?)",
       (target_id, sender_id, question[:300]))
    send_message(target_id, "📬 Тебе пришел новый анонимный вопрос!\n\nЗайди в приложение во вкладку «Сообщения», чтобы ответить.")
    return 200, {"status": "ok"}

def h_get_user_data(data):
    user = read_user(data)
    if not user: return 401, {"error": "Unauthorized"}
    uid = user["id"]
    row = db("SELECT coins FROM users WHERE user_id = ?", (uid,), "one")
    if not row:
        return 200, {"registered": False, "coins": 0, "friends": [], "contacts": []}
    friends = [{"id": r[0], "name": r[1], "avatar": "👤"} for r in
               db("SELECT user_id, name FROM users WHERE referred_by = ?", (uid,), "all")]
    contacts = [{"id": r[0], "name": r[1], "username": r[2], "in_bot": user_exists(r[0])} for r in
                db("SELECT contact_id, name, username FROM contacts WHERE owner_id = ?", (uid,), "all")]
    return 200, {"registered": True, "coins": row[0], "friends": friends, "contacts": contacts}

def h_story_start(data):
    user = read_user(data)
    key = str(data.get("key", ""))[:64]
    if not user or not key or not user_exists(user["id"]):
        return 401, {"error": "Unauthorized"}
    db("INSERT OR IGNORE INTO story_claims (user_id, key, started_at) VALUES (?, ?, ?)",
       (user["id"], key, time.time()))
    return 200, {"status": "ok"}

def h_reward_story(data):
    user = read_user(data)
    key = str(data.get("key", ""))[:64]
    if not user or not key:
        return 401, {"error": "Unauthorized"}
    uid, now = user["id"], time.time()
    row = db("SELECT started_at, claimed FROM story_claims WHERE user_id = ? AND key = ?", (uid, key), "one")
    if not row: return 400, {"error": "Сторис не начиналась"}
    if row[1]: return 409, {"error": "Награда за этот ответ уже получена"}
    if now - row[0] < STORY_MIN_DELAY: return 429, {"error": "Слишком рано"}
    done = db("SELECT COUNT(*) FROM story_claims WHERE user_id = ? AND claimed = 1 AND started_at > ?",
              (uid, now - 86400), "one")[0]
    if done >= STORY_DAILY_LIMIT: return 429, {"error": "Дневной лимит наград исчерпан"}
    if db("UPDATE story_claims SET claimed = 1 WHERE user_id = ? AND key = ? AND claimed = 0",
          (uid, key), "rowcount") == 0:
        return 409, {"error": "Уже получено"}
    db("UPDATE users SET coins = coins + ? WHERE user_id = ?", (STORY_REWARD, uid))
    coins = db("SELECT coins FROM users WHERE user_id = ?", (uid,), "one")[0]
    return 200, {"status": "ok", "coins": coins}

ROUTES = {
    "/send_question": h_send_question,
    "/get_user_data": h_get_user_data,
    "/story_start": h_story_start,
    "/reward_story": h_reward_story,
}

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/health"):
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(200); self._cors()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)
        else:
            self.send_response(404); self._cors()
            self.send_header("Content-Length", "0"); self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try: data = json.loads(raw or b"{}")
        except Exception: data = {}
        fn = ROUTES.get(self.path.split("?")[0])
        if not fn:
            status, body = 404, {"error": "not found"}
        else:
            try: status, body = fn(data)
            except Exception as e:
                print("handler error:", e); status, body = 500, {"error": "server error"}
        payload = json.dumps(body).encode()
        self.send_response(status); self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def log_message(self, *args):
        pass

if __name__ == "__main__":
    threading.Thread(target=bot_loop, daemon=True).start()
    PORT = int(os.getenv("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"🚀 Бэкенд запущен на порту {PORT} (без зависимостей)")
    server.serve_forever()
