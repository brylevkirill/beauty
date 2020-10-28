import cv2
import dlib
import os
import subprocess
import tempfile

from beauty import args
from labels import Label

def visual_filter(label: Label, video):
    if args.visual_filter_face:
        if not visual_filter_face(label, video):
            return False
    if args.visual_filter_dark:
        if not visual_filter_dark(label, video):
            return False
    if args.visual_filter_cuts:
        if not visual_filter_cuts(label, video):
            return False
    if args.visual_filter_pace:
        if not visual_filter_pace(label, video):
            return False
    return True

def visual_filter_base(label: Label, video, filter_expr, filter_func):
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
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

def visual_filter_face(label: Label, video):
    _, frame_file_name = tempfile.mkstemp(suffix='.png')
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str((label.input_start_point + label.input_final_point) / 2),
        '-i', video,
        '-frames:v', str(1),
        '-vcodec', 'png',
        '-y', frame_file_name
        ],
        check=True
    )
    frame = cv2.cvtColor(cv2.imread(frame_file_name), cv2.COLOR_BGR2RGB)
    os.remove(frame_file_name)
    return (
        bool(dlib.get_frontal_face_detector()(frame))
        == (args.visual_filter_face == 'include')
    )
