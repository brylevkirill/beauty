import subprocess
import validators

from labels import parse_timestamp

def youtube_collections(items, type):
    def process(items, collections):
        if not items:
            items.add(collections.values()[
                random.randint(0, len(collections) - 1)])
        else:
            for item in list(items):
                if item in collections:
                    items.append(collections[item])
                    items.remove(item)
    if type == 'audio':
        audios = {
            'orchestra': 'https://youtube.com/playlist?' \
                'list=PL659KIPAkeqgZtrIadb7YXGlFJBqZp9SX'
        }
        process(items, audios)
    if type == 'video':
        videos = {
            'night sky': 'https://youtube.com/playlist?' \
                'list=PL659KIPAkeqhsK80VGeiQ4g06mdYcJxt7',
            'flowers': 'https://youtube.com/playlist?' \
                'list=PL659KIPAkeqj_VlAKEuFRpHvCkl-03Fw1',
            'girls': 'https://youtube.com/playlist?' \
                'list=PL659KIPAkeqjaerr91OSBWPHRFbkY5jaD'
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

def youtube_video(
    url,
    filter='bestvideo[ext=mp4][width=1920][height=1080]',
    strict=True):
    try:
        process = subprocess.run([
            'youtube-dl',
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
                'requested format not available'
            ]):
                return None
        raise e
    output = process.stdout.decode().splitlines()
    variants = [
        (url, parse_timestamp(duration))
        for (url, duration) in zip(*[iter(output)] * 2)
        if check_media_url(url)
    ]
    if strict and not variants:
        raise Exception('Can\'t read "%s".' % url)
    return variants[0] if variants else None

def check_media_url(url):
    process = subprocess.run([
        'ffprobe',
        '-v', 'quiet',
        url
        ],
        check=False
    )
    return process.returncode == 0
