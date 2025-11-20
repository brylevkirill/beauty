import subprocess
import sys

from . import args
from .mappings import Mapping

def visual_filter(mapping: Mapping, video):
    filters = [
        visual_filter_pace,
        visual_filter_cuts,
        visual_filter_dark,
        visual_filter_face,
        visual_filter_word
    ]
    filters = [
        f for f in filters
            if getattr(args, f.__name__)
    ]
    if args.visual_filter_ordered:
        filters.sort(
            key=lambda f:
                sys.argv.index(
                    '--' + f.__name__
                        .replace('_', '-')
                )
        )
    for f in filters:
        if not f(mapping, video):
            return False
    return True

def visual_filter_base(
    mapping: Mapping,
    video,
    expr,
    func
):
    proc = subprocess.run([
        *args.ffmpeg,
        '-ss', str(mapping.source.start),
        '-to', str(mapping.source.final),
        '-i', video,
        '-vf', expr,
        '-f', 'null',
        '-'
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return func(proc.stderr.decode())

def visual_filter_pace(mapping: Mapping, video):
    expr = \
        'select=\'gt(scene,{})\',showinfo' \
            .format(
                args.visual_filter_pace_prob
            )
    def func(x):
        _frames_number = x.count('pts_time:')
        return (
            _frames_number /
                frames_number(video) >=
                    args.visual_filter_pace_rate
            ) == (
                args.visual_filter_pace == 'fast'
            )
    return visual_filter_base(
        mapping,
        video,
        expr,
        func
    )

def visual_filter_cuts_base(
    mapping: Mapping, video
):
    expr = \
        'select=\'gt(scene,{})\',showinfo' \
            .format(
                args.visual_filter_cuts_prob
            )
    def func(x):
        return (
            float(
                s.split('pts_time:')[1]
                    .split()[0]
            ) for s in x.splitlines()
                if 'pts_time:' in s
        )
    return visual_filter_base(
        mapping,
        video,
        expr,
        func
    )

def visual_filter_cuts(mapping: Mapping, video):
    cuts = \
        next(iter(
            visual_filter_base(
                mapping, video
            )), None
        )
    return bool(cuts) == (
        args.visual_filter_cuts == 'include'
    )

def visual_filter_dark(mapping: Mapping, video):
    dark = \
        visual_filter_base(
            mapping,
            video,
            'blackframe',
            lambda x: 'pblack:' in x
        )
    return bool(dark) == (
        args.visual_filter_dark == 'include'
    )

def frame(mapping: Mapping, video, color):
    import cv2, tempfile
    temp_file = \
        tempfile.NamedTemporaryFile(
            suffix='.png'
        )
    subprocess.run([
        *args.ffmpeg,
        '-loglevel', args.loglevel,
        '-ss', str(
            (mapping.source.start +
                mapping.source.final) / 2
        ),
        '-i', video,
        '-frames:v', str(1),
        '-vcodec', 'png',
        '-y', temp_file.name
        ],
        check=True
    )
    image = \
        cv2.cvtColor(
            cv2.imread(
                temp_file.name
                ), color
        )
    temp_file.close()
    return image

def visual_filter_face(mapping: Mapping, video):
    import cv2, dlib
    face = \
        dlib.get_frontal_face_detector()(
            frame(
                mapping,
                video,
                cv2.COLOR_BGR2RGB
            )
        )
    return bool(face) == (
        args.visual_filter_face == 'include'
    )

def visual_filter_word(mapping: Mapping, video):
    import cv2, pytesseract
    image = \
        frame(
            mapping,
            video,
            cv2.COLOR_BGR2GRAY
        )
    _, threshold = \
        cv2.threshold(
            image,
            0,
            255,
            cv2.THRESH_OTSU |
                cv2.THRESH_BINARY_INV
        )
    kernel = \
        cv2.getStructuringElement(
            cv2.MORPH_RECT, (18, 18)
        )
    dilation = \
        cv2.dilate(
            threshold,
            kernel,
            iterations=1
        )
    contours, _ = \
        cv2.findContours(
            dilation,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE
        )
    text = None
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        text = \
            pytesseract.image_to_string(
                image[y:y+h, x:x+w]
            )
        if text:
            break
    return bool(text) == (
        args.visual_filter_word == 'include'
    )
