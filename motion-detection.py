import cv2
import imutils
import datetime
import yaml
from flask import Flask, Response, send_file
from flask_httpauth import HTTPBasicAuth
import copy

from threading import Thread, Lock
import time


app = Flask(__name__)
auth = HTTPBasicAuth()

cameras = {}
config = {}

with open("config.yaml", 'r') as config_file:
    try:
        config = yaml.load(config_file)
    except yaml.YAMLError as e:
        print(e)
        exit(1)


@auth.get_password
def get_pw(username):
    if username in config['auth']:
        return config['auth'][username]
    return None


def synchronized(func):
    func.__lock__ = Lock()

    def synced_func(*args, **kws):
        with func.__lock__:
            return func(*args, **kws)

    return synced_func


logfile = open('motion-detection.log', 'a+')


@synchronized
def log(message):
    if config['log']['log_to_file']:
        logfile.write("{}: {}\n".format(datetime.datetime.now(), message))
    print("{}: {}".format(datetime.datetime.now(), message))


def log_if(message, config_key):
    if config['log'][config_key]:
        log(message)


def send_mail(camera_description, motion_since, threshold):
    try:
        log_if("attempting to send notify mail about {}".format(camera_description), 'mail')
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart()
        msg['From'] = config['email']['from_address']
        msg['To'] = config['email']['to_address']
        msg['Subject'] = config['email']['subject'].replace('%CAMERA%', camera_description)

        body = config['email']['body'].replace('%CAMERA%', camera_description)
        body = body.replace('%MOTION_SINCE%', str(motion_since))
        body = body.replace('%THRESHOLD%', str(threshold))
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(config['email']['smtp']['server'], config['email']['smtp']['port'])
        server.starttls()
        server.login(config['email']['smtp']['user'], config['email']['smtp']['password'])
        text = msg.as_string()
        server.sendmail(config['email']['from_address'], config['email']['to_address'], text)
        server.quit()
        log_if("mail successfully sent about {}".format(camera_description), 'mail')
    except Exception as e:
        log_if("failed to send email about {}".format(camera_description), 'mail')
        log_if(e, 'mail')
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


def td_format(td_object):
    seconds = int(td_object.total_seconds())
    periods = [
        ('year',        60*60*24*365),
        ('month',       60*60*24*30),
        ('day',         60*60*24),
        ('hour',        60*60),
        ('minute',      60),
        ('second',      1)
    ]

    strings = []
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value , seconds = divmod(seconds, period_seconds)
            has_s = 's' if period_value > 1 else ''
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return ", ".join(strings)


def get_video_capture(url):
    return cv2.VideoCapture(url)


def detect_motion(config):

    cameras[config['name']] = None

    if 'url' in config:
        url = config['url']
    else:
        url = 'http://%s:%s@%s:%s/%s' % (config['user'],
                                         config['password'],
                                         config['host'],
                                         config['port'],
                                         config['path'])

    log("cam {} detecting motion on url {}".format(config['name'], url))

    cap = get_video_capture(url)

    reference_frame = None

    now = datetime.datetime.now()
    motion_state = {
        'motion': {
            'last': now,
            'since': datetime.timedelta(0),
            'last_notification': now
        },
        'motionless': {
            'last': now,
            'since': datetime.timedelta(0),
            'last_notification': now
        }
    }

    notified = True

    frame_counter = 0

    threshold = None
    frame_delta = None

    update_reference_delta = datetime.timedelta(seconds=config['detection']['update_reference_seconds'])
    notify_delta = datetime.timedelta(seconds=config['detection']['notify_seconds'])

    while True:
        ret, frame = cap.read()

        if not ret:
            cap = get_video_capture(url)
            continue

        if frame_counter != 0:
            frame_counter -= 1
            continue
        else:
            frame_counter = config['detection']['frame_skip']

        frame = cv2.resize(frame, (config['resize']['x'], config['resize']['y']))

        gray = get_grayscale(frame)

        if gray is None:
            continue

        if reference_frame is None:
            reference_frame = gray
            continue

        if config['detection']['enabled']:
            motion_detected, frame, threshold, frame_delta = get_motion(frame, reference_frame,
                                                                        config['detection']['min_area'])

            if motion_detected:
                if motion_state['motionless']['since'] != datetime.timedelta(0):
                    log_if("cam {}: motion detected after {} seconds of no motion".format(config['name'], motion_state['motionless']['since']),
                           'motion_changes')
                    motion_state['motionless']['since'] = datetime.timedelta(0)
                motion_state['motion']['since'] = datetime.datetime.now() - motion_state['motionless']['last']

                text = "Motion detected for {:.2f} seconds".format(motion_state['motion']['since'].total_seconds())
                notified = False
                motion_state['motion']['last'] = datetime.datetime.now()

                # update reference frame
                if motion_state['motion']['since'] > update_reference_delta:
                    reference_frame = gray

            else:
                if motion_state['motion']['since'] != datetime.timedelta(0):
                    log_if("cam {}: no motion detected after {} seconds of motion".format(config['name'], motion_state['motion']['since']), 'motion_changes')
                    motion_state['motion']['since'] = datetime.timedelta(0)
                motion_state['motionless']['since'] = datetime.datetime.now() - motion_state['motion']['last']
                text = "No Motion detected for {:.2f} seconds".format(motion_state['motionless']['since'].total_seconds())

                # notify
                if motion_state['motionless']['since'] > notify_delta:
                    if not notified:
                        log_if('notify cam {}'.format(config['name']), 'notify')
                        if config['email']['enabled']:
                            send_mail(config['description'], td_format(motion_state['motion']['since']), config['detection']['notify_seconds'])
                        notified = True
                    else:
                        log_if('no notify (already notified) cam {}'.format(config['name']), 'already_notified')
                motion_state['motionless']['last'] = datetime.datetime.now()

            frame = add_text(frame, text)

        cameras[config['name']] = frame
        if config['log']['frames_recieved']:
            log('cam {} got a frame'.format(config['name']))

        display(config, frame, threshold, frame_delta)


@app.route('/video_feed/<camera>')
@auth.login_required
def video_feed(camera):
    if has_frame(camera):
        return Response(get_frame(camera),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    else:
        return send_file('./img/offline.jpg', mimetype='image/jpeg', cache_timeout=-1)

@app.route('/')
@auth.login_required
def index():
    page = '''
<html>
<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family: Arial;
}

.header {
    text-align: center;
    padding: 32px;
}

.row {
    display: -ms-flexbox; /* IE10 */
    display: flex;
    -ms-flex-wrap: wrap; /* IE10 */
    flex-wrap: wrap;
    padding: 0 4px;
}

.column {
    -ms-flex: 50%; /* IE10 */
    flex: 50%;
    max-width: 50%;
    padding: 0 4px;
}

.column img {
    margin-top: 8px;
    vertical-align: middle;
}


@media screen and (max-width: 1280px) {
    .column {
        -ms-flex: 100%;
        flex: 100%;
        max-width: 100%;
    }
}
</style>

  <head>
    <title>Motion Detection</title>
  </head>
  <body>
    <h1>Motion Detection</h1>
'''

    for idx, camera in enumerate(config['cameras']):
        if idx % 2 == 0:
            page += '<div class="row">'

        page += '<div class="column">'

        page += '<h2>{}</h2><br \><img src="/video_feed/{}" style="width:100%">'.format(camera['description'], camera['name'])

        page += '</div>'

        if idx % 2 == 1:
            page += '</div>'

    page += '''
    
  </body>
</html>
    '''

    return page


def has_frame(camera):
    return camera not in cameras or cameras[camera] is not None


def get_frame(camera):
    while True:
        frame = cameras[camera]
        jpg_frame = cv2.imencode('.jpg', frame)[1].tostring()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpg_frame + b'\r\n')
        time.sleep(config['server']['frame_interval_seconds'])


def merge(a, b, path=None):
    if path is None: path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass
            else:
                a[key] = b[key]
        else:
            a[key] = b[key]
    return a


threads = []

for camera_idx in range(len(config['cameras'])):
    cam_config = copy.deepcopy(config)
    merge(cam_config, config['cameras'][camera_idx])
    del cam_config['cameras']

    log("starting thread for cam {}".format(cam_config['name']))

    process = Thread(target=detect_motion, args=[cam_config])
    process.start()
    threads.append(process)

app.run(host=config['server']['listen_address'], port=config['server']['port'], debug=False)

for process in threads:
    process.join()
