import collections
import multiprocessing.pool
import os
import random
import re
import subprocess
import typing
import validators

import labels
from beauty import args
from labels import labels_created, write_labels, Label
from youtube import youtube_collections, youtube_playlists, youtube_video
from filters import visual_filter, visual_filter_cuts_base

class Video(typing.NamedTuple):
    url: str
    duration: float

videos = {}

def read_videos():
    youtube_collections(args.videos, 'video')
    youtube_playlists(args.videos)
    if labels_created() and args.increment:
        return
    if args.videos_max_number and len(args.videos) > args.videos_max_number:
        args.videos = random.sample(args.videos, args.videos_max_number)
    for l in labels.labels:
        if (l.input_url is not None and
            (os.path.isfile(l.input_url) or
            validators.url(l.input_url.replace('---', '-'))) and
            l.input_url not in args.videos):
            args.videos.append(l.input_url)
    if not args.videos:
        raise Exception('No video file names or video URLs given.')
    pool = multiprocessing.pool.ThreadPool(len(args.videos))
    result = [pool.apply_async(read_video, (v, False)) for v in args.videos]
    pool.close()
    pool.join()
    [r.get() for r in result]

def read_video(video_url, strict=True):
    if (validators.url(video_url) and
        'youtube.com' in video_url or 'youtu.be' in video_url):
        v = youtube_video(video_url, strict=strict)
        if not v:
            assert not strict
            return None
        videos[video_url] = Video(
            url=v[0],
            duration=v[1]
        )
    else:
        videos[video_url] = Video(
            url=video_url,
            duration=duration(video_url)
        )
    return videos[video_url]

def labels_from_video(video_url):
    video = read_video(video_url)
    points = [0]
    points.extend(
        visual_filter_cuts_base(
            Label(
                input_url=video_url,
                input_start_point=0,
                input_final_point=video.duration
            ),
            video.url))
    points.append(video.duration)
    p = [points[0]]
    points[1:-1] = [
        points[i] for i in range(1, len(points) - 1)
        if points[i] - p[0] >= args.labels_min_length and
            points[-1] - points[i] >= args.labels_min_length and
            not p.remove(p[0]) and not p.append(points[i])
    ]
    return [
        Label(
            output_start_point=points[i],
            output_final_point=points[i + 1]
        )
        for i in range(len(points) - 1)
    ]

def update_labels():
    pool_size = 1 if args.visual_filter_chrono else os.cpu_count()
    pool = multiprocessing.pool.Pool(pool_size)
    result = [
        pool.apply_async(check_label, (i,))
        for i in range(len(labels.labels))
    ]
    pool.close()
    pool.join()
    assert all(r.get() is None for r in result)

def check_label(n):
    retries = 0
    while True:
        label, label_changed = update_label(n)
        if not label_changed:
            break
        if args.increment:
            cache_input(label, n)
            duration = label.output_final_point - label.output_start_point
            cache_label = Label(
                output_start_point=label.output_start_point,
                output_final_point=label.output_final_point,
                input_url=args.cache % (n + 1),
                input_start_point=0,
                input_final_point=duration
            )
            cache_video = Video(
                url=args.cache % (n + 1),
                duration=duration
            )
            if visual_filter(cache_label, cache_video.url):
                labels.labels[n] = label
                break
        else:
            if visual_filter(label, videos[label.input_url].url):
                labels.labels[n] = label
                break
        retries += 1
        if retries >= args.visual_filter_retries:
            labels.labels[n] = label
            break
    if label_changed:
        write_labels()
    if args.increment and not os.path.isfile(args.cache % (n + 1)):
        cache_input(labels.labels[n], n)

def update_label(n):
    l = labels.labels[n]
    input_url = l.input_url if (
        l.input_url is not None and (
        os.path.isfile(l.input_url) or
        validators.url(l.input_url))) else (
        next_input_url(n))
    output_duration = l.output_final_point - l.output_start_point
    if type(l.input_start_point) is not list:
        input_duration = l.input_final_point - l.input_start_point
        input_start_point = l.input_start_point if (
            input_url is None or l.input_start_point >= 0) else (
            next_input_start_point(
                n,
                duration(input_url),
                output_duration))
        input_final_point = l.input_final_point if (
            input_url is None or
            l.input_start_point >= 0 and l.input_final_point >= 0 and
            abs(output_duration - input_duration) < 0.01) else (
            input_start_point + output_duration)
    else:
        if type(l.input_final_point) is not list:
            i = random.randint(0, len(l.input_start_point) - 1)
            input_start_point = l.input_start_point[i]
        else:
            assert len(l.input_start_point) == len(l.input_final_point)
            position = next_input_start_point(
                n, 
                sum(l.input_final_point[i] - l.input_start_point[i]
                    for i in range(len(l.input_start_point))
                    if l.input_final_point[i] - l.input_start_point[i] >=
                        output_duration),
                output_duration)
            for i in range(len(l.input_start_point)):
                input_duration = l.input_final_point[i] - l.input_start_point[i]
                if input_duration >= output_duration:
                    if position <= input_duration:
                        break
                    else:
                        position -= input_duration
            input_start_point = l.input_start_point[i] + position if (
                l.input_start_point[i] + position <
                    l.input_final_point[i] - output_duration) else (
                random.uniform(
                    l.input_start_point[i],
                    l.input_final_point[i] - output_duration))
        input_final_point = input_start_point + output_duration
    label_changed = (
        input_url != l.input_url or
        input_start_point != l.input_start_point or
        input_final_point != l.input_final_point)
    return Label(
        l.output_start_point,
        l.output_final_point,
        input_url,
        input_start_point,
        input_final_point
        ), label_changed

def next_input_url(n):
    if not videos:
        return None
    if args.visual_filter_chrono:
        return list(videos.keys())[n % len(videos)]
    else:
        V = [
            (url, video) for url, video in videos.items() if (
                labels.labels[n].input_url is None or
                re.match(labels.labels[n].input_url, url)
            )
        ]
        if not V:
            raise Exception(
                'Video not found for "%s".' % labels.labels[n].input_url)
        point = random.uniform(0, sum(v.duration for _, v in V))
        for url, video in V:
            point -= video.duration
            if point <= 0:
                break
        return url

def next_input_start_point(n, input_duration, output_duration):
    assert input_duration >= output_duration
    scope = (
        args.visual_filter_chrono_scope
            if args.visual_filter_chrono and args.visual_filter_chrono_scope
        else min(1.0, len(videos) / len(labels.labels))
            if args.visual_filter_chrono
        else 1.0)
    speed = (
        args.visual_filter_chrono_speed
        if args.visual_filter_chrono_speed else 1 / len(labels.labels))
    start = max(
        labels.labels[n - 1].output_final_point
            if args.visual_filter_chrono and
                n > 0 and
                labels.labels[n - 1].output_final_point != -1
            else 0,
        input_duration * (1 - scope) * speed * n % input_duration)
    final = min(
        start + input_duration * scope - output_duration,
        input_duration - output_duration)
    return random.uniform(start, final)

def cache_input(l: Label, n):
    if l.input_url not in videos:
        read_video(l.input_url)
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str(l.input_start_point),
        '-t', str(l.input_final_point - l.input_start_point +
            args.offset_increment),
        '-i', videos[l.input_url].url,
        '-c:v', 'libx264',
        *(['-crf', '17'] if args.output_quality == 'high' else
            ['-crf', '33'] if args.output_quality == 'low' else []),
        *(['-preset', 'slow'] if args.output_quality == 'high' else
            ['-preset', 'veryfast'] if args.output_quality == 'low' else []),
        *(['-tune', 'film'] if args.output_quality == 'high' else []),
        '-an',
        '-y', args.cache % (n + 1)
        ],
        check=True
    )

def property(video_url, stream, prop):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'format=%s' % prop,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        video_url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return float(process.stdout.decode())

def duration(video_url):
    if validators.url(video_url):
        if video_url not in videos:
            read_video(video_url)
        return videos[video_url].duration
    return property(video_url, 'v:0', 'duration')

def frames_number(video_url):
    return property(video_url, 'v:0', 'nb_frames')
