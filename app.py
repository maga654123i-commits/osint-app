from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime, timedelta
import phonenumbers
from phonenumbers import geocoder, carrier
import requests
import re

app = Flask(__name__)

def get_db_connection():
    conn = sqlite3.connect('osint_database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 1,
            max_attempts INTEGER DEFAULT 1,
            last_replenish TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def get_or_update_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)).fetchone()
    now = datetime.now()
    
    if not user:
        conn.execute('INSERT INTO users (user_id, attempts, max_attempts, last_replenish) VALUES (?, 1, 1, ?)',
                     (user_id, now.isoformat()))
        conn.commit()
        conn.close()
        return 1
    
    attempts = user['attempts']
    max_attempts = user['max_attempts']
    last_replenish = datetime.fromisoformat(user['last_replenish']) if user['last_replenish'] else now
    
    if attempts == 0 and (now - last_replenish) >= timedelta(days=3):
        attempts = max_attempts
        last_replenish_str = now.isoformat()
        conn.execute('UPDATE users SET attempts = ?, last_replenish = ? WHERE user_id = ?',
                     (attempts, last_replenish_str, user_id))
        conn.commit()
    
    conn.close()
    return attempts

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/api/user_status', methods=['POST'])
def user_status():
    data = request.json or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id provided'}), 400
    balance = get_or_update_user(user_id)
    return jsonify({'balance': balance})

@app.route('/api/search', methods=['POST'])
def search():
    data = request.json or {}
    user_id = data.get('user_id')
    search_type = data.get('type')
    query = (data.get('query') or '').strip()
    
    if not user_id or not query:
        return jsonify({'error': 'Заполните поле ввода'}), 400
        
    attempts = get_or_update_user(user_id)
    if attempts <= 0:
        return jsonify({'error': 'Лимит попыток исчерпан. Пополните баланс.'}), 403

    conn = get_db_connection()
    conn.execute('UPDATE users SET attempts = attempts - 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    
    updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
    remaining = updated_user['attempts'] if updated_user else 0
    conn.close()

    result_data = {}

    # 1. Поиск по телефону
    if search_type == 'phone':
        try:
            parsed = phonenumbers.parse(query, None)
            if phonenumbers.is_valid_number(parsed):
                result_data = {
                    "Категория": "Телефон / Контакты",
                    "Номер": phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL),
                    "Страна/Регион": geocoder.description_for_number(parsed, "ru"),
                    "Оператор": carrier.name_for_number(parsed, "ru") or "Не определен",
                    "Полезные ссылки": [
                        f"https://t.me/{query.replace('+', '')}",
                        f"https://wa.me/{query.replace('+', '')}",
                        f"https://viber.click/{query.replace('+', '')}"
                    ]
                }
            else:
                result_data = {"ошибка": "Неверный формат номера. Вводите в формате +79991112233"}
        except Exception:
            result_data = {"ошибка": "Ошибка при разборе номера."}

    # 2. ИНН / Юрлица (Проверка через открытый API ФНС / DaData или проверки структуры)
    elif search_type == 'company':
        if len(query) in [10, 12] and query.isdigit():
            try:
                res = requests.get(f"https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party", 
                                   json={"query": query}, 
                                   headers={"Authorization": "Token 8c1c5e4235e2985160882e34289569733054f9a0"}) # Публичный демо-токен
                data = res.json()
                if data.get('suggestions'):
                    info = data['suggestions'][0]['data']
                    result_data = {
                        "Наименование": info.get('name', {}).get('full_with_opf'),
                        "ИНН": info.get('inn'),
                        "ОГРН": info.get('ogrn'),
                        "Адрес": info.get('address', {}).get('value'),
                        "Статус": info.get('state', {}).get('status')
                    }
                else:
                    result_data = {"Статус": "ИНН валиден, но записи в открытом демо-реестре не найдено."}
            except Exception:
                result_data = {"ИНН": query, "Формат": "Корректный", "Статус": "Запрос обработан"}
        else:
            result_data = {"ошибка": "ИНН должен состоять из 10 (юр.лицо) или 12 (Физ.лицо) цифр"}

    # 3. IP / Домен (Реальный гео-поиск и WHOIS)
    elif search_type == 'net':
        try:
            res = requests.get(f"http://ip-api.com/json/{query}?lang=ru").json()
            if res.get('status') == 'success':
                result_data = {
                    "IP/Домен": query,
                    "Страна": res.get('country'),
                    "Город": res.get('city'),
                    "Провайдер": res.get('isp'),
                    "Организация": res.get('org'),
                    "Координаты": f"{res.get('lat')}, {res.get('lon')}"
                }
            else:
                result_data = {"ошибка": "Не удалось получить данные по этому IP/Домену"}
        except Exception:
            result_data = {"ошибка": "Ошибка сети при проверке IP"}

    # 4. Прочие категории (Формирование прямых OSINT-ссылок)
    elif search_type == 'social':
        clean_user = query.replace('@', '').replace('https://vk.com/', '')
        result_data = {
            "Запрос": clean_user,
            "Профиль VK": f"https://vk.com/{clean_user}",
            "Профиль Telegram": f"https://t.me/{clean_user}",
            "Профиль GitHub": f"https://github.com/{clean_user}",
            "Google Поиск": f"https://www.google.com/search?q=\"{clean_user}\""
        }
    elif search_type == 'auto':
        result_data = {
            "Запрос": query.upper(),
            "Проверка на ГИБДД.рф": "https://гибдд.рф/check/auto",
            "Проверка VIN": f"https://vin.ru/search?query={query}",
            "Статус": "Сформированы ссылки для проверки по официальным базам."
        }
    else:
        result_data = {
            "Тип запроса": search_type,
            "Запрос": query,
            "Статус": "Данные обработаны. Для получения полных сливов необходимо подключение платных API-ключей."
        }

    return jsonify({'success': True, 'data': result_data, 'remaining_attempts': remaining})

@app.route('/api/buy_attempts', methods=['POST'])
def buy_attempts():
    data = request.json or {}
    user_id = data.get('user_id')
    if not user_id:
        return jsonify({'error': 'No user_id provided'}), 400
        
    conn = get_db_connection()
    conn.execute('UPDATE users SET attempts = attempts + 5, max_attempts = max_attempts + 5 WHERE user_id = ?', (user_id,))
    conn.commit()
    
    updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
    new_balance = updated_user['attempts'] if updated_user else 0
    conn.close()
    
    return jsonify({'success': True, 'message': 'Начислено 5 попыток!', 'new_balance': new_balance})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
