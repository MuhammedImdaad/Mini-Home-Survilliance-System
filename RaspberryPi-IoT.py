from picamera.array import PiRGBArray
from picamera import PiCamera
import argparse
import warnings
import datetime
import imutils
import json
import time
import cv2
import firebase_admin
from firebase_admin import db
from firebase_admin import storage
import paho.mqtt.client as mqtt
import uuid

def on_message(client, userdata, message):
    txt = str(message.payload.decode('utf-8'))
    print("message received " ,txt)
    print("message topic=",message.topic)
    print("message retain flag=",message.retain)
    if txt[:4]=='Send':
        framenm= 'requested_images/frame%s.png'%(uuid.uuid1())
        cv2.imwrite(framenm,frame)
        print ('done')
        blob = bucket.blob(framenm)
        blob.upload_from_filename(framenm)
        url1 = 'https://storage.googleapis.com/sem3-iot.appspot.com/'+framenm
        print (url1)
        client.publish('Sem3-iot-03',url1)
        time.sleep(0.5)
broker_address="broker.hivemq.com"
client = mqtt.Client("Sem3-iot")
client.on_message=on_message
client.connect(host=broker_address,port=1883)
client.subscribe("Sem3-iot-03")
client.loop_start()

ap = argparse.ArgumentParser()
ap.add_argument("-c", "--conf", required=True,help="path to the JSON configuration file")
args = vars(ap.parse_args())

warnings.filterwarnings("ignore")
conf = json.load(open(args["conf"]))

cred = firebase_admin.credentials.Certificate(
'sem3-iot-firebase-adminsdk-eh0i0-b5584b5c89.json')
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://sem3-iot.firebaseio.com',
    'storageBucket': 'sem3-iot.appspot.com'
})
ref = db.reference()
bucket = storage.bucket()

camera = PiCamera()
camera.resolution = tuple(conf["resolution"])
camera.framerate = conf["fps"]
rawCapture = PiRGBArray(camera, size=tuple(conf["resolution"]))

print("[INFO] warming up...")
time.sleep(conf["camera_warmup_time"])
avg = None
lastUploaded = datetime.datetime.now()
motionCounter = 0
i=0

for f in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
	frame = f.array
	timestamp = datetime.datetime.now()
	text = "Not-Detected"

	frame = imutils.resize(frame, width=500)
	gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
	gray = cv2.GaussianBlur(gray, (21, 21), 0)

	if avg is None:
		print("[INFO] starting background model...")
		avg = gray.copy().astype("float")
		rawCapture.truncate(0)
		continue

	cv2.accumulateWeighted(gray, avg, 0.5)
	frameDelta = cv2.absdiff(gray, cv2.convertScaleAbs(avg))

	thresh = cv2.threshold(frameDelta, conf["delta_thresh"], 255,cv2.THRESH_BINARY)[1]
	thresh = cv2.dilate(thresh, None, iterations=2)
	cnts = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
	cnts = imutils.grab_contours(cnts)

	for c in cnts:
		if cv2.contourArea(c) < conf["min_area"]:
			continue
		(x, y, w, h) = cv2.boundingRect(c)
		cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
		text = "Detected"
		#client.publish("Sem3-iot-01",text)
	#ref.update({'motion':text})	
	ts = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
	cv2.putText(frame, "Room Status: {}".format(text), (10, 20),cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
	cv2.putText(frame, ts, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,0.35, (0, 0, 255), 1)

	if text == "Detected":
		if (timestamp - lastUploaded).seconds >= conf["min_upload_seconds"]:
			motionCounter += 1
			print (motionCounter)
			if motionCounter >=conf["min_detection_frames"]:
				client.publish("Sem3-iot-01",text)
			if motionCounter >= conf["min_motion_frames"]:
				framename='output_images/frame%s.png'%(uuid.uuid1())
				blob=bucket.blob(framename)
				cv2.imwrite(framename,frame)
				lastUploaded = timestamp
				motionCounter = 0
				blob.upload_from_filename(framename)
				url='https://storage.googleapis.com/sem3-iot.appspot.com/'+framename #+'?authuser=0'
				print (url)
				client.publish("Sem3-iot-02",url)

	else:
		motionCounter = 0
	if conf["show_video"]:
		cv2.imshow("Security Feed", frame)
		key = cv2.waitKey(1) & 0xFF
		if key == ord("q"):
			break
	rawCapture.truncate(0)
	i+=1
