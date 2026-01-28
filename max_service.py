import asyncio
from datetime import datetime
from aiohttp import web
import re
import logging
import os
import sys
from pathlib import Path
from pymax import MaxClient
import json
from configparser import ConfigParser

CONFIG_FILE = "./maxnews.conf"

config = ConfigParser()
config.read(CONFIG_FILE, encoding='utf-8')

SERVICE_NAME = config.get('General', 'SERVICE_NAME')
MAX_CHANNEL_COUNT = config.getint('General', 'MAX_CHANNEL_COUNT')
MAX_MSG_LEN = config.getint('General', 'MAX_MSG_LEN')
SERVICE_HOST = config.get('Network', 'SERVICE_HOST')
SERVICE_PORT = config.getint('Network', 'SERVICE_PORT')
PHONE_NUMBER = config.get('Max', 'PHONE_NUMBER')
WORK_DIR = config.get('Paths', 'WORK_DIR')
LOG_DIR = config.get('Paths', 'LOG_DIR')

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

log_file_path = Path(LOG_DIR) / 'service.log'
file_handler = logging.FileHandler(log_file_path)
file_handler.setFormatter(formatter)
root_logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
root_logger.addHandler(console_handler)

pymax_logger = logging.getLogger('pymax')
pymax_logger.propagate = False
pymax_logger.setLevel(logging.WARNING)

pymax_core_logger = logging.getLogger('pymax.core')
pymax_core_logger.propagate = False
pymax_core_logger.setLevel(logging.WARNING)

logger = logging.getLogger(SERVICE_NAME)

logger.info(f"Загружена конфигурация из файла: {CONFIG_FILE}")
logger.info(f"Настройки сервиса: имя={SERVICE_NAME}, хост={SERVICE_HOST}, порт={SERVICE_PORT}")
logger.info(f"Пути: WORK_DIR={WORK_DIR}, LOG_DIR={LOG_DIR}")
logger.info(f"Настройки Max: телефон={PHONE_NUMBER}, макс.каналов={MAX_CHANNEL_COUNT}")

def clean_message_text(text: str) -> str:

    if not text:
        return text or ""

    patterns = [
        # Удаляем эмодзи и специальные символы (кроме букв, цифр, пробелов и основной пунктуации)
        r'[^\w\s.,!?:;"\'\-]',

        # Удаляем конструкции: [содержимое], (содержимое), __содержимое__
        r'\[.*?\]|\(.*?\)|\_.*?\_',

        # Удаляем упоминания и хештеги
        r'[@#]\w+',
    ]

    cleaned_text = text
    for pattern in patterns:
        cleaned_text = re.sub(pattern, ' ', cleaned_text)

    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)

    return cleaned_text.strip()


async def get_todays_news() -> list:
    client = MaxClient(PHONE_NUMBER, work_dir=WORK_DIR)
    try:
        logger.info("Получение сегодняшних новостей...")
        await client._connect(client.user_agent)

        if client._token is None:
            await client._login()
        else:
            await client._sync()

        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_start_ts = int(today_start.timestamp() * 1000)

        today_news = []
        news_count = 0

        for channel in client.channels:
            try:
                messages = await client.fetch_history(
                    chat_id=channel.id,
                    from_time=int(datetime.now().timestamp() * 1000),
                    backward=50,
                    forward=0
                )
                if messages:
                    channel_today_messages = []

                    for msg in messages:
                        if (msg.time >= today_start_ts and
                                hasattr(msg, 'text') and
                                msg.text):
                            channel_today_messages.append(msg)

                    if channel_today_messages:
                        latest_message = max(channel_today_messages, key=lambda x: x.time)

                        cleaned_text = clean_message_text(latest_message.text)

                        if cleaned_text:
                            message_time = datetime.fromtimestamp(latest_message.time / 1000)
                            formatted_time = message_time.strftime("%H:%M")

                            news_item = {
                                "channel_name": clean_message_text(channel.title),
                                "news_text": cleaned_text,
                                "timestamp": latest_message.time,
                                "time_formatted": formatted_time
                            }
                            today_news.append(news_item)
                            logger.info(f"Добавляем новости из канала: {channel.title}...")
                            news_count += 1

            except Exception as e:
                logger.error(f"Ошибка при обработке канала {channel.title}: {e}")
                continue

        logger.info(f"Найдено новостей за сегодня: {news_count}")
        return today_news

    except Exception as e:
        logger.error(f"Ошибка при получении сегодняшних новостей: {e}")
        return []
    finally:
        await client.close()


async def get_subscribed_channels() -> list:
    client = MaxClient(PHONE_NUMBER, work_dir=WORK_DIR)
    try:
        logger.info("Получение списка подписанных каналов...")
        await client._connect(client.user_agent)

        if client._token is None:
            await client._login()
        else:
            await client._sync()

        channels_info = []

        for channel in client.channels:
            channels_info.append({
                "channel_name": channel.title,
                "subscribers_count":channel.participants_count,
                "channel_id": channel.id,
                "channel_link": channel.link,
                "channel_description": channel.description
            })

        logger.info(f"Найдено каналов: {len(channels_info)}")
        return channels_info

    except Exception as e:
        logger.error(f"Ошибка при получении списка каналов: {e}")
        return []
    finally:
        await client.close()


async def get_profile_info() -> dict:
    client = MaxClient(PHONE_NUMBER, work_dir=WORK_DIR)
    try:
        logger.info("Получение информации о профиле пользователя...")
        await client._connect(client.user_agent)

        if client._token is None:
            await client._login()
        else:
            await client._sync()

        if client.me.names and len(client.me.names) > 0:
            profile_name = client.me.names[0].name
        else:
            profile_name = "Неизвестно"

        profile_data = {
            "names": profile_name,
            "phone_number": client.phone,
            "channels_count": len(client.channels),
            "is_authenticated": client._token is not None,
            "last_sync": datetime.now().isoformat(),
            "status": "Активен" if client._token else "Не авторизован"
        }

        logger.info(f"Получены данные профиля для пользователя: {client.phone}")
        return profile_data

    except Exception as e:
        logger.error(f"Ошибка при получении профиля: {e}")
        return {"error": str(e)}
    finally:
        await client.close()

async def api_get_channels(request):
    try:
        channels_list = await get_subscribed_channels()

        sorted_channels = sorted(channels_list, key=lambda x: x["channel_name"])

        response_data = {
            "channels": sorted_channels,
            "total_count": len(sorted_channels),
            "timestamp": datetime.now().isoformat()
        }

        return create_json_response(response_data)

    except Exception as e:
        logger.error(f"API ошибка в get_channels: {e}")
        error_response = {
            "error": f"Ошибка сервера: {e}",
            "timestamp": datetime.now().isoformat()
        }
        return create_json_response(error_response)


async def api_get_profile(request):
    try:
        profile_info = await get_profile_info()

        response_data = {
            "profile": profile_info,
            "timestamp": datetime.now().isoformat(),
            "service": SERVICE_NAME
        }

        return create_json_response(response_data)

    except Exception as e:
        logger.error(f"API ошибка в get_profile: {e}")
        error_response = {
            "error": f"Ошибка сервера: {e}",
            "timestamp": datetime.now().isoformat()
        }
        return create_json_response(error_response)


def format_news_for_alice(news_list: list) -> str:
    if not news_list:
        return "Сегодня новостей пока нет."
    sorted_news = sorted(news_list, key=lambda x: x["timestamp"], reverse=True)

    formatted_entries = []

    for news in sorted_news:
        channel_name = news["channel_name"]
        news_text = news["news_text"]

        if len(news_text) > MAX_MSG_LEN:
            words = news_text.split()
            shortened_text = []
            total_length = 0
            for word in words:
                if total_length + len(word) + 1 <= MAX_MSG_LEN:
                    shortened_text.append(word)
                    total_length += len(word) + 1
                else:
                    break
            news_text = ' '.join(shortened_text) + "..."

        news_entry = f"В канале {channel_name} пишут {news_text}"
        formatted_entries.append(news_entry)

    if len(formatted_entries) > MAX_CHANNEL_COUNT:
        formatted_entries = formatted_entries[:MAX_CHANNEL_COUNT]

    result = ". ".join(formatted_entries)

    return result


def create_json_response(data):
    json_text = json.dumps(data, ensure_ascii=False, indent=2)

    response = web.Response(
        text=json_text,
        content_type='application/json'
    )
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response


# API обработчики
async def api_get_todays_news(request):
    try:
        news_list = await get_todays_news()

        response_data = {
            "news": news_list,
            "total_count": len(news_list),
            "formatted_text": format_news_for_alice(news_list),
            "timestamp": datetime.now().isoformat()
        }

        result = create_json_response(response_data)
        return result

    except Exception as e:
        logger.error(f"API ошибка в get_todays_news: {e}")
        error_response = {
            "error": f"Ошибка сервера: {e}",
            "timestamp": datetime.now().isoformat()
        }
        result = create_json_response(error_response)
        return result

async def health_check(request):
    response_data = {
        "status": "healthy",
        "service": SERVICE_NAME,
        "timestamp": datetime.now().isoformat()
    }
    return create_json_response(response_data)


async def main():
    app = web.Application()

    app.router.add_get('/today_news', api_get_todays_news)
    app.router.add_get('/channels', api_get_channels)
    app.router.add_get('/profile', api_get_profile)
    app.router.add_get('/health', health_check)

    logger.info(f"Запуск сервиса {SERVICE_NAME} на {SERVICE_HOST}:{SERVICE_PORT}...")
    logger.info("Доступные endpoints:")
    logger.info("  GET /today_news - Свежие новости")
    logger.info("  GET /channels - Список каналов")
    logger.info("  GET /profile - Информация профиля")
    logger.info("  GET /health - Проверка здоровья сервиса")

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(runner, SERVICE_HOST, SERVICE_PORT)
    await site.start()

    logger.info("Сервис успешно запущен и готов к работе")

    await asyncio.Event().wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info(f"Сервис {SERVICE_NAME} остановлен по запросу пользователя")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        sys.exit(1)