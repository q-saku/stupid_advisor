import os
import logging
import requests

from aiogram import Bot, Dispatcher, executor, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State

API_TOKEN = os.getenv('SA_BOT_API_TOKEN')

storage = MemoryStorage()
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot, storage=storage)


class OpenAIConnector(object):
    API_TOKEN = os.getenv('OPENAI_API_TOKEN')
    HEADERS = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_TOKEN}'
    }

    @classmethod
    def chat_completion(cls, context, model='gpt-3.5-turbo'):
        url = 'https://api.openai.com/v1/chat/completions'
        resp = requests.post(url, json={'model': model, 'messages': context}, headers=cls.HEADERS)
        if not resp.ok:
            logging.error(f'Something went wrong: {resp.reason} More details: {resp.text}')
        return resp


class DialogStates(StatesGroup):
    started = State()


@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    await message.reply("Это не учения. Здесь тебя ждет интерфейс к великой и ужасной ChatGPT. Жми /gpt Для старта")


@dp.message_handler(commands=['gpt'])
async def gpt_dialog(message: types.Message):
    await DialogStates.started.set()
    await message.answer("Итак. О чем же ты хотел меня спросить?")


@dp.message_handler(commands=['clear'], state=DialogStates.started)
async def gpt_dialog(message: types.Message, state: FSMContext):
    await message.answer("Контекст беседы был сброшен. Для нового диалога жми /gpt")
    d = await state.get_data()
    await state.finish()


@dp.message_handler(state=DialogStates.started)
async def send_message(message: types.Message, state: FSMContext):
    """
    Main handle to ChatGPT conversations.
    """
    async with state.proxy() as d:
        if 'context' in d:
            d['context'].append({'role': 'user', 'content': message.text})
        else:
            d['context'] = [{'role': 'user', 'content': message.text}]
        openai_answer = OpenAIConnector.chat_completion(d['context'])
        if openai_answer.ok:
            d['context'].extend(openai_answer.json()['choices'][0])
            answer = d['context'][-1].get('content')
        else:
            answer = f'У меня не получилось достучаться к оракулу. Возможно эта информация тебе поможет: {openai_answer.text}'
    await message.answer(answer, parse_mode="MarkdownV2")


def extract_context(response):
    result = []
    for choice in response['choices']:
        result.append(choice['message'])
    return result


if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
