import os
import telebot
from telebot import types

TOKEN = '8952822528:AAF8qGUF4bdgYNUaoJ29pHDide4XtBjlRUU'
WEB_APP_URL = 'https://pavlik97d-sys.github.io/ev/'

bot = telebot.TeleBot(TOKEN)

@bot.message_handler(func=lambda m: True)
def send_app(m):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(text='⚡ Открыть EV Garage', web_app=types.WebAppInfo(url=WEB_APP_URL)))
    bot.send_message(m.chat.id, 'Бортовой журнал Geely EX5 готов к работе:', reply_markup=kb)

if __name__ == '__main__':
    print('>>> БОТ ЗАПУЩЕН НА СЕРВЕРЕ 24/7 <<<')
    bot.infinity_polling(skip_pending=True)
