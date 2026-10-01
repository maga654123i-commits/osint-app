import sqlite3
import time
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- Настройка Базы Данных ---

def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    # Таблица пользователей и их попыток
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            balance INTEGER DEFAULT 1,
            max_free_limit INTEGER DEFAULT 1,
            free_replenish_amount INTEGER DEFAULT 1,
            last_replenish_time INTEGER
        )
    ''')
    conn.commit()
    conn.close()

init_db()

THREE_DAYS_IN_SECONDS = 3 * 24 * 60 * 60  # 3 дня в секундах

def get_or_create_user(user_id):
    """Получает данные пользователя или создает нового с 1 бесплатной попыткой."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance, max_free_limit, free_replenish_amount, last_replenish_time FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    current_time = int(time.time())

    if not user:
        # Новый пользователь: 1 попытка, начисление раз в 3 дня
        cursor.execute(
            "INSERT INTO users (user_id, balance, max_free_limit, free_replenish_amount, last_replenish_time) VALUES (?, 1, 1, 1, ?)",
            (user_id, current_time)
        )
        conn.commit()
        conn.close()
        return {"balance": 1, "free_replenish_amount": 1}

    balance, max_free_limit, free_replenish_amount, last_replenish_time = user

    # --- Логика начисления попыток раз в 3 дня ---
    if current_time - last_replenish_time >= THREE_DAYS_IN_SECONDS:
        # Начисляем, только если текущий баланс МЕНЬШЕ лимита
        if balance < max_free_limit:
            new_balance = min(balance + free_replenish_amount, max_free_limit)
            cursor.execute(
                "UPDATE users SET balance = ?, last_replenish_time = ? WHERE user_id = ?",
                (new_balance, current_time, user_id)
            )
            conn.commit()
            balance = new_balance

    conn.close()
    return {"balance": balance, "free_replenish_amount": free_replenish_amount}

def deduct_attempt(user_id):
    """Списывает 1 попытку при поиске."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance - 1 WHERE user_id = ? AND balance > 0", (user_id,))
    success = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return success

def add_paid_subscription(user_id, extra_attempts=3, new_period_amount=4):
    """Покупка: прибавляет попытки и меняет регулярное начисление на 4 попытки."""
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE users 
        SET balance = balance + ?, 
            max_free_limit = ?, 
            free_replenish_amount = ? 
        WHERE user_id = ?
    ''', (extra_attempts, new_period_amount, new_period_amount, user_id))
    conn.commit()
    conn.close()

# --- Маршруты Flask ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/user_status', methods=['POST'])
def user_status():
    user_id = request.json.get('user_id', 'guest_user')
    user_info = get_or_create_user(user_id)
    return jsonify(user_info)

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json
    user_id = data.get('user_id', 'guest_user')
    query_type = data.get('type')
    query_value = data.get('query', '').strip()

    # Проверяем и обновляем баланс
    user_info = get_or_create_user(user_id)
    if user_info['balance'] <= 0:
        return jsonify({
            "error": "У вас закончились попытки! Подождите 3 дня или купите дополнительный пакет."
        }), 403

    # Списываем попытку
    if not deduct_attempt(user_id):
        return jsonify({"error": "Недостаточно попыток"}), 403

    # Выполняем поиск (здесь твои OSINT-функции)
    result_data = {
        "message": f"Успешный поиск по запросу '{query_value}'",
        "type": query_type
    }

    # Возвращаем результат и оставшийся баланс
    new_status = get_or_create_user(user_id)
    return jsonify({
        "success": True,
        "data": result_data,
        "remaining_attempts": new_status['balance']
    })

# Эмуляция покупки пакета
@app.route('/api/buy_attempts', methods=['POST'])
def buy_attempts():
    user_id = request.json.get('user_id', 'guest_user')
    # Начисляем 3 попытки сразу и ставим регулярное начисление = 4
    add_paid_subscription(user_id, extra_attempts=3, new_period_amount=4)
    new_status = get_or_create_user(user_id)
    return jsonify({
        "success": True, 
        "message": "Покупка успешно оформлена!", 
        "new_balance": new_status['balance']
    })

if __name__ == '__main__':
    app.run(debug=True, port=5000)
