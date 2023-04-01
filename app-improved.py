import os
import json
import time
import traceback
from functools import wraps

import openai
import boto3
from loguru import logger
from chalice import Chalice
from telegram.ext import (
    Dispatcher,
    MessageHandler,
    Filters,
)
from telegram import ParseMode, Update, Bot
from chalice.app import Rate

from chalicelib.utils import generate_transcription, send_typing_action

# Environment variables
TOKEN = os.environ["TELEGRAM_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# Chalice Lambda app
APP_NAME = "chatgpt-telegram-bot"
MESSAGE_HANDLER_LAMBDA = "message-handler-lambda"

app = Chalice(app_name=APP_NAME)
app.debug = True

# Telegram bot
bot = Bot(token=TOKEN)
dispatcher = Dispatcher(bot, None, use_context=True)

# Cache for recent responses
response_cache = {}

#####################
# Telegram Handlers #
#####################


def ask_chatgpt(text):
    if text in response_cache:
        return response_cache[text]

    openai.api_key = OPENAI_API_KEY
    message = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "assistant",
                "content": text,
            },
        ],
    )
    logger.info(message)

    response = message["choices"][0]["message"]["content"]
    response_cache[text] = response
    return response


@send_typing_action
def process_voice_message(update, context):
    voice_message = update.message.voice
    file_id = voice_message.file_id
    file = bot.get_file(file_id)
    transcript_msg = generate_transcription(file)
    message = ask_chatgpt(transcript_msg)

    chat_id = update.message.chat_id
    context.bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode=ParseMode.MARKDOWN,
    )


@send_typing_action
def process_message(update, context):
    chat_id = update.message.chat_id
    chat_text = update.message.text

    try:
        message = ask_chatgpt(chat_text)
    except Exception as e:
        app.log.error(e)
        app.log.error(traceback.format_exc())
        context.bot.send_message(
            chat_id=chat_id,
            text="There was an exception handling your message :(",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        context.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN,
        )


############################
# Lambda Handler functions #
############################


@app.lambda_function(name=MESSAGE_HANDLER_LAMBDA)
def message_handler(event, context):
    dispatcher.add_handler(MessageHandler(Filters.text, process_message))
    dispatcher.add_handler(MessageHandler(Filters.voice, process_voice_message))

    try:
        dispatcher.process_update(Update.de_json(json.loads(event["body"]), bot))
    except Exception as e:
        print(e)
        return {"statusCode": 500}

    return {"
