import telebot
from telebot import types
import requests
import json
import base64
import re
from datetime import datetime

# --- КОНФИГУРАЦИЯ ---
TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=103'

GEMINI_API_KEY = 'AQ.Ab8RN6LOhgXxeTni3tHuDoYaaz_xjbkqpvQpbEevspclGu7--A'

SUPABASE_REST = 'https://smxvjnlbwiaoudwlbvud.supabase.co/rest/v1/ev_cars'
SUPABASE_KEY = 'sb_publishable_XZpvUvSdYte6jLJsWDMNJg_YWgVHkc2'

bot = telebot.TeleBot(TOKEN)

def get_supabase_headers():
    return {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }

def find_user_car(user_id):
    """Поиск автомобиля владельца или со-водителя"""
    try:
        res = requests.get(f"{SUPABASE_REST}?select=*", headers=get_supabase_headers(), timeout=10)
        if res.ok:
            cars = res.json()
            user_str = str(user_id)
            for car in cars:
                if str(car.get('owner_id')) == user_str:
                    return car
                drivers = car.get('drivers') or []
                if isinstance(drivers, list) and user_str in [str(d) for d in drivers]:
                    return car
            # Если прямой привязки нет, берем первую машину
            if cars:
                return cars[0]
    except Exception as e:
        print(f"Ошибка получения авто: {e}")
    return None

def update_car_in_supabase(car):
    """Обновление журнала в Supabase"""
    try:
        url = f"{SUPABASE_REST}?id=eq.{car['id']}"
        payload = {
            'logs': car.get('logs', []),
            'updated_at': datetime.utcnow().isoformat()
        }
        res = requests.patch(url, headers=get_supabase_headers(), json=payload, timeout=10)
        return res.ok
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return False

def clean_json_string(s):
    """Очистка от markdown-блоков ```json ... ```"""
    s = re.sub(r'```json\s*', '', s)
    s = re.sub(r'```\s*', '', s)
    return s.strip()

def analyze_photo_with_gemini(image_bytes):
    """Распознавание показателей через Gemini Vision"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    b64_image = base64.b64encode(image_bytes).decode('utf-8')
    
    prompt = """
    Ты эксперт по электромобилям и зарядным станциям.
    Внимательно изучи экран (это может быть дисплей домашней зарядки типа Wallbox/Energy Charger, экран ЭЗС или приборная панель автомобиля).
    
    Найди параметры:
    1. "kwh": Заряженная энергия (kWh / кВт⋅ч / Энергия / Заряд). Например, если написано "Энергия 11.7kwh", верни 11.7. Если нет, верни null.
    2. "odo": Общий пробег автомобиля (ODO / км / Пробег / Total km). Только если это приборная панель авто. Если это зарядная станция, верни null.
    3. "location_type": Если это домашняя станция / гараж / розетка — верни "🏠 Дом". Если публичная станция — "⚡ ЭЗС".

    Верни ТОЛЬКО JSON формат:
    {"odo": null, "kwh": 11.7, "location_type": "🏠 Дом"}
    """

    payload = {
        "contents": [{
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64_image
                    }
                }
            ]
        }]
    }

    try:
        response = requests.post(url, json=payload, timeout=20)
        if response.ok:
            data = response.json()
            raw_text = data['candidates'][0]['content']['parts'][0]['text']
            cleaned = clean_json_string(raw_text)
            return json.loads(cleaned)
        else:
            print(f"Ошибка Gemini API: {response.status_code} {response.text}")
    except Exception as e:
        print(f"Ошибка парсинга Gemini: {e}")
    return None

@bot.message_handler(commands=['start'])
def start_handler(message):
    markup = types.InlineKeyboardMarkup()
    web_app = types.WebAppInfo(url=WEB_APP_URL)
    btn = types.InlineKeyboardButton(text="⚡ Открыть EV Garage", web_app=web_app)
    markup.add(btn)
    
    bot.send_message(
        message.chat.id,
        "👋 Привет! Добро пожаловать в **EV Garage**.\n\n"
        "📸 **Отчет по фото:** Просто отправьте фотографию экрана зарядки или приборной панели — показатели считаются автоматически!\n\n"
        "Открыть панель аналитики:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    user_id = message.from_user.id
    user_name = message.from_user.first_name or "Водитель"
    
    status_msg = bot.reply_to(message, "🔍 Считываю показатели с экрана зарядки...")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        img_res = requests.get(file_url, timeout=15)
        
        if not img_res.ok:
            bot.edit_message_text("❌ Не удалось загрузить фото из Telegram.", message.chat.id, status_msg.message_id)
            return

        parsed = analyze_photo_with_gemini(img_res.content)

        if not parsed or (parsed.get('odo') is None and parsed.get('kwh') is None):
            bot.edit_message_text(
                "⚠️ Не удалось четко распознать кВт⋅ч или пробег на фото.\n"
                "Сделайте снимок экрана чуть ближе или внесите сессию через WebApp.",
                message.chat.id,
                status_msg.message_id
            )
            return

        car = find_user_car(user_id)
        if not car:
            bot.edit_message_text(
                "⚠️ Автомобиль не найден. Откройте WebApp и сохраните ваш автомобиль.",
                message.chat.id,
                status_msg.message_id
            )
            return

        logs = car.get('logs') or []
        
        # Если пробег на зарядной станции отсутствует, берем последний пробег авто
        odo_val = parsed.get('odo')
        if odo_val is None:
            odo_val = logs[-1].get('odo', 0) if logs else 0
            
        kwh_val = parsed.get('kwh') or 0.0
        loc_val = parsed.get('location_type') or '🏠 Дом'
        
        # Берем тариф из настроек авто
        rates = car.get('rates') or {'night': 2.8, 'day': 6.5, 'work': 0, 'ez': 19.0}
        if 'Дом' in loc_val:
            rate_val = rates.get('night', 2.8)
        elif 'Работа' in loc_val:
            rate_val = rates.get('work', 0.0)
        else:
            rate_val = rates.get('ez', 19.0)

        total_price = round(float(kwh_val) * float(rate_val), 2)

        new_entry = {
            'odo': float(odo_val),
            'kwh': float(kwh_val),
            'rate': float(rate_val),
            'location': loc_val,
            'totalPrice': total_price,
            'price': total_price,
            'author': user_name,
            'author_id': str(user_id),
            'date': datetime.utcnow().isoformat()
        }
        logs.append(new_entry)
        car['logs'] = logs

        if update_car_in_supabase(car):
            markup = types.InlineKeyboardMarkup()
            web_app = types.WebAppInfo(url=WEB_APP_URL)
            btn = types.InlineKeyboardButton(text="📊 Открыть EV Garage", web_app=web_app)
            markup.add(btn)

            bot.edit_message_text(
                f"✅ **Сессия успешно распознана и сохранена!**\n\n"
                f"🚗 **Авто:** {car.get('name')}\n"
                f"🔋 **Заряжено:** +{kwh_val} кВт⋅ч\n"
                f"📍 **Локация:** {loc_val} ({rate_val} ₽/кВт⋅ч)\n"
                f"💰 **Стоимость:** {total_price} ₽\n"
                f"🛣️ **Пробег:** {odo_val} км\n"
                f"👤 **Записал:** {user_name}",
                message.chat.id,
                status_msg.message_id,
                reply_markup=markup,
                parse_mode="Markdown"
            )
        else:
            bot.edit_message_text("❌ Ошибка сохранения в базу данных.", message.chat.id, status_msg.message_id)

    except Exception as e:
        bot.edit_message_text(f"⚠️ Ошибка: {e}", message.chat.id, status_msg.message_id)

if __name__ == '__main__':
    print("Бот запущен и ожидает команды и фото...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
