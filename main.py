import os
import sqlite3
import json
import random
import string
from pathlib import Path
import requests
from flask import Flask, jsonify, request, send_from_directory

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "coolout_bot.db"

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "8103392209"))
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://coolout-bot.onrender.com").rstrip("/")

app = Flask(__name__, static_folder="static", static_url_path="")

# --- База данных ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        # Таблица для чеков
        conn.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                code TEXT PRIMARY KEY,
                is_used INTEGER DEFAULT 0,
                user_id INTEGER,
                won_prize TEXT
            )
        """)
        # Таблица пользователей (чтобы помнить, кто уже крутил)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                promocode TEXT
            )
        """)
        conn.commit()

# --- Telegram API ---
def send_message(chat_id, text):
    if not BOT_TOKEN: return
    requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": text})

# --- Генерация кодов (для админа) ---
def generate_codes(amount):
    codes = []
    with get_db() as conn:
        for _ in range(amount):
            code = ''.join(random.choices(string.digits, k=4))
            try:
                conn.execute("INSERT INTO receipts (code) VALUES (?)", (code,))
                codes.append(code)
            except sqlite3.IntegrityError:
                pass # Если код совпал, пропускаем
        conn.commit()
    return codes

# --- Эндпоинты для Mini App ---
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.post("/api/check_receipt")
def check_receipt():
    data = request.get_json() or {}
    code = data.get("code", "").strip()
    init_data = data.get("initData", "")
    
    # Достаем ID пользователя
    telegram_id = None
    try:
        from urllib.parse import parse_qs
        parsed = parse_qs(init_data)
        user_data = json.loads(parsed.get("user", ["{}"])[0])
        telegram_id = user_data.get("id")
    except: pass

    if not telegram_id: return jsonify({"error": "Ошибка авторизации"}), 401

    with get_db() as conn:
        receipt = conn.execute("SELECT * FROM receipts WHERE code = ?", (code,)).fetchone()
        if not receipt:
            return jsonify({"error": "Такой код не найден"}), 404
        if receipt["is_used"]:
            return jsonify({"error": "Этот код уже был использован"}), 400
        
        # Активируем код
        conn.execute("UPDATE receipts SET is_used = 1, user_id = ? WHERE code = ?", (telegram_id, code))
        conn.commit()
    
    return jsonify({"success": True})

@app.post("/api/spin")
def spin():
    # Список призов для колеса
    prizes = [
        {"text": "Скидка 10%", "promo_prefix": "S10"},
        {"text": "Скидка 20%", "promo_prefix": "S20"},
        {"text": "Бесплатный сироп", "promo_prefix": "SYR"},
        {"text": "Бесплатный кофе", "promo_prefix": "FREE"},
        {"text": "Скидка 15%", "promo_prefix": "S15"},
        {"text": "Круассан в подарок", "promo_prefix": "CRO"}
    ]
    
    # Рандомный выбор (можно настроить вероятности, добавив повторяющиеся элементы)
    prize = random.choice(prizes)
    promo_code = f"COOL-{prize['promo_prefix']}-{random.randint(1000, 9999)}"

    # Отправляем уведомление админу
    if ADMIN_ID:
        send_message(ADMIN_ID, f"🎡 Крутили колесо! Выигрыш: {prize['text']}. Промокод: {promo_code}")

    return jsonify({"prize": prize["text"], "promo_code": promo_code})

# --- Webhook для бота ---
@app.post("/telegram/webhook")
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")
    telegram_id = message.get("from", {}).get("id")

    if text == "/start":
        send_message(chat_id, "Привет! Если ты купил кофе в Coolout, введи 4-значный код с чека в приложении ниже 👇", 
                     )
        # Здесь нужно прикрепить кнопку меню, но проще настроить её в BotFather
        
    elif text.startswith("/gencodes") and telegram_id == ADMIN_ID:
        # Админ команда для генерации кодов
        codes = generate_codes(10)
        send_message(chat_id, f"Сгенерированы новые коды: {', '.join(codes)}")

    return jsonify({"ok": True})

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))