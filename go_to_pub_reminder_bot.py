# -*- coding: utf-8 -*-
"""
Created on Sat Sep 20 12:41:46 2025

@author: Mihail Pedus
"""

import datetime
import requests
import logging
import time
import os

from telegram.ext import Application, CommandHandler, ContextTypes, JobQueue
from telegram import Update

from icalendar import Calendar

from openai import OpenAI

TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY=os.getenv("OPENAI_API_KEY")

CHAT_IDS = []
ICAL_URLS = [
             "https://www.officeholidays.com/ics/ireland",
             "https://www.officeholidays.com/ics/russia",
             ]

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(level=logging.INFO)

def register_chat_id(update):
    chat_id = update.message.chat.id
    if chat_id not in CHAT_IDS:
        CHAT_IDS.append(chat_id)
        print(f"Новый CHAT_ID зарегистрирован: {chat_id}")

def generate_poem(event: dict) -> str:
    if event is None:
        prompt = """
Ты поэт. Составь весёлое четверостишье на русском языке про день без конкретного праздника.
Четверостишье должно приглашать друзей собраться в паб без особого повода.

Правила:
- Три первые строки — про веселье, дружбу и радость без повода.
- Четвёртая строка обязательно должна приглашать в паб, в рифму.
- Тон лёгкий, дружеский, с юмором и акцентом на Ирландском пабе, гинессе.
- Не используй слишком длинные строки.

Сгенерируй только текст четверостишья, без пояснений.
"""
    else:
        prompt = f"""
Ты поэт. Составь весёлое четверостишье на русском языке про событие.
Четверостишье должно пргилашать друзей собраться в паб.

Событие:
Дата: {event['date']}
Название: {event['summary']}
Страна/место: {event['location']}
для дополнительного контекста о празднике можно почитать на сайте {event['url']}

Правила:
- Если событие - Bank Holiday, то попробуй понять к какому конкретно празднику это приурочено и пиши имено про этот праздник
- Первые три строки четверостишья должны быть связаны с праздником или днём.
- Четвёртая строка обязательно должна приглашать в паб, в рифму.
- Тон лёгкий, дружеский, с юмором с акцентом на Ирландском пабе, гинессе.
- Не используй слишком длинные строки.


Сгенерируй только текст четверостишья, без пояснений.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",  # можно заменить на gpt-4o-mini если хочешь дешевле
        messages=[{"role": "user", "content": prompt}],
        max_tokens=100,
        temperature=0.6,
    )

    return response.choices[0].message.content.strip()

def safe_generate_poem(event):
    DEFAULT_POEM = """  
Сегодня праздник к нам пришёл,  
Хотели стих – но GPT не сработал толком.  
Хотя ошибка <{error_code}> возникла вдруг,  
Ведь в этот день веселье важней любых разлук.  
Так что, друзья, в паб пойдём без промедленья,  
Ведь праздник зовёт нас к весёлому мгновенью!
"""
    try:
        return generate_poem(event)
    except Exception as e:
        error_code = getattr(e, "code", str(e))
        print(f"Generate poem exception: {e}")

    return DEFAULT_POEM.format(error_code=error_code)

def fetch_events():
    today = datetime.date.today()
    events = []

    for url in ICAL_URLS:
        try:
            r = requests.get(url)
            r.raise_for_status()
            gcal = Calendar.from_ical(r.text)
        except Exception as e:
            print(f"Ошибка при загрузке {url}: {e}")
            continue

        for component in gcal.walk("VEVENT"):
            dt = component.get("DTSTART").dt
            if isinstance(dt, datetime.datetime):  # нормализуем к дате
                dt = dt.date()
            
            summary = str(component.get("SUMMARY"))

            # пропускаем "мостики" и "замены"
            if "bridge day" in summary.lower() or "in lieu" in summary.lower():
                continue
            
            if dt >= today:
                events.append({
                    "date": dt,
                    "summary": summary,
                    "location": str(component.get("LOCATION")),
                    "url": str(component.get("URL")),
                })
    
    # сгруппируем по дате
    grouped = defaultdict(list)
    for ev in events:
        grouped[ev["date"]].append(ev)

    collapsed = []
    for date, evs in grouped.items():
        if len(evs) == 1:
            collapsed.append(evs[0])
        else:
            collapsed.append({
                "date": date,
                "summary": "/".join(e["summary"] for e in evs),
                "location": "/".join(e["location"] for e in evs if e["location"]),
                "url": "/".join(e["url"] for e in evs if e["url"]),
            })
    # сортировка по дате            
    return sorted(collapsed, key=lambda x: x["date"])

def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    events = fetch_events()
    today = datetime.date.today()
    for event in events:
        if event["date"] < (today + datetime.timedelta(days=3)):
            poem = safe_generate_poem(event)
            for chat_id in CHAT_IDS:
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Всем привет!\nСкоро {event['summary']}\n{poem}\n🍺🍺🍺"
                )

async def start(update, context):
    register_chat_id(update)
    
    await update.message.reply_text(
        "Привет! Я барный бот 🍺\n"
        "Я могу напомнить о праздниках и сочинить четверостишье 🎉\n"
        "Чтобы узнать ближайшее событие, используй команду /next_event — и я подскажу, по какому поводу идем в паб!"
        "Если хочешь просто собрать друзей и сходить в паб без повода, воспользуйся командой /go_to_pub"
    )

async def next_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat_id(update)
    
    events = fetch_events()
    if not events:
        poem = safe_generate_poem(None)
        text = (
            f"Нет ближайших событий\n"
            f"{poem}\n🍺🍺🍺"
        )
    else :
        # берём ближайшее событие
        event = events[0]
        poem = safe_generate_poem(event)
        text = (
            f"Ближайшее событие: {event['summary']} ({event['location']})\n"
            f"Дата: {event['date']}\n\n"
            f"{poem}\n🍺🍺🍺"
        )
    await update.message.reply_text(text)
    
async def go_to_pub(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Команда /go_to_pub: проверяет ближайшее событие на этой неделе
    и отправляет стих о празднике или просто приглашение в паб.
    """
    register_chat_id(update)
    
    events = fetch_events()
    today = datetime.date.today()
    week_later = today + datetime.timedelta(days=7)

    if not events:
        # Событий нет вообще
        poem = safe_generate_poem(None)
        await update.message.reply_text(
            f"Ближайших праздников нет, но это не повод грустить!\n\n{poem}\n🍺"
        )
        return

    # События уже отсортированы по дате, берём первое
    next_event = events[0] if today <= events[0]["date"] <= week_later else None

    if next_event:
        poem = safe_generate_poem(next_event)
        await update.message.reply_text(
            f"Ближайшее событие: {next_event['summary']} ({next_event['date']})!\n\n{poem}\n🍺"
        )
    else:
        poem = safe_generate_poem(None)
        await update.message.reply_text(
            f"Ближайших праздников в течение недели нет, но не унываем!\n\n{poem}\n🍺"
        )

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("next_event", next_event))
    app.add_handler(CommandHandler("go_to_pub", go_to_pub))
    
    async def schedule_jobs(app):
        app.job_queue.run_daily(send_reminder, time=dt_time(hour=10, minute=0))

    # запускаем планировщик вместе с polling
    app.run_polling()

if __name__ == "__main__":
    main()
