# motion-detection

hacky python app that scrapes one or many ip cams via m-jpg, performs configurable motion detection and alerts if no motion is detected (you read that right!). Mainly used to oversee industrial machines.

USE AT YOUR OWN RISK

## dependencies

### Windows 10
Windows 10 should have all required dependencies. Please open an issue if you discover otherwise.

### Windows server 2012
Follow these instructions: https://stackoverflow.com/questions/52121143/opencv-with-python-3-6-4-on-windows-server-2012-r2-x64-import-cv2-dll-not-found

## run
start `motion-detection.exe`, be sure to configure it first (see below). Start via `cmd.exe` for log output.

webpage is by default located at (http://localhost:8080)

## config
requires a config.yaml file next to the .exe with contents like:

```yaml
auth:
  admin: ThisIsNotVerySecure
log:
  frames_recieved: False
  already_notified: True
  notify: True
  motion_changes: True
  log_to_file: True
  mail: True
cameras:
- name: cam_1
  description: Camera 1
  host: '192.168.2.3'
  port: '8080'
  path: 'mjpg/video.mjpg'
  user: ''
  password: ''
  detection:
    enabled: False

- name: cam_2
  description: Camera 2
  host: '192.168.1.50'
  port: '80'
  path: 'mjpg/video.mjpg'
  user: ''
  password: ''
  email:
    enabled: False
detection:
  min_area: 10
  update_reference_seconds: 3
  notify_seconds: 300
  frame_skip: 5
resize:
  x: 640
  y: 480
email:
  enabled: False
  smtp:
    server: ''
    port: 587
    user: ''
    password: ''
  subject: 'no motion on camera %CAMERA%'
  body: |
    no motion detected on camera %CAMERA%

    after running for %MOTION_SINCE% seconds, the camera reported no motion for %THRESHOLD%.

    please verify!
  from_address: ''
  to_address: ''
local_display:
  show_camera_feed: False
  show_threshold: False
  show_frame_delta: False

server:
  listen_address: '0.0.0.0'
  port: 8080
  frame_interval_seconds: 0.1
```

## build
build via `build.cmd` on windows with pyinstaller.
