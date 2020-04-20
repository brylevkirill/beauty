import os
import random
import subprocess
import urllib.parse
import validators

from beauty import args
from labels import parse_timestamp, read_subtitles

def youtube_collections(items, type):
    def process(items, collections):
        if not items:
            if args.labels_public:
                items.append('with labels')
            else:
                items.append('collection')
            youtube_collections(items, type)
        else:
            for item in list(items):
                if item in collections:
                    id = random.sample(collections[item], 1)[0]
                    if id[0:2] == 'PL':
                        items.append(youtube_playlist_url(id))
                    else:
                        items.append(youtube_video_url(id))
                    items.remove(item)
    if type == 'audio':
        audios = {
            'collection': ['PL659KIPAkeqgZtrIadb7YXGlFJBqZp9SX'],
            'electronic': ['PL659KIPAkeqgZhtIQKazFHTUaL5gXNLqD'],
            'with labels': [
                'uLbmXLJm6Kk',
                'javS-iqjMcY',
                'PxogNHnvP_k',
                'g85UfdZoyeg',
                'QWsQo9ZPtog',
                'yzeclFG_ke0'
            ]
        }
        process(items, audios)
    if type == 'video':
        videos = {
            'night sky': ['PL659KIPAkeqhsK80VGeiQ4g06mdYcJxt7'],
            'flowers': ['PL659KIPAkeqj_VlAKEuFRpHvCkl-03Fw1'],
            'girls': ['PL659KIPAkeqjaerr91OSBWPHRFbkY5jaD']
        }
        process(items, videos)

def youtube_playlists(items):
    for item in list(items):
        if (validators.url(item) and 'youtube.com/playlist' in item or
            item.startswith('ytsearch') or
            item.startswith('ytdl://ytsearch')
        ):
            items.remove(item)
            if item.startswith('ytdl://ytsearch'):
                item = item[7:]
            items.extend(youtube_playlist(item))

def youtube_playlist(url):
    process = subprocess.run([
        'youtube-dl',
        '--quiet',
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
                for word in url[url.index(':') + 1:].split()
        )
        )
    ]

def youtube_playlist_url(id):
    return 'https://youtube.com/playlist?list=%s' % id

def youtube_video(
    url,
    filter='bestvideo[ext=mp4][width=1920][height=1080]',
    strict=True):
    try:
        process = subprocess.run([
            'youtube-dl',
            '--quiet',
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
                'This video is unavailable',
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

def read_labels(url):
    video_id = youtube_video_id(url)
    process = subprocess.run([
        'youtube-dl',
        '--quiet',
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
        raise Exception('Video "%s" doesn\'t have subtitles.' % url)
    subtitles = "%s.en.vtt" % video_id
    labels = read_subtitles(subtitles)
    os.remove(subtitles)
    return labels
