import os
import time
import threading
import http.server
import socketserver
import telebot
from telebot import types

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/?v=6'

# Веб-сервер для бесплатного тарифа Render
class SimpleHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive and running 24/7")

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

# Обработка любых сообщений и команд
@bot.message_handler(func=lambda m: True)
def handle_all_messages(message):
    try:
        # Убираем старую серую клавиатуру
        remove_kb = types.ReplyKeyboardRemove()
        
        # Создаем кнопку вызова WebApp
        inline_kb = types.InlineKeyboardMarkup()
        btn = types.InlineKeyboardButton(
            text='⚡ Открыть EV Garage',
            web_app=types.WebAppInfo(url=WEB_APP_URL)
        )
        inline_kb.add(btn)

        bot.send_message(
            message.chat.id,
            "⚡ **Бортовой журнал Geely EX5 готов к работе!**\n\nНажмите кнопку ниже, чтобы открыть журнал:",
            parse_mode="Markdown",
            reply_markup=inline_kb
        )
        
        # Удаляем старое серое меню из интерфейса
        bot.send_message(
            message.chat.id,
            "Меню очищено.",
            reply_markup=remove_kb
        )
    except Exception as e:
        print("Error sending message:", e)

if __name__ == '__main__':
    print('>>> БОТ ОБНОВЛЕН И ЗАПУЩЕН <<<')
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception as err:
            print("Polling restart:", err)
            time.sleep(3)
