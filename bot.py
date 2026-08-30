import os
import time
import threading
import http.server
import socketserver
import telebot
from telebot import types

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=11'

# Фоновый веб-сервер для 24/7 работы на Render
class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"EV Garage Bot is Online 24/7")

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(("", port), SimpleHandler) as httpd:
            httpd.serve_forever()
    except Exception as e:
        print("Server error:", e)

threading.Thread(target=run_web_server, daemon=True).start()

bot = telebot.TeleBot(TOKEN)

# Настройка постоянной кнопки WebApp в нижнем левом углу чата (Menu Button)
try:
    bot.set_chat_menu_button(
        menu_button=types.MenuButtonWebApp(
            type="web_app",
            text="⚡ EV Garage",
            web_app=types.WebAppInfo(url=WEB_APP_URL)
        )
    )
except Exception as err:
    print("Menu button error:", err)

# Приветственное сообщение
WELCOME_TEXT = """🚗 **Добро пожаловать в бортовой журнал электромобилей!**

Здесь вы можете:
• ⚡ Вносить и отслеживать историю своих зарядок
• 📊 Считать средний расход (кВт⋅ч/100 км) и затраты в рублях
• 📈 Изучать открытую статистику других электромобилей сообщества
• 📑 Выгружать готовую аналитику в Excel

_Нажмите кнопку ниже или используйте постоянную кнопку в левом нижнем углу меню:_"""

@bot.message_handler(func=lambda m: True)
def handle_message(message):
    try:
        # Создаем стильную Inline-кнопку
        inline_kb = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton(
            text='⚡ Открыть EV Garage',
            web_app=types.WebAppInfo(url=WEB_APP_URL)
        )
        inline_kb.add(btn)

        # Отправляем карточку приветствия
        bot.send_message(
            message.chat.id,
            WELCOME_TEXT,
            parse_mode="Markdown",
            reply_markup=inline_kb
        )

        # Бесследно очищаем старую зависшую серую клавиатуру
        bot.send_message(
            message.chat.id,
            "⠀",
            reply_markup=types.ReplyKeyboardRemove()
        )
    except Exception as e:
        print("Message handle error:", e)

if __name__ == '__main__':
    print('>>> БОТ ОБНОВЛЕН И ЗАПУЩЕН С НОВЫМ ИНТЕРФЕЙСОМ <<<')
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception as err:
            time.sleep(3)
