import os
import random
import re
import subprocess
import urllib.parse
import validators

from . import args
from .mappings import (
    parse_timestamp,
    read_subtitles
)

def youtube_collections(items, type):
    def process(items, collections):
        if not items:
            items[:] = random.sample(
                list(collections.values()), 1
                )[0]
            if items[0][0:2] == 'PL':
                items[0] = youtube_playlist_url(items[0])
            youtube_collections(items, type)
        else:
            for item in list(items):
                if item == 'any':
                    items.remove(item)
                    item = random.sample(
                        list(collections.keys()), 1
                        )[0]
                if item in collections:
                    if type == 'audio':
                        ids = random.sample(
                            collections[item], 1
                        )
                    elif type == 'video':
                        ids = collections[item]
                    for id in ids:
                        if id[0:2] == 'PL':
                            items.append(
                                youtube_playlist_url(id)
                            )
                        else:
                            items.append(
                                youtube_video_url(id)
                            )
                    if item in items:
                        items.remove(item)
    if type == 'audio':
        audios = {
            'orchestral': [
                'PL659KIPAkeqgZtrIadb7YXGlFJBqZp9SX'
            ],
            'electronic': [
                'PL659KIPAkeqjudXxn0pEdDIl4nAWRqFuV'
            ],
            'atmospheric': [
                'PL659KIPAkeqijzchDUC_kOjTD5k9RXhaY'
            ],
            'subtitled': [
                'Ax_GJvCbGRc',
                'u0-iGVgBaYs',
                'thlW3tjec9I',
                'QWsQo9ZPtog',
                '4aDSKgFmJ2k',
                'xZYkr-Bca_Y',
                'TEr4vO_ICEg',
                'dbGqN66jv6s',
                'TDn_QuSF4E0',
                'LrPFtOAJQYw'
            ]
        }
        process(items, audios)
    if type == 'video':
        videos = {
            'flowers': [
                '4RCPqdTgf24',
                'nvEGRN-C1oY',
                'HJaM5JtYYGw',
                'CV2P-xsEiYE'
            ],
            'nightsky': [
                'L71nt62ddPk',
                'aE2lFmRbs4Y',
                'rSWqY5XOKcs',
                'jQWSjB95TX8',
                'MFRPJRcf2M4'
            ],
            'slow-mo': [
                'zrPphZ4WJxc'
            ]
        }
        process(items, videos)

def youtube_playlists(items):
    for item in list(items):
        if (validators.url(item) and
            'youtube.com/playlist' in item or
            item.startswith('ytsearch') or
            item.startswith('ytdl://ytsearch')
        ):
            items.remove(item)
            if item.startswith('ytdl://ytsearch'):
                item = item[7:]
            items.extend(youtube_playlist(item))

def youtube_playlist(url):
    process = subprocess.run([
        'yt-dlp',
        '--quiet',
        '--no-warnings',
        '--get-title',
        '--get-id',
        '--flat-playlist',
        url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    output = process.stdout.decode().splitlines()
    return [
        'http://youtu.be/' + id
        for (title, id) in zip(*[iter(output)] * 2)
            if (not url.startswith('ytsearch') or
                all (word.lower() in title.lower()
                    for word in
                        url[url.index(':') + 1:].split()
                )
            )
    ]

def youtube_playlist_url(id):
    return 'https://youtube.com/playlist?list=%s' % id

def youtube_video(
    url,
    filter='bestvideo' +
        (f'[ext={args.videos_format}]'
            if args.videos_format else '') +
        (f'[width={args.videos_width}]'
            if args.videos_width else '') +
        (f'[height={args.videos_height}]'
            if args.videos_height else ''),
    strict=True):
    try:
        process = subprocess.run([
            'yt-dlp',
            '--quiet',
            '--no-warnings',
            '--get-url',
            '--get-duration',
            '-f', filter,
            '--youtube-skip-dash-manifest',
            url
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        if not strict:
            if any (m in e.stderr.decode() for m in [
                'This video',
                'requested format not available',
                'YouTube said:'
            ]):
                return None
        raise e
    output = process.stdout.decode().splitlines()
    variants = [
        (url, parse_timestamp(duration))
        for (url, duration) in zip(*[iter(output)] * 2)
            if youtube_check_video(url)
    ]
    if strict and not variants:
        raise Exception('Can\'t read "%s".' % url)
    return variants[0] if variants else None

def youtube_check_video(url):
    process = subprocess.run([
        'ffprobe',
        '-v', 'quiet',
        url
        ],
        check=False
    )
    return process.returncode == 0

def youtube_video_url(id):
    return 'https://youtu.be/%s' % id

def youtube_video_id(url):
    if not validators.url(url):
        raise Exception('Video URL "%s" is not valid.' % url)
    o = urllib.parse.urlparse(url)
    if o.netloc == 'youtu.be':
        return o.path[1:]
    elif o.netloc in ('www.youtube.com', 'youtube.com'):
        if o.path == '/watch':
            index = o.query.index('v=')
            return o.query[index + 2:index + 13]
        elif o.path[:7] == '/embed/':
            return o.path.split('/')[2]
        elif o.path[:3] == '/v/':
            return o.path.split('/')[2]
    return None

def mappings_from_subs(url):
    video_id = youtube_video_id(url)
    process = subprocess.run([
        'yt-dlp',
        '--quiet',
        '--no-warnings',
        '--write-sub',
        '--sub-lang', 'en',
        '--skip-download',
        url,
        '-o',
        video_id
        ],
        check=True,
        stderr=subprocess.PIPE
    )
    errors = process.stderr.decode().splitlines()
    if 'WARNING: video doesn\'t have subtitles' in errors:
        return []
    subtitles = "%s.en.vtt" % video_id
    mappings = read_subtitles(subtitles)
    os.remove(subtitles)
    return mappings
