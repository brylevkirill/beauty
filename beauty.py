import argparse
import os
import random
import shutil
import sys
import uuid

# implemented functionality:
# - reading audios & videos
# - YT videos/lists/search
# - reading/writing labels
# - creating labels (audio)
# - creating labels (video)
# - applying visual filters
# - applying visual effects
# - encoding/writing videos (reencoding/incrementing)
# - playing created videos

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
arg('-o', '--output', type=str, metavar='<file> | "-" (stdout)')

arg('-l', '--labels', type=str, metavar='<labels file>')
arg('--labels-reinit')
arg('--labels-public')
arg('--labels-source', type=str, metavar='<labels file>')

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
arg('--output-format', type=str, default='mp4')
arg('--output-quality', type=str, choices=['high', 'low'])

arg('--create-labels-min-length', type=float, default=0.2)
arg('--create-labels-max-length', type=float)
arg('--create-labels-joins', type=int, default=1)
arg('--create-labels-splits', type=int, default=1)
arg('--create-labels-from-chords')
arg('--create-labels-from-chords-chroma')
arg('--create-labels-from-chords-cnn')
arg('--create-labels-from-beats')
arg('--create-labels-from-beats-detection')
arg('--create-labels-from-beats-tracking')
arg('--create-labels-from-beats-detection-crf')
arg('--create-labels-from-beats-tracking-dbn')
arg('--create-labels-from-notes')
arg('--create-labels-from-notes-rnn')
arg('--create-labels-from-notes-cnn')

arg('--visual-filter-retries', type=int, default=5)
arg('--visual-filter-chrono')
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

arg('--loglevel', default='repeat+level+warning')
arg('--video-output', type=str, default='%s.video')
arg('--audio-output', type=str, default='%s.audio')
arg('--cache', metavar='<cache file>', type=str, default='%d.mp4')
arg('--subtitles-output', type=str, default='%s.srt')
arg('--player-config', type=str, default='%s.conf')
arg('--offset-reencode', type=float, default=-0.0415)
arg('--offset-increment', type=float, default=-0.0245)
arg('--offset-mixed', type=float, default=-0.045)

args = parser.parse_args()

output = ('output.' + str(uuid.uuid1()) + '.mp4'
    if not args.output or args.output == '-'
    else args.output)
if not output.endswith('.' + args.output_format):
    args.output_format = output[output.rfind('.') + 1:]
args.video_output = args.video_output % output + '.' + args.output_format
args.audio_output = args.audio_output % output + '.m4a'
if not args.labels or not os.path.isfile(args.labels):
    args.labels_reinit = True
if not args.labels:
    args.labels = output + '.txt'
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
        if not args.labels_reinit:
            labels.read_labels(args.labels)
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
