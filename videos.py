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
from filters import visual_filter, visual_filter_hard_cuts_base

class Video(typing.NamedTuple):
    url: str
    duration: float

videos = {}

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

def read_videos():
    youtube_collections(args.videos, 'video')
    youtube_playlists(args.videos)
    if labels_created() and args.increment:
        return
    if args.videos_max_number and len(args.videos) > args.videos_max_number:
        args.videos = random.sample(args.videos, args.videos_max_number)
    for l in labels.labels:
        if (l.input_file_name is not None and
            (os.path.isfile(l.input_file_name) or
            validators.url(l.input_file_name.replace('---', '-'))) and
            l.input_file_name not in args.videos):
            args.videos.append(l.input_file_name)
    if not args.videos:
        raise Exception('No video file names or video URLs given.')
    pool = multiprocessing.pool.ThreadPool(len(args.videos))
    result = [pool.apply_async(read_video, (v, False)) for v in args.videos]
    pool.close()
    pool.join()
    assert all(r.get() is not None for r in result)
    if not all (v in videos for v in args.videos):
        raise Exception('Not all videos have been read.')

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
    return videos[video_file_name]

def create_labels():
    labels = []
    for video_file_name in args.videos:
        video = read_video(video_file_name)
        positions = [0]
        positions.extend(
            visual_filter_hard_cuts_base(
                Label(
                    input_file_name=video_file_name,
                    input_start_pos=0,
                    input_end_pos=video.duration
                ),
                video.url))
        positions.append(video.duration)
        labels.append(Label(
            output_start_pos=0,
            output_end_pos=0,
            input_file_name=video_file_name,
            input_start_pos=positions[:-1],
            input_end_pos=positions[1:]))
    return labels

def update_labels():
    pool = multiprocessing.pool.Pool(os.cpu_count())
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
            if visual_filter(cache_label, cache_video.url):
                labels.labels[n] = label
                break
        else:
            if visual_filter(label, videos[label.input_file_name].url):
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
    input_file_name = l.input_file_name if (
        l.input_file_name is not None and (
        os.path.isfile(l.input_file_name) or
        validators.url(l.input_file_name))) else (
        next_input_file_name(n))
    output_duration = l.output_end_pos - l.output_start_pos
    if type(l.input_start_pos) is not list:
        input_duration = l.input_end_pos - l.input_start_pos
        input_start_pos = l.input_start_pos if (
            input_file_name is None or l.input_start_pos >= 0) else (
            next_input_start_pos(
                n,
                duration(input_file_name),
                output_duration))
        input_end_pos = l.input_end_pos if (
            input_file_name is None or
            l.input_start_pos >= 0 and l.input_end_pos >= 0 and
            abs(output_duration - input_duration) < 0.01) else (
            input_start_pos + output_duration)
    else:
        if type(l.input_end_pos) is not list:
            i = random.randint(0, len(l.input_start_pos) - 1)
            input_start_pos = l.input_start_pos[i]
        else:
            assert len(l.input_start_pos) == len(l.input_end_pos)
            position = next_input_start_pos(
                n, 
                sum(l.input_end_pos[i] - l.input_start_pos[i]
                    for i in range(len(l.input_start_pos))
                    if l.input_end_pos[i] - l.input_start_pos[i] >=
                        output_duration),
                output_duration)
            for i in range(len(l.input_start_pos)):
                if (l.input_end_pos[i] - l.input_start_pos[i] >=
                    output_duration):
                    position -= l.input_end_pos[i] - l.input_start_pos[i]
                    if position <= 0:
                        break
            input_start_pos = l.input_start_pos[i] + next_input_start_pos(
                n,
                l.input_end_pos[i] - l.input_start_pos[i],
                output_duration)
        input_end_pos = input_start_pos + output_duration
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

def next_input_file_name(n):
    if not videos:
        return None
    if args.visual_filter_chrono:
        return list(videos.keys())[n % len(videos)]
    else:
        V = [
            (file_name, video) for file_name, video in videos.items() if (
                labels.labels[n].input_file_name is None or
                re.match(labels.labels[n].input_file_name, file_name)
            )
        ]
        if not V:
            raise Exception(
                'Video not found for "%s".' % labels.labels[n].input_file_name)
        position = random.uniform(0, sum(v.duration for _, v in V))
        for file_name, video in V:
            position -= video.duration
            if position <= 0:
                break
        return file_name

def next_input_start_pos(n, input_duration, output_duration):
    scope = (min(1.0, len(videos) / len(labels.labels))
        if args.visual_filter_chrono else 1.0)
    return (
        input_duration * (1 - scope) * n / len(labels.labels) +
        random.uniform(0, input_duration * scope - output_duration)
    )

def cache_input(l: Label, n):
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
