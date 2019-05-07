from flask import Flask, request, abort, render_template
import os
import json
import base64
import redis
import urllib.parse
import requests
import numpy

from linebot import (
    LineBotApi, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)

app = Flask(__name__, static_folder='static')

line_bot_api = LineBotApi(os.environ.get('CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('CHANNEL_SECRET'))

url = urllib.parse.urlparse(os.environ["REDIS_URL"])
pool = redis.ConnectionPool(host=url.hostname,
                            port=url.port,
                            db=url.path[1:],
                            password=url.password,
                            decode_responses=True)
r = redis.StrictRedis(connection_pool=pool)

@app.route('/')
def do_get():
    return render_template('index.html')

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    try:
        # Python SDK doesn't support LINE Things event
        # => Unknown event type. type=things
        """
        for event in parser.parse(body, signature):
            handle_message(event)
        """
        # Parse JSON without SDK for LINE Things event
        events = json.loads(body)
        for event in events["events"]:
            if "things" in event:
                handle_things_event(event)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'


def handle_things_event(event):
    if event["things"]["type"] != "scenarioResult":
        return
    if event["things"]["result"]["resultCode"] != "success":
        app.logger.warn("Error result: %s", event)
        return

    # Read value end decode
    decoded = base64.b64decode(
        event["things"]["result"]["bleNotificationPayload"])

    temperature = float(numpy.frombuffer(
        buffer=decoded, dtype='int16', count=1, offset=0)[0] / 100.0)

    acx = float(numpy.frombuffer(buffer=decoded,
                                 dtype='int16', count=1, offset=2)[0] / 1000.0)
    acy = float(numpy.frombuffer(buffer=decoded,
                                 dtype='int16', count=1, offset=4)[0] / 1000.0)
    acz = float(numpy.frombuffer(buffer=decoded,
                                 dtype='int16', count=1, offset=6)[0] / 1000.0)
    accelerometer = acx + acy + acz

    if r.hget(event["source"]["userId"], 'accelerometer') is None:
        r.hmset(event["source"]["userId"], {
                'accelerometer': accelerometer, 'temperature': temperature})
    else:
        last_accelerometer = float(
            r.hget(event["source"]["userId"], 'accelerometer'))
        last_temperature = float(
            r.hget(event["source"]["userId"], 'temperature'))

        msg = ''

        if(abs(last_accelerometer - accelerometer) > 0.15):
            msg += 'バイクが動きました。'
        elif(abs(last_temperature - temperature) > 5):
            msg += 'バイクのエンジンがかけられました'

        if msg != '':
            reply_with_request(event, msg)

        r.hmset(event["source"]["userId"], {
                'accelerometer': accelerometer, 'temperature': temperature})


# Can be replaced with the function in SDK
def reply_with_request(event, msg):
    url = 'https://api.line-beta.me/v2/bot/message/reply'
    payload = {"replyToken": event["replyToken"],
               "messages": [{"type": "text", "text": msg}]}
    headers = {'content-type': 'application/json',
               'Authorization': 'Bearer %s' % os.environ.get('CHANNEL_ACCESS_TOKEN')}
    requests.post(url, data=json.dumps(payload), headers=headers)
    return


if __name__ == "__main__":
    app.debug = True
    app.run()
