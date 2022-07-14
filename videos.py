import multiprocessing.pool
import os
import random
import re
import subprocess
import sys
import typing
import validators

import beauty.mappings as mappings
from . import args
from .filters import (
    visual_filter,
    visual_filter_cuts_base
)
from .mappings import (
    mappings_complete,
    Mapping,
    Resource
)
from .youtube import (
    youtube_collections,
    youtube_playlists,
    youtube_video
)

class Video(typing.NamedTuple):
    url: str
    duration: float

videos = {}

def read():
    youtube_collections(args.videos, 'video')
    youtube_playlists(args.videos)
    if mappings_complete() and args.increment:
        return
    if args.videos_number and \
        len(args.videos) > args.videos_number:
        args.videos = random.sample(
            args.videos,
            args.videos_number
        )
    for mapping in mappings.mappings:
        if (mapping.source is not None and
            mapping.source.url is not None and
            (os.path.isfile(mapping.source.url) or
                validators.url(
                    mapping.source.url.replace('---', '-')
                )
            ) and mapping.source.url not in args.videos):
            args.videos.append(mapping.source.url)
    if not args.videos:
        raise Exception('No video file names or URLs given.')
    pool = multiprocessing.pool.ThreadPool(len(args.videos))
    result = [
        pool.apply_async(read_video, (v, False))
        for v in args.videos
    ]
    pool.close()
    pool.join()
    [r.get() for r in result]
    return args.videos

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

def mappings_from_cuts(url):
    video = read_video(url)
    points = [0]
    points.extend(
        visual_filter_cuts_base(
            Mapping(
                source=Resource(
                    start=0,
                    final=video.duration
                )
            ),
            video.url))
    points.append(video.duration)
    p = [points[0]]
    points[1:-1] = [
        points[i]
        for i in range(1, len(points) - 1)
            if points[i] - p[0] >= \
                args.mappings_min_interval and
                points[-1] - points[i] >= \
                    args.mappings_min_interval and
                not p.remove(p[0]) and
                not p.append(points[i])
    ]
    return [
        Mapping(
            source=Resource(
                url = url,
                start=points[i],
                final=points[i + 1]
            ),
            target=Resource(
                url = url,
                start=points[i],
                final=points[i + 1]
            )
        )
        for i in range(len(points) - 1)
    ]

def generate_mappings():
    pool = multiprocessing.pool.Pool(
        args.visual_filter_threads
    )
    result = [
        pool.apply_async(generate_mapping, (idx,))
        for idx in range(len(mappings.mappings))
    ]
    pool.close()
    pool.join()
    return [r.get() for r in result]

def generate_mapping(idx):
    random.seed(idx + random.randint(0, sys.maxsize))
    retries = args.visual_filter_retries
    while True:
        mapping, mapping_updated = update_mapping(idx)
        if args.increment:
            cache_file_name = args.video_cache % (idx + 1)
            if mapping_updated or \
                not os.path.isfile(cache_file_name):
                cache_input(mapping, idx)
        if not mapping_updated:
            break
        if args.increment:
            duration = mapping.target.final - \
                mapping.target.start
            cache_mapping = Mapping(
                source=Resource(
                    url=cache_file_name,
                    start=0,
                    final=duration
                ),
                target=Resource(
                    start=mapping.target.start,
                    final=mapping.target.final
                )
            )
            accept = visual_filter(
                cache_mapping,
                cache_file_name
            )
        else:
            accept = visual_filter(
                mapping,
                videos[mapping.source.url].url
            )
        if accept or retries == 0:
            mappings.mappings[idx] = mapping
            mappings.write()
            break
        retries -= 1
    return mapping

def update_mapping(idx):
    mapping = mappings.mappings[idx]
    if (mapping.source is None or
        mapping.source.url is None or
        mapping.source.start == -1):
        input, input_start, input_final = next_input(idx)
    else:
        output_duration = \
            mapping.target.final - mapping.target.start
        input, input_start, input_final = (
            mapping.source.url,
            mapping.source.start,
            mapping.source.start + output_duration
        )
    mapping_updated = (
        mapping.source is None or
        input != mapping.source.url or
        input_start != mapping.source.start or
        input_final != mapping.source.final
    )
    return Mapping(
        source=Resource(
            url=input,
            start=input_start,
            final=input_final
        ),
        target=mapping.target
        ), mapping_updated

def next_input(idx):
    mapping = mappings.mappings[idx]
    inputs = [
        input
        for input in sorted(
            videos.keys(),
            key=lambda v:
                (list(args.inputs.keys()) + [v[0]]). \
                    index(v[0])
        ) if (
            mapping.source is None or
            mapping.source.url is None or
            re.match(mapping.source.url, input)
        )
    ]
    if not inputs:
        raise Exception(
            'Video not found for "%s".' % mapping.source.url
        )
    def complete_duration(input):
        if input in args.inputs:
            return sum((
                (final if final != -1 else duration(input)) -
                (start if start != -1 else 0)
                ) for start, final in args.inputs[input]
            )
        else:
            return duration(input)
    inputs_duration = sum(
        complete_duration(input) for input in inputs
    )
    output_duration = \
        mapping.target.final - mapping.target.start
    assert inputs_duration >= output_duration
    point = (
        idx / len(mappings.mappings) *
        args.visual_filter_chrono_speed *
        inputs_duration % inputs_duration
        ) if args.visual_filter_chrono else (
            random.uniform(0, inputs_duration)
    )
    for input in inputs:
        input_duration = complete_duration(input)
        if point <= input_duration:
            break
        point -= input_duration
    delta = 0.5 * max(
        input_duration * 
        min(1,
            inputs_duration / input_duration /
            len(mappings.mappings) *
            args.visual_filter_chrono_scope
        ) if args.visual_filter_chrono else input_duration,
        output_duration
    )
    point = random.uniform(
        max(0, point - delta),
        max(0,
            min(point + delta, input_duration) - \
                output_duration
        )
    )
    if input in args.inputs:
        for start, final in args.inputs[input]:
            if start == -1:
                start = 0
            if final == -1:
                final = duration(input)
            if point < final - start:
                point = min(
                    start + point,
                    final - output_duration
                )
                break
            point -= final - start
    return input, point, point + output_duration

def cache_input(mapping: Mapping, idx):
    if mapping.source.url not in videos:
        read_video(mapping.source.url)
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-ss', '{:.3f}'.format(mapping.source.start),
        '-t', '{:.3f}'.format(
            mapping.source.final -
            mapping.source.start +
            args.increment_offset),
        '-i', videos[mapping.source.url].url,
        '-codec:v', 'libx264',
        *(['-crf', '17']
            if args.output_quality == 'high'
            else ['-crf', '33']
                if args.output_quality == 'low'
            else []),
        *(['-preset', 'slow']
            if args.output_quality == 'high'
            else ['-preset', 'veryfast']
                if args.output_quality == 'low'
            else []),
        '-an',
        '-y', args.video_cache % (idx + 1)
        ],
        check=True
    )

def property(url, stream, name):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'stream=%s' % name,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return process.stdout.decode()

def duration(url):
    if validators.url(url):
        if url not in videos:
            read_video(url)
        return videos[url].duration
    return float(property(url, 'v:0', 'duration'))

def frames_number(url):
    return int(property(url, 'v:0', 'nb_frames'))

def frames_rate(url):
    return float(eval(property(url, 'v:0', 'r_frame_rate')))
