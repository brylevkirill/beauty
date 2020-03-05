import argparse
import collections
import multiprocessing
import random
import time

parser = argparse.ArgumentParser(
    formatter_class=argparse.ArgumentDefaultsHelpFormatter
)
def arg(*args, **kwargs):
    kwargs['action'] = 'store' if 'type' in kwargs else 'store_true'
    for a in args:
        if a.startswith('--'):
            kwargs['dest'] = a[2:].replace('-', '_')
    parser.add_argument(*args, **kwargs)

arg('-n', '--new-labels')
arg('-l', '--labels', metavar='<labels file>', type=str)
opt = '<file|URL> | <YT playlist URL> | "ytsearch"[""|<N>|"all"]":"<query>"'
arg('-a', '--audios', metavar='(%s | "orchestra")' % opt,
    type=str, nargs='+', default=[])
arg('-v', '--videos', metavar='(%s | "night sky"|"flowers"|"girls")' % opt,
    type=str, nargs='+', default=[])
arg('-o', '--output', metavar='<file> | "-" (stdout)', type=str)

arg('-m', '--videos-max-number', type=int)
arg('-d', '--output-max-length', type=float)
arg('-f', '--output-format', type=str, default='mp4')
arg('-r', '--reencode')
arg('-i', '--increment')

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

arg('--video-output', type=str, default='%s.video')
arg('--audio-output', type=str, default='%s.audio')
arg('--cache', metavar='<cache file>', type=str, default='%d.mp4')
arg('--offset-reencode', type=float, default=-0.0415)
arg('--offset-increment', type=float, default=-0.0245)
arg('--offset-mixed', type=float, default=-0.045)

args = parser.parse_args()

output = args.output if args.output != '-' else 'stdout.mp4'
if not output.endswith('.' + args.output_format):
    args.output_format = output[output.rfind('.') + 1:]
args.video_output = args.video_output % output + '.' + args.output_format
args.audio_output = args.audio_output % output + '.m4a'
if not args.labels:
    args.labels = output + '.labels.txt'
    args.new_labels = True
if not args.reencode and not args.increment:
    args.reencode = True

# implemented functionality:
# - reading audios & videos
# - YT videos/lists/search
# - reading/writing labels
# - creating labels (audio)
# - creating labels (video)
# - applying visual filters
# - applying visual effects
# - encoding/writing videos (reencoding/incrementing)

if __name__== '__main__':
    import labels
    import audios
    import videos
    import coders
    with multiprocessing.Manager() as manager:
        labels.labels = manager.list()
        videos.videos = manager.dict()
        random.seed(time.time())
        if not args.new_labels:
            labels.read_labels()
            if not labels.labels:
                args.new_labels = True
        audios.read_audios()
        if not labels.labels:
            labels.labels.extend(audios.create_labels_audio())
            labels.write_labels()
        videos.read_videos()
        labels_before = list(labels.labels)
        videos.create_labels_video()
        coders.write_video(labels_before)
