import cv2
import dlib
import os
import pytesseract
import subprocess
import sys
import tempfile

from beauty import args
from labels import Label

def visual_filter(label: Label, video):
    filters = [
        visual_filter_dark,
        visual_filter_cuts,
        visual_filter_pace,
        visual_filter_face,
        visual_filter_word
    ]
    filters = [f for f in filters if getattr(args, f.__name__)]
    if args.visual_filter_ordered:
        filters.sort(key=lambda f:
            sys.argv.index('--' + f.__name__.replace('_', '-')))
    for f in filters:
        if not f(label, video):
            return False
    return True

def visual_filter_base(label: Label, video, filter_expr, filter_func):
    process = subprocess.run([
        'ffmpeg',
        '-ss', str(label.input_start_point),
        '-to', str(label.input_final_point),
        '-i', video,
        '-vf', filter_expr,
        '-f', 'null',
        '-'
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return filter_func(process.stderr.decode())

def visual_filter_dark(label: Label, video):
    return visual_filter_base(
        label,
        video,
        'blackframe',
        lambda x: 'pblack:' not in x)

def visual_filter_cuts_base(label: Label, video):
    filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
        args.visual_filter_cuts_prob)
    def filter_func(x):
        return (float(s.split('pts_time:')[1].split()[0])
            for s in x.splitlines() if 'pts_time:' in s)
    return visual_filter_base(
        label,
        video,
        filter_expr,
        filter_func)

def visual_filter_cuts(label: Label, video):
    return next(iter(visual_filter_cuts_base(label, video)), None) is None

def visual_filter_pace(label: Label, video):
    filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
        args.visual_filter_pace_prob)
    def filter_func(x):
        fast_frames_number = x.count('pts_time:')
        return (
            (fast_frames_number / frames_number(video)
                >= args.visual_filter_pace_rate)
            == (args.visual_filter_pace == 'fast')
        )
    return visual_filter_base(
        label,
        video,
        filter_expr,
        filter_func)

def frame(label: Label, video, color):
    temp_file = tempfile.NamedTemporaryFile(suffix='.png')
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str((label.input_start_point + label.input_final_point) / 2),
        '-i', video,
        '-frames:v', str(1),
        '-vcodec', 'png',
        '-y', temp_file.name
        ],
        check=True
    )
    image = cv2.cvtColor(cv2.imread(temp_file.name), color)
    return image

def visual_filter_face(label: Label, video):
    return (
        bool(dlib.get_frontal_face_detector()(
            frame(label, video, cv2.COLOR_BGR2RGB)))
        == (args.visual_filter_face == 'include')
    )

def visual_filter_word(label: Label, video):
    image = frame(label, video, cv2.COLOR_BGR2GRAY)
    _, threshold = cv2.threshold(
        image,
        0,
        255,
        cv2.THRESH_OTSU | cv2.THRESH_BINARY_INV)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (18, 18))
    dilation = cv2.dilate(
        threshold,
        kernel,
        iterations=1)
    contours, _ = cv2.findContours(
        dilation,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE)
    text = None
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        text = pytesseract.image_to_string(image[y:y + h, x:x + w])
        if text:
            break
    return bool(text) == (args.visual_filter_word == 'include')
