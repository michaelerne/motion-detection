
import cv2
import imutils
import datetime
import yaml
from flask import Flask, Response

from threading import Thread
import time

app = Flask(__name__)

cameras = {}

with open("config.yaml", 'r') as config_file:
    try:
        config = yaml.load(config_file)
    except yaml.YAMLError as e:
        print(e)
        exit(1)


def send_mail(camera_description):
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg['From'] = config['email']['from_address']
        msg['To'] = config['email']['to_address']
        msg['Subject'] = config['email']['subject'].replace('%CAMERA%', camera_description)

        body = config['email']['body'].replace('%CAMERA%', camera_description)
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(config['email']['smtp']['server'], config['email']['smtp']['port'])
        server.starttls()
        server.login(config['email']['smtp']['user'], config['email']['smtp']['password'])
        text = msg.as_string()
        server.sendmail(config['email']['from_address'], config['email']['to_address'], text)
        server.quit()
    except Exception as e:
        return False
    return True


def get_grayscale(frame):
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (21, 21), 0)
    except:
        return None
    return gray


def get_motion(frame, reference_frame, min_area):
    motion_detected = False
    gray = get_grayscale(frame)

    frame_delta = cv2.absdiff(reference_frame, gray)
    threshold = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]

    threshold = cv2.dilate(threshold, None, iterations=2)
    contours = cv2.findContours(threshold.copy(), cv2.RETR_EXTERNAL,
                                cv2.CHAIN_APPROX_SIMPLE)
    contours = contours[0] if imutils.is_cv2() else contours[1]

    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue

        (x, y, w, h) = cv2.boundingRect(c)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
        motion_detected = True

    return motion_detected, frame, threshold, frame_delta


def add_text(frame, text):
    cv2.putText(frame, text, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
    cv2.putText(frame, datetime.datetime.now().strftime("%A %d %B %Y %I:%M:%S%p"),
                (10, frame.shape[0] - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
    return frame


def display(config, frame, threshold, frame_delta):
    if config['local_display']['show_camera_feed']:
        cv2.imshow("Camera Feed", frame)
    if config['local_display']['show_threshold']:
        cv2.imshow("Threshold", threshold)
    if config['local_display']['show_frame_delta']:
        cv2.imshow("Frame Delta", frame_delta)
    key = cv2.waitKey(1) & 0xFF

    if key == ord("q"):
        exit(0)


def get_video_capture(url):
    return cv2.VideoCapture(url)


def detect_motion(config):
    cameras[config['camera']['name']] = None
    url = 'http://%s:%s@%s:%s/%s' % (config['camera']['user'],
                                     config['camera']['password'],
                                     config['camera']['host'],
                                     config['camera']['port'],
                                     config['camera']['path'])

    # url = './video.mjpg'
    print("cam {} detecting motion on url {}".format(config['camera']['name'], url))

    cap = get_video_capture(url)

    reference_frame = None

    last_motion = datetime.datetime.now()
    last_motionless = datetime.datetime.now()

    notified = True

    frame_counter = 0
    while True:
        text = ""
        ret, frame = cap.read()
        if not ret:
            cap = get_video_capture(url)
            continue

        if frame_counter != 0:
            frame_counter -= 1
            continue
        else:
            frame_counter = config['detection']['frame_skip']

        frame = cv2.resize(frame, (640, 480))

        gray = get_grayscale(frame)

        if gray is None:
            return

        if reference_frame is None:
            reference_frame = gray
            continue

        motion_detected, frame, threshold, frame_delta = get_motion(frame, reference_frame, config['detection']['min_area'])

        if motion_detected:
            motion_since = datetime.datetime.now() - last_motionless

            text = "Motion detected for {:.2f} seconds".format(motion_since.total_seconds())
            notified = False
            last_motion = datetime.datetime.now()

            # update reference frame
            if motion_since > datetime.timedelta(seconds=config['detection']['update_reference_seconds']):
                reference_frame = gray

        else:
            motionless_since = datetime.datetime.now() - last_motion
            text = "No Motion detected for {:.2f} seconds".format(motionless_since.total_seconds())


            # notify
            if motionless_since > datetime.timedelta(seconds=config['detection']['notify_seconds']) and not notified:
                print('notify cam {} @ {}'.format(config['camera']['name'], datetime.datetime.now()))
                if config['email']['enabled']:
                    send_mail(config['camera']['description'])
                notified = True

            last_motionless = datetime.datetime.now()

        frame = add_text(frame, text)

        cameras[config['camera']['name']] = frame
        print('{}: cam {} got a frame'.format(datetime.datetime.now(), config['camera']['name']))

        display(config, frame, threshold, frame_delta)


@app.route('/video_feed/<camera>')
def video_feed(camera):
    return Response(get_frame(camera),
                    mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/')
def index():
    page = '''
<html>
  <head>
    <title>Motion Detection</title>
  </head>
  <body>
    <h1>Motion Detection</h1>
'''

    for camera in config['cameras']:
        page += '<h2>{}</h2><br \><img src="/video_feed/{}">'.format(camera['description'], camera['name'])

    page += '''
  </body>
</html>
    '''

    return page


def get_frame(camera):
    while True:
        frame = cameras[camera]
        jpg_frame = cv2.imencode('.jpg', frame)[1].tostring()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg_frame + b'\r\n')
        time.sleep(config['server']['frame_interval_seconds'])


threads = []

for camera_idx in range(len(config['cameras'])):
    cam_config = config.copy()
    cam_config['camera'] = cam_config['cameras'][camera_idx]
    print("starting thread for cam {}".format(cam_config['camera']['name']))
    process = Thread(target=detect_motion, args=[cam_config])
    process.start()
    threads.append(process)


app.run(host=config['server']['listen_address'], port=config['server']['port'], debug=False)


for process in threads:
    process.join()

