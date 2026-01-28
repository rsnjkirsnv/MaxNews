from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
import logging
from datetime import datetime
import sys
import uvicorn
from aiohttp import ClientTimeout, ClientSession, ContentTypeError
import asyncio

from models import BaseModel, AliceRequest, AliceResponse, HealthCheck
from configparser import ConfigParser

CONFIG_FILE = "./alice_skill_service.conf"

config = ConfigParser()
config.read(CONFIG_FILE, encoding='utf-8')

SERVICE_VER = config.get('General', 'SERVICE_VER')
SERVICE_NAME = config.get('General', 'SERVICE_NAME')
SERVICE_HOST = config.get('Network', 'SERVICE_HOST')
SERVICE_PORT = config.getint('Network', 'SERVICE_PORT')
MAX_SERVICE_URL = config.get('Max', 'MAX_SERVICE_URL')
LOG_DIR = config.get('Paths', 'LOG_DIR')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/service.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(SERVICE_NAME)

app = FastAPI(
    title="MAXимальные Новости для Алисы",
    description="Сервис для предоставления последних новостей из MAX каналов",
    version=SERVICE_VER
)

service_start_time = datetime.now()

async def get_news_from_max_service() -> str:

    try:
        timeout = ClientTimeout(total=10)
        async with ClientSession(timeout=timeout) as session:
            async with session.get(f"{MAX_SERVICE_URL}/today_news") as response:
                if response.status == 200:
                    data = await response.json()

                    format_text = data.get("formatted_text", "")
                    news_text = f"Вот последние новости: {format_text}"

                    if news_text:
                        logger.info(f"Получены новости из MAX сервиса: {len(news_text)} символов")
                        return news_text
                    else:
                        logger.warning("В ответе от MAX сервиса отсутствует formatted_text")
                        return "Извините, новости временно недоступны."
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка от MAX сервиса: {response.status} - {error_text}")
                    return "Извините, сервис новостей временно недоступен."

    except asyncio.TimeoutError:
        logger.error("Таймаут при подключении к сервису MAX")
        return "Извините, сервис новостей не отвечает. Попробуйте позже."
    except ContentTypeError:
        logger.error("Некорректный  формат ответаот MAX сервиса (ожидался JSON)")
        return "Извините, произошла ошибка при обработке новостей."
    except Exception as e:
        logger.error(f"Ошибка при получении новостей из MAX: {e}")
        return "Извините, произошла ошибка при получении новостей."

def create_alice_response(text: str, session_data: dict, end_session: bool = False) -> dict:
    return {
        "response": {
            "text": text,
            "tts": text,
            "end_session": end_session,
            "buttons": [
                {
                    "title": "Еще новости",
                    "hide": True
                },
                {
                    "title": "Помощь",
                    "hide": True
                }
            ]
        },
        "session": session_data,
        "version": "1.0"
    }

@app.get("/health", response_model=HealthCheck)
async def health_check():
    try:
        max_service_status = "unknown"
        try:
            async with ClientSession() as session:
                async with session.get(f"{MAX_SERVICE_URL}/health", timeout=5) as response:
                    max_service_status = "healthy" if response.status == 200 else "unhealthy"
        except:
            max_service_status = "unhealthy"

        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "service_uptime": str(datetime.now() - service_start_time),
            "service": "MAXимальные Новости для Алисы",
            "version": SERVICE_VER,
            "max_service": max_service_status
        }
        return health_status

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "timestamp": datetime.now().isoformat(),
                "error": str(e),
                "service_uptime": str(datetime.now() - service_start_time)
            }
        )

@app.post("/alice-webhook", response_model=AliceResponse)
async def handle_alice_request(alice_request: AliceRequest):
    logger.info(f"Received request from Alice")

    user_command = alice_request.request.get('original_utterance', '').lower()
    session_data = alice_request.session

    logger.info(f"Запрос: user command [{user_command}]")
    logger.info(f"Запрос: session [{session_data}]")

    if user_command in ['', 'что ты умеешь']:
        text = "Привет! Я расскажу тебе последние новости из MAX каналов. Просто скажи: 'Свежие новости' или 'Последние новости'."
    elif 'новости' in user_command or 'что нового' in user_command or 'свежие новости' in user_command or 'последние новости' in user_command:
        try:
            text = await get_news_from_max_service()
        except Exception as e:
            logger.error(f"Error fetching news from MAX: {str(e)}")
            text = "В настоящее время новости недоступны. Попробуйте позже."
    elif 'пока' in user_command or 'выход' in user_command or 'до свидания' in user_command:
        text = "До свидания! Возвращайтесь за свежими новостями!"
        alice_response = create_alice_response(text, session_data, end_session=True)
        return alice_response
    else:
        text = "Извините, я вас не поняла. Скажите 'Свежие новости', чтобы узнать последние новости."

    logger.info(f"Response: {text}")
    alice_response = create_alice_response(text, session_data)
    return alice_response

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error(f"HTTP error: {exc.status_code} - {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {str(exc)}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "Internal server error"}
    )

def main():
    logger.info(f"Запуск сервиса {SERVICE_NAME} {SERVICE_VER} на {SERVICE_HOST}:{SERVICE_PORT}...")
    logger.info(f"MAX сервис URL: {MAX_SERVICE_URL}")

    uvicorn.run(
        app,
        host=SERVICE_HOST,
        port=SERVICE_PORT,
        reload=False,  # Отключаем для продакшена
        log_level="info",
        workers=1,
        access_log=True
    )

if __name__ == "__main__":
    main()
