from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

import os
from dotenv import load_dotenv
import sqlite3
from openai import OpenAI

load_dotenv()

ACCESS_TOKEN = os.environ.get('ACCESS_TOKEN')
CHANNEL_SECRET = os.environ.get('CHANNEL_SECRET')

app = Flask(__name__)

configuration = Configuration(access_token=ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        app.logger.info("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)

        question = event.message.text
        answer = dialogue_process(question)

        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=answer)]
            )
        )


def connect_to_database(database_name):
    return sqlite3.connect(database_name)


def create_dialogues_table(cur):
    cur.execute('''CREATE TABLE IF NOT EXISTS dialogues (
                    num INTEGER PRIMARY KEY AUTOINCREMENT,
                    role TEXT,
                    content TEXT
                    )''')

    if cur.execute('''SELECT COUNT(*) FROM dialogues''').fetchone()[0] == 0:
        cur.execute('''INSERT INTO dialogues (role, content) VALUES (?, ?)''',
                    ('system', '你是一位有用的助手。回答問題使用正體中文，勿使用簡體字'))


def insert_question(cur, question):
    cur.execute('''INSERT INTO dialogues (role, content) VALUES (?, ?)''', ('user', question))


def insert_answer(cur, answer):
    cur.execute('''INSERT INTO dialogues (role, content) VALUES (?, ?)''', ('assistant', answer))


def retrieve_dialogues(cur):
    total_records = cur.execute('''SELECT COUNT(*) FROM dialogues''').fetchone()[0]

    if total_records > 7:

        # 超過11筆清理資料庫
        if total_records > 11:
            keep_first_and_last(cur)

        # 擷取第一筆資料
        cur.execute('''SELECT * FROM dialogues LIMIT 1''')
        first_row = cur.fetchone()
        dialogues = [{'role': first_row[1], 'content': first_row[2]}]

        # 擷取最後七筆資料
        cur.execute('''SELECT * FROM dialogues ORDER BY num DESC LIMIT 7''')
        last_six_rows = cur.fetchall()[::-1]  # 將資料反向，使最後一筆資料在列表的第一個位置

        for row in last_six_rows:
            dialogues.append({'role': row[1], 'content': row[2]})

    else:
        # 直接取出所有資料
        cur.execute('''SELECT * FROM dialogues ORDER BY num''')
        dialogues = [{'role': row[1], 'content': row[2]} for row in cur.fetchall()]

    return dialogues


def openai_chat(dialogues):
    client = OpenAI()
    completion = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=dialogues
    )
    answer = completion.choices[0].message.content

    return answer


def keep_first_and_last(cur):

    # 擷取第一筆資料的 ID
    cur.execute('''SELECT num FROM dialogues LIMIT 1''')
    first_row_id = cur.fetchone()[0]

    # 擷取最後七筆資料的 ID
    cur.execute('''SELECT num FROM dialogues ORDER BY num DESC LIMIT 7''')
    last_seven_ids = [row[0] for row in cur.fetchall()]

    # 刪除除了第一筆和最後七筆資料以外的所有資料
    cur.execute('''DELETE FROM dialogues WHERE num NOT IN (?, ?, ?, ?, ?, ?, ?, ?)''', (first_row_id, *last_seven_ids))

def dialogue_process(question):
    database_name = 'dialogues.db'
    conn = connect_to_database(database_name)
    cur = conn.cursor()
    create_dialogues_table(cur)

    insert_question(cur, question)

    dialogues = retrieve_dialogues(cur)
    answer = openai_chat(dialogues)

    insert_answer(cur, answer)

    conn.commit()
    cur.close()
    conn.close()
    
    return answer


if __name__ == "__main__":
    app.run()
