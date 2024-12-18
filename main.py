import os
import re
import logging
import requests

from logging.config import dictConfig
from aiogram import Bot, Dispatcher, executor, types, utils
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types.input_media import InputMedia

logger = logging.getLogger(__name__)

BOT_API_TOKEN = os.getenv('BOT_API_TOKEN')
AVAILABLE_MODELS = ['gpt-4o-mini', 'gpt-4o', 'o1-mini', 'gpt-3.5-turbo', 'gpt-4', 'dall-e-3']
GPT_ALL_ALLOWED_IDS = [35690816, 1277041256, 1082295207, 468387894, 613130210, 303259445]
DALLE3_ALLOWED_IDS = [238644194, 35690816]
O1_ALLOWED_IDS = [35690816]

storage = MemoryStorage()
bot = Bot(token=BOT_API_TOKEN)
dp = Dispatcher(bot, storage=storage)


class OpenAIConnector(object):
    OPENAI_API_TOKEN = os.getenv('OPENAI_API_TOKEN')
    HEADERS = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {OPENAI_API_TOKEN}'
    }

    @classmethod
    def chat_completion(cls, context, model='gpt-4o-mini'):
        url = 'https://api.openai.com/v1/chat/completions'
        request_data = {'model': model, 'messages': context}
        resp = requests.post(url, json=request_data, headers=cls.HEADERS)
        logger.info(f'REQUEST {url} with DATA {request_data}')
        if not resp.ok:
            logger.error(f'Something went wrong: {resp.reason} More details: {resp.text}')
        return resp

    @classmethod
    def image_generation(cls, prompt, size='1024x1024', count=1, model='dall-e-3'):
        url = 'https://api.openai.com/v1/images/generations'
        request_data = {'model': model, 'prompt': prompt, 'n': count, 'size': '1024x1024' }
        resp = requests.post(url, json=request_data, headers=cls.HEADERS)
        logger.info(f'IMAGE GENERATION REQUEST {url} with DATA {request_data}')
        if not resp.ok:
            logger.error(f'Something went wrong: {resp.reason} More details: {resp.text}')
        return resp


class DialogStates(StatesGroup):
    started = State()


@dp.message_handler(commands=['start'], state='*')
async def start(message: types.Message):
    await message.reply("Это не учения. Здесь тебя ждет интерфейс к великой и ужасной ChatGPT. Жми /gpt Для старта\nДисклеймер: Меня постоянно поднимают и роняют (поэтому я такой умный). Поэтому если долго молчу, нужно написать мне команду /gpt для нового диалога. Такова селяви.")


@dp.message_handler(commands=['help'], state='*')
async def help(message: types.Message):
    await message.answer(
        f"""Вот такие команды я умею обрабатывать:

/help  - Вывести это сообщение
/start - Начать пользоваться моими знаниями
/set_model - Выбрать версию модели (доступно не для всех). Пока доступны версии {AVAILABLE_MODELS}
/clear - Сбросить контекст диалога. Так как иногда я трудно улавливаю нить повествования в длинных беседах.
/gpt   - Начать новый диалог, но теперь мне можно просто написать.

""")


@dp.message_handler(commands=['gpt'], state='*')
async def gpt_dialog(message: types.Message):
    await DialogStates.started.set()
    await message.answer("Итак. О чем же ты хотел меня спросить?")


@dp.message_handler(commands=['set_model'], state='*')
async def set_model(message: types.Message, state: FSMContext):
    keyboard = types.inline_keyboard.InlineKeyboardMarkup(
        row_width=1,
    )
    for el in AVAILABLE_MODELS:
        cur_model = await get_current_model(state)
        if cur_model == el:
            button_text = el + ' ☑️'
        else:
            button_text = el
        keyboard.add(
            types.inline_keyboard.InlineKeyboardButton(text=button_text, callback_data='set_' + el)
        )
    await message.answer('Выбери модель для работы', reply_markup=keyboard)


@dp.message_handler(commands=['clear'], state=DialogStates.started)
async def gpt_dialog(message: types.Message, state: FSMContext):
    await message.answer("Контекст беседы был сброшен. Для нового диалога жми /gpt или просто напиши свое сообщение")
    d = await state.get_data()
    await state.finish()


@dp.message_handler(state=DialogStates.started)
async def send_message(message: types.Message, state: FSMContext):
    """
    Main handle to ChatGPT conversations.
    """
    async with state.proxy() as d:
        answer_message = await message.answer('Обдумываю твой вопрос..')
        if 'dall-e' in d.get('model', AVAILABLE_MODELS[0]):
            openai_answer = OpenAIConnector.image_generation(message.text, d.get('model', AVAILABLE_MODELS[0]))
            if openai_answer.ok:
                image_url = openai_answer.json()['data'][0]['url']
                answer_photo = InputMedia(type='photo', media=image_url, caption=f'Вот, что у меня получилось')
                await answer_message.edit_media(answer_photo)
                return
        if message.text.startswith('/system_message'):
            role = 'system'
            message.text = message.text.split('/system_message')[1].trim()
        else:
            role = 'user'
        if 'context' in d:
            d['context'].append({'role': role, 'content': message.text})
        else:
            d['context'] = [{'role': role, 'content': message.text}]
        if role == 'user':
            openai_answer = OpenAIConnector.chat_completion(d['context'], d.get('model', AVAILABLE_MODELS[0]))
            if openai_answer.ok:
                d['context'].extend(extract_context(openai_answer.json()))
                answer = d['context'][-1].get('content')
            else:
                answer = f'У меня не получилось достучаться к оракулу. Возможно эта информация тебе поможет: {openai_answer.text}'
        else:
            answer = f'Выставлено системное сообщение: `{message.text}`'
        logger.info(f'User_ID: {message.from_user} Request: {message.text} Response: {answer}')
        answers = paging(answer)
        await answer_message.edit_text(md_to_html(answers[0]), parse_mode=types.ParseMode.HTML)
        if len(answers) > 1:
            for a in answers[1:]:
                await message.answer(md_to_html(a), parse_mode=types.ParseMode.HTML)


@dp.message_handler(state=None)
async def unknown_message(message: types.Message, state: FSMContext):
    await DialogStates.started.set()
    await message.answer('Прости, я кажется потерял контекст нашей беседы. Придется начать все заново. Сейчас поищу ответ на твой запрос.')
    await send_message(message, state)


@dp.callback_query_handler(state='*')
async def callback_handler(callback_query: types.CallbackQuery, state: FSMContext):
    args = callback_query.data.split("_", 1)
    if args[0] == 'set':
        keyboard = callback_query.message.reply_markup.inline_keyboard
        logger.info(keyboard)
        if callback_query.from_user.id not in GPT_ALL_ALLOWED_IDS and 'gpt-4' in args[1]:
            await callback_query.answer(f'Тебе не разрешено использовать GPT-4 модели')
        elif callback_query.from_user.id not in DALLE3_ALLOWED_IDS and 'dall-e' in args[1]:
            await callback_query.answer(f'Тебе не разрешено использовать DALL-E модели')
        elif callback_query.from_user.id not in O1_ALLOWED_IDS and 'o1-mini' in args[1]:
            await callback_query.answer(f'Тебе не разрешено использовать Q1 модели')
        else:
            async with state.proxy() as d:
                d['model'] = args[1]
            for key in keyboard:
                if key[0]["callback_data"] == callback_query.data:
                    if "☑️" not in key[0]["text"]:
                        key[0]["text"] = f"{key[0].text} ☑️"
                else:
                    key[0]["text"] = f"{key[0].text.split()[0]}️"
            await callback_query.message.edit_reply_markup(
                reply_markup=types.inline_keyboard.InlineKeyboardMarkup(inline_keyboard=keyboard)
            )
            await callback_query.answer(f'Выставлена модель {args[1]}')


async def get_current_model(state: FSMContext):
    async with state.proxy() as d:
        model = d.get('model', AVAILABLE_MODELS[0])
    return model


def extract_context(response):
    result = []
    for choice in response['choices']:
        result.append(choice['message'])
    return result


def paging(message_text):
    """
    Separate full message answer by 4050 symbols. This is less than 4096 characters because you didn't convert text to html yet.
    """
    messages = []
    if len(message_text) > 4050:
        for x in range(0, len(message_text), 4050):
            messages.append(message_text[x:x+4050])
    else:
        messages.append(message_text)
    return messages


def md_to_html(text: str) -> str:
    # Format the most popular tags from source <pre> and <code> if message was cut - end with ```
    text = utils.markdown.quote_html(text)
    text = re.sub(r"```([^`].+?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    text = check_position(text, "```", "<pre>", "</pre>")
    text = re.sub(r"```([^`].+?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
    text = re.sub(r"\*\*([^`].+?)\*\*", r"<strong>\1</strong>", text, flags=re.DOTALL)
    logger.info(text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    #text = check_position(text, "`", "<code>", "</code>")
    logger.info(text)
    return text


def check_position(text, pattern, tag_open, tag_closed):
    if pattern not in text:
        return text
    position = text.find(pattern)
    if position > len(text)/2:
        text = re.sub(r"```", rf"{tag_open}", text, flags=re.DOTALL)
        text = text + tag_closed
    else:
        text = re.sub(r"```", rf"{tag_closed}", text, flags=re.DOTALL)
        text = tag_open + text
    return text


def prepare_logging(filename):
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s:%(name)s:%(process)d:%(lineno)d " "%(levelname)s %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S"
            },
        },
        "handlers": {
            "logfile": {
                "formatter": "default",
                "level": "INFO",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": filename,
                "backupCount": 2,
            },
            "output": {
                "formatter": "default",
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": [
                "logfile",
                "output"
            ]
        },
    })


if __name__ == '__main__':
    prepare_logging('stupid_advisor.log')
    executor.start_polling(dp, skip_updates=True)