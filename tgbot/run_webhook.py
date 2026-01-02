#!/usr/bin/env python3
import uvicorn
import asyncio
from webhook_server import app, init_bot
from config import BOT_TOKEN


async def main():
    # Инициализируем бота
    init_bot(BOT_TOKEN)

    # Запуск веб-сервера
    # config = uvicorn.Config(
    #     app,
    #     host="0.0.0.0",
    #     port=8000,
    #     ssl_keyfile="path/to/key.pem",  # Для HTTPS
    #     ssl_certfile="path/to/cert.pem"  # Для HTTPS
    # )
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8080
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())