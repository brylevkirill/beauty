import argparse
import os
import random
import shutil
import sys
import urllib.parse
import uuid

# implemented functionality:
# - reading audios & videos
# - YT videos/lists/search
# - reading/writing labels
# - creating labels (audio) (analyzing audio track)
# - creating labels (video) (analyzing video track)
# - applying visual filters
# - applying visual effects
# - encoding/writing videos (reencoding/incrementing)
# - playing created videos (during encoding/writing)
# - editing created videos (picture-in-picture mode)

# sample videos:
# - https://youtube.com/playlist?list=PL659KIPAkeqh4xPJF2BaUClsliKemfN5K

parser = argparse.ArgumentParser(
    formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
def arg(*args, **kwargs):
    kwargs['action'] = 'store' if 'type' in kwargs else 'store_true'
    for a in args:
        if a.startswith('--'):
            kwargs['dest'] = a[2:].replace('-', '_')
    parser.add_argument(*args, **kwargs)

opt = '<file|URL> | <YT playlist URL> | "ytsearch"[""|<N>|"all"]":"<query>'
arg('-a', '--audios', type=str, nargs='+', default=[],
    metavar='(%s | "any"|"orchestral"|"electronic"|"labeled")' % opt)
arg('-v', '--videos', type=str, nargs='+', default=[],
    metavar='(%s | "any"|"flowers"|"nightsky"|"girls"|"girls2")' % opt)
arg('-i', '--images', type=str, nargs='+', default=[])
arg('-o', '--output', type=str, nargs='*', default=[],
    metavar='(<file> | <live stream URL> | "-" (stdout))')

arg('-l', '--labels', type=str, metavar='<labels file>')
arg('--labels-reinit')
arg('--labels-public')
arg('--labels-source', type=str, metavar='<labels file>')
arg('--labels-source-reinit')

arg('-p', '--play')
arg('-k', '--keep')
arg('-x', '--loop')
arg('-t', '--time', type=float, default=600)
arg('-q', '--queue', type=int, default=2)
arg('-w', '--wait')
arg('-s', '--subtitles')

arg('--input', type=str, metavar='<file>')
arg('--input-labels', type=str, metavar='<labels file>')

arg('--reencode')
arg('--increment')

arg('--videos-max-number', type=int)
arg('--output-max-length', type=float)
arg('--output-format', type=str)
arg('--output-quality', type=str, choices=['high', 'medium', 'low'])

arg('--labels-min-length', type=float, default=0.2)
arg('--labels-max-length', type=float)
arg('--labels-joins', type=int, default=1)
arg('--labels-splits', type=int, default=1)
arg('--labels-from-chords')
arg('--labels-from-chords-chroma')
arg('--labels-from-chords-cnn')
arg('--labels-from-beats')
arg('--labels-from-beats-detection')
arg('--labels-from-beats-detection-crf')
arg('--labels-from-beats-tracking')
arg('--labels-from-beats-tracking-dbn')
arg('--labels-from-notes')
arg('--labels-from-notes-rnn')
arg('--labels-from-notes-cnn')

arg('--visual-filter-retries', type=int, default=5)
arg('--visual-filter-chrono')
arg('--visual-filter-chrono-scope', type=float)
arg('--visual-filter-chrono-speed', type=float)
arg('--visual-filter-drop-black-frame')
arg('--visual-filter-drop-hard-cuts')
arg('--visual-filter-drop-hard-cuts-prob', type=float, default=0.05)
arg('--visual-filter-drop-slow-pace')
arg('--visual-filter-drop-slow-pace-prob', type=float, default=0.02)
arg('--visual-filter-drop-slow-pace-rate', type=float, default=0.2)
arg('--visual-filter-drop-face-less')

arg('--visual-effect-speedup')
arg('--visual-effect-speedup-tempo-multi', type=float, default=1)
arg('--visual-effect-zooming')

arg('--loglevel', type=str,
    choices=['quiet', 'repeat+level+warning', 'repeat+level+verbose'],
    default='repeat+level+warning')
arg('--video-output', type=str, default='video.%s.%s')
arg('--audio-output', type=str, default='audio.%s.%s')
arg('--cache', metavar='<cache files>', type=str)
arg('--subtitles-output', type=str, default='%s.srt')
arg('--offset-reencode', type=float, default=-0.0415)
arg('--offset-increment', type=float, default=-0.0245)
arg('--offset-mixed', type=float, default=-0.045)

args = parser.parse_args()

output = 'output.%s' % uuid.uuid1()
if not args.output_format:
    stream_output = any(
        bool(urllib.parse.urlparse(output).scheme) for output in args.output
    )
    args.output_format = 'flv' if stream_output or args.play else 'mp4'
args.labels = output + '.txt' if not args.labels else args.labels
args.video_output = args.video_output % (output, args.output_format)
args.audio_output = args.audio_output % (output, 'm4a')
args.cache = 'cache.' + output + '.%s.' + args.output_format
output += '.' + args.output_format
if not args.labels or not os.path.isfile(args.labels):
    args.labels_reinit = True
if not args.reencode and not args.increment:
    args.reencode = True
args.visual_effect = (
    args.visual_effect_speedup or
    args.visual_effect_zooming)

if __name__== '__main__':
    import multiprocessing
    import random

    import labels
    import audios
    import videos
    import images
    import coders
    import youtube

    if args.play:
        coders.play_video()
        sys.exit()

    with multiprocessing.Manager() as manager:
        labels.labels = manager.list()
        videos.videos = manager.dict()
        images.images = manager.list()
        random.seed(int.from_bytes(os.getrandom(4), 'big'))
        if args.labels_source_reinit:
            labels.write_labels(args.labels_source, videos.create_labels())
        if not args.labels_reinit:
            labels.read_labels()
        else:
            if args.labels_source:
                shutil.copyfile(args.labels_source, args.labels)
                labels.read_labels()
        if args.audios:
            args.audios[:] = audios.read_audios()
            if not labels.labels:
                if args.labels_public:
                    new_labels = youtube.obtain_labels(args.audios[0])
                if not args.labels_public or not new_labels:
                    new_labels = audios.create_labels()
                labels.update_labels(new_labels)
                labels.write_labels()
        labels_before = list(labels.labels)
        if args.videos:
            videos.read_videos()
            videos.update_labels()
        elif args.images:
            images.read_images()
            images.update_labels()
        labels.write_labels()
        coders.write_video(labels_before)
