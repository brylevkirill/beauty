import collections
import multiprocessing.pool
import os
import random
import re
import subprocess
import sys
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
    for label in labels.labels:
        if (label.input is not None and
            (os.path.isfile(label.input) or
            validators.url(label.input.replace('---', '-'))) and
            label.input not in args.videos):
            args.videos.append(label.input)
    if not args.videos:
        raise Exception('No video file names or URLs given.')
    pool = multiprocessing.pool.ThreadPool(len(args.videos))
    result = [pool.apply_async(read_video, (v, False)) for v in args.videos]
    pool.close()
    pool.join()
    [r.get() for r in result]

def read_video(url, strict=True):
    if (validators.url(url) and
        'youtube.com' in url or 'youtu.be' in url):
        v = youtube_video(url, strict=strict)
        if not v:
            assert not strict
            return None
        videos[url] = Video(
            url=v[0],
            duration=v[1]
        )
    else:
        videos[url] = Video(
            url=url,
            duration=duration(url)
        )
    return videos[url]

def labels_from_video(url):
    video = read_video(url)
    points = [0]
    points.extend(
        visual_filter_cuts_base(
            Label(
                input=url,
                input_start=0,
                input_final=video.duration
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
            start=points[i],
            final=points[i + 1]
        )
        for i in range(len(points) - 1)
    ]

def create_labels():
    pool = multiprocessing.pool.Pool(args.visual_filter_threads)
    result = [
        pool.apply_async(create_label, (n,))
        for n in range(len(labels.labels))
    ]
    pool.close()
    pool.join()
    return [r.get() for r in result]

def create_label(n):
    random.seed(n + random.randint(0, sys.maxsize))
    retries = args.visual_filter_retries
    while True:
        label, label_updated = update_label(n)
        if not label_updated:
            break
        if args.increment:
            cache_input(label, n)
            duration = label.final - label.start
            cache_label = Label(
                start=label.start,
                final=label.final,
                input=args.video_cache % (n + 1),
                input_start=0,
                input_final=duration
            )
            cache_video = Video(
                url=args.video_cache % (n + 1),
                duration=duration
            )
            accept = visual_filter(cache_label, cache_video.url)
        else:
            accept = visual_filter(label, videos[label.input].url)
        if accept or retries == 0:
            labels.labels[n] = label
            break
        retries -= 1
    if label_updated:
        write_labels()
    if args.increment and not os.path.isfile(args.video_cache % (n + 1)):
        cache_input(label, n)
    return label

def update_label(n):
    label = labels.labels[n]
    if label.input is None or label.input_start == -1:
        input, input_start, input_final = next_input(n)
    else:
        output_duration = label.final - label.start
        input, input_start, input_final = (
            label.input,
            label.input_start,
            label.input_start + output_duration
        )
    label_updated = (
        input != label.input or
        input_start != label.input_start or
        input_final != label.input_final
    )
    return Label(
        label.start,
        label.final,
        input,
        input_start,
        input_final
        ), label_updated

def next_input(n):
    if not videos:
        return None, None, None
    label = labels.labels[n]
    V = [
        (input, video) for input, video in sorted(
            videos.items(),
            key=lambda x: list(args.inputs.keys()).index(x[0])) if (
                label.input is None or re.match(label.input, input)
        )
    ]
    if not V:
        raise Exception('Video not found for "%s".' % label.input)
    inputs_duration = sum(duration(input) for input, _ in V)
    output_duration = label.final - label.start
    assert inputs_duration >= output_duration
    if args.visual_filter_chrono:
        point = inputs_duration * n / len(labels.labels)
    else:
        point = random.uniform(0, inputs_duration)
    for input, _ in V:
        input_duration = duration(input)
        if point <= input_duration:
            break
        point -= input_duration
    scope = (
        args.visual_filter_chrono_scope
            if args.visual_filter_chrono_scope
        else min(1,
            1 / (len(labels.labels) * input_duration / inputs_duration) *
                args.visual_filter_chrono_scope_factor)
            if args.visual_filter_chrono
        else 1
    )
    delta = 0.5 * max(scope * input_duration, output_duration)
    last_label = labels.labels[n - 1] if n > 0 else None
    start = (
        last_label.final
        if args.visual_filter_chrono_serial and
            last_label and
            last_label.input == input and
            last_label.final != -1
        else 0
    )
    point = random.uniform(
        max(start, point - delta),
        max(start, min(point + delta, input_duration) - output_duration)
    )
    if input in args.inputs:
        for start, final in args.inputs[input]:
            if point < final - start:
                point = min(start + point, final - output_duration)
                break
            point -= final - start
    return input, point, point + output_duration

def cache_input(label: Label, n):
    if label.input not in videos:
        read_video(label.input)
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', str(label.input_start),
        '-t', str(label.input_final -
            label.input_start +
            args.increment_offset),
        '-i', videos[label.input].url,
        '-codec:v', 'libx264',
        *(['-crf', '17'] if args.output_quality == 'high' else
            ['-crf', '33'] if args.output_quality == 'low' else []),
        *(['-preset', 'slow'] if args.output_quality == 'high' else
            ['-preset', 'veryfast'] if args.output_quality == 'low' else []),
        *(['-tune', 'film'] if args.output_quality == 'high' else []),
        '-an',
        '-y', args.video_cache % (n + 1)
        ],
        check=True
    )

def property(url, stream, name):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'format=%s' % name,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return float(process.stdout.decode())

def duration(url):
    if url in args.inputs:
        return sum((final - start) for start, final in args.inputs[url])
    if validators.url(url):
        if url not in videos:
            read_video(url)
        return videos[url].duration
    return property(url, 'v:0', 'duration')

def frames_number(url):
    return property(url, 'v:0', 'nb_frames')

def frames_rate(url):
    return eval(property(url, 'v:0', 'r_frame_rate'))
