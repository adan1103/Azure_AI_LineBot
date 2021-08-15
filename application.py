import os
import json
import time
import re
from flask import Flask, request, abort
from datetime import datetime, timezone, timedelta
from azure.cognitiveservices.vision.computervision import ComputerVisionClient
from azure.cognitiveservices.vision.computervision.models import OperationStatusCodes
from azure.cognitiveservices.vision.face import FaceClient
from azure.cognitiveservices.vision.face.models import TrainingStatusType
from msrest.authentication import CognitiveServicesCredentials
from imgur_python import Imgur

from PIL import Image, ImageDraw, ImageFont
from io import BytesIO

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent,
    TextMessage,
    ImageMessage,
    TextSendMessage,
    FlexSendMessage)

LINE_SECRET = os.getenv("Line_secret")
LINE_TOKEN = os.getenv("Line_token")
AZURE_SUBSCRIPTION_KEY = os.getenv("Subscription_key")
AZURE_ENDPOINT = os.getenv("Endpoint")
AZURE_FACE_KEY = os.getenv("Face_key")
AZURE_FACE_END = os.getenv("Face_end")
IMGUR_CLIEND_ID = os.getenv("Imgur_client_id")
IMGUR_CLIEND_SECRET = os.getenv("Imgur_client_secret")
IMGUR_ACCESS_TOKEN = os.getenv("Imgur_access_token")
IMGUR_REFRESH_TOKEN = os.getenv("Imgur_refresh_token")

IMGUR_CONFIG = {
  "client_id": IMGUR_CLIEND_ID,
  "client_secret": IMGUR_CLIEND_SECRET,
  "access_token": IMGUR_ACCESS_TOKEN,
  "refresh_token": IMGUR_REFRESH_TOKEN
}
IMGUR_CLIENT = Imgur(config=IMGUR_CONFIG)

CV_CLIENT = ComputerVisionClient(
    AZURE_ENDPOINT, CognitiveServicesCredentials(AZURE_SUBSCRIPTION_KEY))

FACE_CLIENT = FaceClient(
  AZURE_FACE_END, CognitiveServicesCredentials(AZURE_FACE_KEY))
PERSON_GROUP_ID = "player"

LINE_BOT = LineBotApi(LINE_TOKEN)
HANDLER = WebhookHandler(LINE_SECRET)

def azure_face_recognition(filename):
    img = open(filename, "r+b")
    detected_face = FACE_CLIENT.face.detect_with_stream(
        img, detection_model="detection_02"
    )
    # 多於一張臉的情況
    if len(detected_face) != 1:
        return ""
    results = FACE_CLIENT.face.identify(
      [detected_face[0].face_id], PERSON_GROUP_ID)
    # 沒有結果的情況
    if len(results) == 0:
        return "unknown"

    result = results[0].as_dict()

    # 找不到相像的人
    if len(result["candidates"]) == 0:
        return "unknown"
    # 雖然有類似的人，但信心程度太低
    if result["candidates"][0]["confidence"] < 0.5:
        return "unknown"
    person = FACE_CLIENT.person_group_person.get(
        PERSON_GROUP_ID, result["candidates"][0]["person_id"]
    )
    return person.name

def azure_ocr(url):

    ocr_results = CV_CLIENT.read(url, raw=True)
    operation_location_remote = \
    ocr_results.headers["Operation-Location"]
    operation_id = operation_location_remote.split("/")[-1]
    status = ["notStarted", "running"]
    while True:
        get_handw_text_results = \
        CV_CLIENT.get_read_result(operation_id)
        if get_handw_text_results.status not in status:
            break
        time.sleep(1)
        text = []
    succeeded = OperationStatusCodes.succeeded
    if get_handw_text_results.status == succeeded:
        res = get_handw_text_results.\
        analyze_result.read_results
        for text_result in res:
            for line in text_result.lines:
                if len(line.text) <= 8:
                    text.append(line.text)
    # 利用 Regular Expresion (正規表示法) 針對台灣車牌的規則過濾
    r = re.compile("[0-9A-Z]{2,4}[.-]{1}[0-9A-Z]{2,4}")
    text = list(filter(r.match, text))
    return text[0].replace(".", "-") if len(text) > 0 else ""


def azure_object_detection(url, filename):
    img = Image.open(filename)
    draw = ImageDraw.Draw(img)
    font_size = int(5e-2 * img.size[1])
    fnt = ImageFont.truetype(
      "static/TaipeiSansTCBeta-Regular.ttf", size=font_size)
    object_detection = CV_CLIENT.detect_objects(url)
    if len(object_detection.objects) > 0:
        for obj in object_detection.objects:
            left = obj.rectangle.x
            top = obj.rectangle.y
            right = obj.rectangle.x + obj.rectangle.w
            bot = obj.rectangle.y + obj.rectangle.h
            name = obj.object_property
            confidence = obj.confidence
            draw.rectangle(
              [left, top, right, bot],
              outline=(255, 0, 0), width=3)
            draw.text(
                [left, top + font_size],
                "{} {}".format(name, confidence),
                fill=(255, 0, 0),
                font=fnt,
            )
    # 把畫完的結果存檔，利用 imgur 把檔案轉成網路連結
    img.save(filename)
    image = IMGUR_CLIENT.image_upload(filename, "", "")
    link = image["response"]["data"]["link"]
# 最後刪掉圖檔
    os.remove(filename)
    return link

def azure_describe(url):
    description_results = CV_CLIENT.describe_image(url)
    output = ""
    for caption in description_results.captions:
        output += "'{}' with confidence {:.2f}% \n".format(
            caption.text, caption.confidence * 100
        )
    return output


app = Flask(__name__)

@HANDLER.add(MessageEvent, message=ImageMessage)
def handle_content_message(event):
    # 先把傳來的照片存檔
    filename = "{}.jpg".format(event.message.id)
    message_content = LINE_BOT.get_message_content(
      event.message.id)
    with open(filename, "wb") as f_w:
        for chunk in message_content.iter_content():
            f_w.write(chunk)
    f_w.close()

    # 將取得照片的網路連結
    image = IMGUR_CLIENT.image_upload(filename, "", "")
    link = image["response"]["data"]["link"]


@app.route("/")
def hello():
    "hello world"
    return "Hello World!!!!!"


@app.route("/callback", methods=["POST"])
def callback():
    # X-Line-Signature: 數位簽章
    signature = request.headers["X-Line-Signature"]
    print(signature)
    body = request.get_data(as_text=True)
    print(body)
    try:
        HANDLER.handle(body, signature)
    except InvalidSignatureError:
        print("Check the channel secret/access token.")
        abort(400)
    return "OK"
'''
# message 可以針對收到的訊息種類
@HANDLER.add(MessageEvent, message=TextMessage)
def handle_message(event):
    url_dict = {
      "TIBAME":"https://www.tibame.com/coursegoodjob/traffic_cli",
      "HELP":"https://developers.line.biz/zh-hant/docs/messaging-api/",
      "GOOGLE":"https://www.google.com.tw/?hl=zh_TW"}
# 將要發出去的文字變成TextSendMessage

    message = event.message.text.upper()
    if message == "GOOGLE": #list(url_dict.keys()):
        with open(f"templates/temp_buble.json", "r") as f_r:
            bubble = json.load(f_r)
        f_r.close()
        LINE_BOT.reply_message(event.reply_token,[FlexSendMessage(alt_text="Report", contents=bubble)])

    else:
        message = TextSendMessage(text=event.message.text)
        LINE_BOT.reply_message(event.reply_token, message)
'''
@HANDLER.add(MessageEvent, message=ImageMessage)
def handle_content_message(event):
    # 先把傳來的照片存檔
    filename = "{}.jpg".format(event.message.id)
    message_content = LINE_BOT.get_message_content(
      event.message.id)
    with open(filename, "wb") as f_w:
        for chunk in message_content.iter_content():
            f_w.write(chunk)
    f_w.close()

    # 將取得照片的網路連結
    image = IMGUR_CLIENT.image_upload(filename, "", "")
    link = image["response"]["data"]["link"]
    name = azure_face_recognition(filename)
    if name != "": # 如果只有一張人臉，輸出人臉辨識結果
        now = datetime.now(timezone(timedelta(hours=8))).\
        strftime("%Y-%m-%d %H:%M") # 注意時區
        output = "{0}, {1}".format(name, now)
        function_name = "face_recognition"
    else:
        plate = azure_ocr(link)
        link_ob = azure_object_detection(link, filename)
        # 有車牌就輸出車牌
        if len(plate) > 0:
            output = "License Plate: {}".format(plate)
            function_name = "OCR"
        # 沒有車牌就就輸出影像描述的結果
        else:
            output = azure_describe(link)
            function_name = "description"
        link = link_ob
        # 分別影像連結和偵測結果放到Flex Message
    with open("templates/temp_bubble.json", "r") as f_r:
        bubble = json.load(f_r)
    f_r.close()
    bubble['hero']['url'] = link
    bubble['body']['contents'][0]['text'] = function_name
    bubble['body']['contents'][2]['contents'][0]['contents'][0]['text'] = output
    LINE_BOT.reply_message(
        event.reply_token,
        [FlexSendMessage(alt_text="Report", contents=bubble)]
    )

