import collections
import multiprocessing.pool
import os
import random
import subprocess
import validators

import labels
from beauty import args
from labels import labels_created, write_labels, Label
from youtube import youtube_collections, youtube_playlists, youtube_video

Video = collections.namedtuple('Video', '''
    url
    duration
    ''')
videos = {}

def read_videos():
    youtube_collections(args.videos, 'video')
    youtube_playlists(args.videos)
    if labels_created() and args.increment:
        return
    given_videos = args.videos
    while True:
        if args.videos_max_number and len(args.videos) > args.videos_max_number:
            args.videos = random.sample(args.videos, args.videos_max_number)
        for l in labels.labels:
            if (l.input_file_name is not None and
                l.input_file_name not in args.videos):
                args.videos.append(l.input_file_name)
        if not args.videos:
            raise Exception('No video file names or video URLs given.')
        pool = multiprocessing.pool.ThreadPool(len(args.videos))
        res = [pool.apply_async(read_video, (v, False)) for v in args.videos]
        pool.close()
        pool.join()
        assert all(r.get() is None for r in res)
        if all (v in videos for v in args.videos):
            break
        else:
            args.videos = given_videos

def read_video(video_file_name, strict=True):
    if (validators.url(video_file_name) and
        'youtube.com' in video_file_name or 'youtu.be' in video_file_name):
        v = youtube_video(video_file_name, strict=strict)
        if v is not None:
            videos[video_file_name] = Video(
                url=v[0],
                duration=v[1]
            )
    else:
        videos[video_file_name] = Video(
            url=video_file_name,
            duration=duration(video_file_name)
        )

def property(media_file_name, stream, prop):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'stream=%s' % prop,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        media_file_name
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return float(process.stdout.decode())

def duration(video_file_name):
    if validators.url(video_file_name):
        if video_file_name not in videos:
            read_video(video_file_name)
        return videos[video_file_name].duration
    return property(video_file_name, 'v:0', 'duration')

def frames_number(video_file_name):
    return property(video_file_name, 'v:0', 'nb_frames')

def create_labels_video():
    pool = multiprocessing.pool.Pool(os.cpu_count())
    res = [
        pool.apply_async(check_label_video, (i,))
        for i in range(len(labels.labels))
    ]
    pool.close()
    pool.join()
    assert all(r.get() is None for r in res)

def check_label_video(n):
    while True:
        label, label_changed = update_label_video(
            labels.labels[n], n / len(labels.labels))
        if not label_changed:
            break
        if args.increment:
            cache_input_video(label, n)
            duration = label.output_end_pos - label.output_start_pos
            cache_label = Label(
                output_start_pos=label.output_start_pos,
                output_end_pos=label.output_end_pos,
                input_file_name=args.cache % (n + 1),
                input_start_pos=0,
                input_end_pos=duration
            )
            cache_video = Video(
                url=args.cache % (n + 1),
                duration=duration
            )
            if visual_filter(cache_label, cache_video):
                labels.labels[n] = label
                break
        else:
            if visual_filter(label, videos[label.input_file_name]):
                labels.labels[n] = label
                break
    if label_changed:
        write_labels()
    if args.increment and not os.path.isfile(args.cache % (n + 1)):
        cache_input_video(labels.labels[n], n)

def update_label_video(l: Label, progress):
    input_file_name = l.input_file_name if (
        l.input_file_name is not None) else (
        next_input_video_file_name(progress))
    input_start_pos = l.input_start_pos if (
        input_file_name is None or l.input_start_pos >= 0) else (
        next_input_video_start_pos(
            duration(input_file_name),
            l.output_end_pos - l.output_start_pos,
            progress))
    input_end_pos = l.input_end_pos if (
        input_file_name is None or
        l.input_start_pos >= 0 and l.input_end_pos >= 0) else (
        input_start_pos + (l.output_end_pos - l.output_start_pos))
    label_changed = (
        input_file_name != l.input_file_name or
        input_start_pos != l.input_start_pos or
        input_end_pos != l.input_end_pos)
    return Label(
        l.output_start_pos,
        l.output_end_pos,
        input_file_name,
        input_start_pos,
        input_end_pos
        ), label_changed

def next_input_video_file_name(progress):
    if not videos:
        return None
    pos = random.uniform(0, sum([v.duration for _, v in videos.items()]))
    for file_name, video in videos.items():
        pos -= video.duration
        if pos < 0:
            break
    return file_name

def next_input_video_start_pos(input_duration, output_duration, progress):
    scope = (min(1.0, len(videos) / len(labels.labels))
        if args.visual_filter_chrono else 1.0)
    return (
        input_duration * (1 - scope) * progress +
        random.uniform(0, input_duration * scope - output_duration)
    )

def cache_input_video(l: Label, n):
    if l.input_file_name not in videos:
        read_video(l.input_file_name)
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str(l.input_start_pos),
        '-t', str(l.input_end_pos - l.input_start_pos +
            args.offset_increment),
        '-i', videos[l.input_file_name].url,
        '-filter_complex', 'concat=n=1',
        '-an',
        '-y', args.cache % (n + 1)
        ],
        check=True
    )

def visual_filter(l: Label, v: Video):
    if args.visual_filter_drop_face_less:
        if not visual_filter_face_less(l, v):
            return False
    if args.visual_filter_drop_black_frame:
        if not visual_filter_black_frame(l, v):
            return False
    if args.visual_filter_drop_hard_cuts:
        if not visual_filter_hard_cuts(l, v):
            return False
    if args.visual_filter_drop_slow_pace:
        if not visual_filter_slow_pace(l, v):
            return False
    return True

def visual_filter_base(l: Label, v: Video, filter_expr, filter_func):
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str(l.input_start_pos),
        '-t', str(l.input_end_pos - l.input_start_pos),
        '-i', v.url,
        '-vf', filter_expr,
        '-f', 'null',
        '-'
        ],
        check=True,
        stderr=subprocess.PIPE
    )
    return filter_func(process.stderr.decode())

def visual_filter_black_frame(l: Label, v: Video):
    visual_filter_base(l, v, 'blackframe', lambda x: 'pblack:' not in x)

def visual_filter_hard_cuts(l: Label, v: Video):
    filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
        args.visual_filter_drop_hard_cuts_prob)
    visual_filter_base(l, v, filter_expr, lambda x: 'pts_time:' not in x)

def visual_filter_slow_pace(l: Label, v: Video):
    filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
        args.visual_filter_drop_slow_pace_prob)
    def filter_func(x):
        fast_frames_number = x.count('pts_time:')
        return (fast_frames_number / frames_number(v.url)
            >= args.visual_filter_drop_slow_pace_rate)
    visual_filter_base(l, v, filter_expr, filter_func)

def visual_filter_face_less(l: Label, v: Video):
    _, frame_file_name = tempfile.mkstemp(suffix='.png')
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str((l.input_start_pos + l.input_end_pos) / 2),
        '-i', v.url,
        '-frames:v', str(1),
        '-vcodec', 'png',
        '-y', frame_file_name
        ],
        check=True
    )
    frame = cv2.cvtColor(cv2.imread(frame_file_name), cv2.COLOR_BGR2RGB)
    os.remove(frame_file_name)
    return not not dlib.get_frontal_face_detector()(frame)

def visual_effects():
    effects = []
    if args.visual_effect_speedup:
        effects.append(visual_effects_speedup)
    if args.visual_effect_zooming:
        effects.append(visual_effects_zooming)
    filters = []
    mappers = []
    for e in effects:
        filter, mapper = e()
        filters.append(filter)
        mappers.append(mapper)
    return filters, mappers

def visual_effects_speedup():
    audio_tempo = (tempo(args.audio_output) *
        args.visual_effect_speedup_tempo_multi)
    def f(x, p, y):
        x0 = x * p + math.pi / 2
        return (2 * (x0 - x0 % math.pi) / math.pi
            - math.cos(x0 % math.pi)) / p - y
    warnings.filterwarnings(
        'ignore', 'The iteration is not making good progress')
    def fx(p, y):
        return f(math.pi / p, p, y)
    p = scipy.optimize.fsolve(functools.partial(fx, y=audio_tempo), 1)[0]
    filter = 'setpts=\'' \
        '(2 * (T * %.3f + PI / 2 - mod(T * %.3f + PI / 2, PI)) / PI' \
        '- cos(mod(T * %.3f + PI / 2, PI))) / %.3f / TB\'' % tuple([p] * 4)
    def mapper(y):
        return scipy.optimize.fsolve(functools.partial(f, p=p, y=y), y)[0]
    return filter, mapper

def visual_effects_zooming():
    return '', lambda x: x
