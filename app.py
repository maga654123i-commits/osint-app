from flask import Flask, render_template, request, jsonify
import sqlite3
from datetime import datetime
import phonenumbers
from phonenumbers import geocoder, carrier
import requests
import threading
import asyncio
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.types import LabeledPrice, PreCheckoutQuery, InlineKeyboardMarkup, InlineKeyboardButton

app = Flask(__name__)

# --- БАЗА ДАННЫХ ---
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
    conn.close()
    return attempts

# --- FLASK ВЕБ-САЙТ ---
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
    # Если баланс >= 999999, возвращаем специальную метку
    if balance >= 999999:
        return jsonify({'balance': '∞ (Админ)'})
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
    # Если у пользователя БЕСКОНЕЧНЫЙ баланс (>= 999999), то НЕ СПИСЫВАЕМ попытки!
    if attempts < 999999:
        conn.execute('UPDATE users SET attempts = attempts - 1 WHERE user_id = ?', (user_id,))
        conn.commit()
    
    updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
    remaining = updated_user['attempts'] if updated_user else 0
    conn.close()

    result_data = {}

    if search_type == 'person':
        parts = query.split(',')
        fio = parts[0].strip()
        bday = parts[1].strip() if len(parts) > 1 else "Не указана"
        clean_fio = fio.replace(' ', '+')

        result_data = {
            "ФИО человека": fio,
            "Дата рождения": bday,
            "Статус": "Данные успешно сформированы",
            "Поиск совпадений в Google": f"https://www.google.com/search?q=\"{fio}\"",
            "Поиск профиля ВКонтакте": f"https://vk.com/search?c%5Bq%5D={clean_fio}&c%5Bsection%5D=people",
            "Проверка ИИН / Налоги (РК)": "https://kgd.gov.kz/ru/services/taxpayer_search",
            "Рекомендация": "Используйте открытые ссылки выше для проверки публичных профилей и документов."
        }

    elif search_type == 'phone':
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
                result_data = {"Ошибка": "Неверный формат номера."}
        except Exception:
            result_data = {"Ошибка": "Ошибка при разборе номера."}

    elif search_type == 'company':
        if len(query) in [10, 12] and query.isdigit():
            try:
                res = requests.get(f"https://suggestions.dadata.ru/suggestions/api/4_1/rs/findById/party", 
                                   json={"query": query}, 
                                   headers={"Authorization": "Token 8c1c5e4235e2985160882e34289569733054f9a0"})
                data = res.json()
                if data.get('suggestions'):
                    info = data['suggestions'][0]['data']
                    result_data = {
                        "Наименование": info.get('name', {}).get('full_with_opf'),
                        "ИНН": info.get('inn'),
                        "ОГРН": info.get('ogrn'),
                        "Адрес": info.get('address', {}).get('value')
                    }
                else:
                    result_data = {"Статус": "ИНН валиден, записей в открытом реестре не найдено."}
            except Exception:
                result_data = {"ИНН": query, "Формат": "Корректный"}
        else:
            result_data = {"Ошибка": "ИНН должен состоять из 10 или 12 цифр"}

    elif search_type == 'net':
        try:
            res = requests.get(f"http://ip-api.com/json/{query}?lang=ru").json()
            if res.get('status') == 'success':
                result_data = {
                    "IP/Домен": query,
                    "Страна": res.get('country'),
                    "Город": res.get('city'),
                    "Провайдер": res.get('isp'),
                    "Координаты": f"{res.get('lat')}, {res.get('lon')}"
                }
            else:
                result_data = {"Ошибка": "Не удалось получить данные по этим координатам/IP"}
        except Exception:
            result_data = {"Ошибка": "Ошибка сети."}

    elif search_type == 'social':
        clean_user = query.replace('@', '').replace('https://vk.com/', '')
        result_data = {
            "Запрос": clean_user,
            "Профиль VK": f"https://vk.com/{clean_user}",
            "Профиль Telegram": f"https://t.me/{clean_user}",
            "Google Поиск": f"https://www.google.com/search?q=\"{clean_user}\""
        }
    else:
        result_data = {
            "Тип запроса": search_type,
            "Запрос": query,
            "Статус": "Запрос обработан."
        }

    display_remaining = "∞" if remaining >= 999999 else remaining
    return jsonify({'success': True, 'data': result_data, 'remaining_attempts': display_remaining})

@app.route('/api/buy_attempts', methods=['POST'])
def buy_attempts():
    data = request.json or {}
    user_id = data.get('user_id')
    code = (data.get('code') or '').strip().upper()
    
    if not user_id:
        return jsonify({'error': 'No user_id provided'}), 400

    VALID_CODES = {
        "PROMO100": 5,
        "VIP1000": 20,
        "ADMIN_PASS": 100,
        "OSINT_CREATOR_9999_SECRET": 999999  # Выдаёт 999999 попыток (Бесконечный доступ)
    }

    if code in VALID_CODES:
        add_attempts = VALID_CODES[code]
        conn = get_db_connection()
        conn.execute('UPDATE users SET attempts = attempts + ? WHERE user_id = ?', (add_attempts, user_id))
        conn.commit()
        
        updated_user = conn.execute('SELECT attempts FROM users WHERE user_id = ?', (user_id,)).fetchone()
        new_balance = updated_user['attempts'] if updated_user else 0
        conn.close()
        
        msg_balance = "∞ (Бесконечно)" if new_balance >= 999999 else f"{new_balance} попыток"
        return jsonify({'success': True, 'message': f'Активировано! Права Администратора получены. Баланс: {msg_balance}', 'new_balance': msg_balance})
    else:
        return jsonify({'success': False, 'error': 'Неверный ключ доступа/промокод!'})

# --- TELEGRAM БОТ ДЛЯ ПРИЕМА ОПЛАТЫ STARS ---
BOT_TOKEN = "8970932287:AAEvRQHEVqHHFyeQlXRPS6GvbLA6hkUlXME"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 5 попыток (50 ⭐️)", callback_data="buy_5")],
        [InlineKeyboardButton(text="🚀 20 попыток (150 ⭐️)", callback_data="buy_20")]
    ])
    await message.answer(
        "👋 **Добро пожаловать в бот оплаты OSINT Search Engine!**\n\n"
        "Выберите желаемый пакет попыток для покупки за Telegram Stars:",
        reply_markup=kb,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    pack = callback.data
    
    if pack == "buy_5":
        title = "Пакет: 5 попыток"
        description = "Ключ доступа на 5 поисковых запросов в OSINT-сервисе"
        price = 50
        payload = "pack_5"
    else:
        title = "Пакет: 20 попыток"
        description = "Ключ доступа на 20 поисковых запросов в OSINT-сервисе"
        price = 150
        payload = "pack_20"

    prices = [LabeledPrice(label=title, amount=price)]

    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=description,
        provider_token="",
        currency="XTR",
        prices=prices,
        start_parameter="osint-pay",
        payload=payload
    )
    await callback.answer()

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@dp.message(F.successful_payment)
async def process_pay_success(message: types.Message):
    payload = message.successful_payment.invoice_payload
    
    if payload == "pack_5":
        code = "PROMO100"
        attempts = 5
    else:
        code = "VIP1000"
        attempts = 20

    await message.answer(
        f"✅ **Оплата прошла успешно!**\n\n"
        f"🔑 Твой ключ доступа: `{code}`\n"
        f"📊 Начисляет: {attempts} попыток\n\n"
        f"Скопируй этот код и введи его на сайте в окне пополнения баланса!",
        parse_mode="Markdown"
    )

def start_bot_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(dp.start_polling(bot))

bot_thread = threading.Thread(target=start_bot_thread, daemon=True)
bot_thread.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
