import argparse
import multiprocessing
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
# - encoding/writing videos (reencoding/incremental)
# - streaming created videos (video generation queue)
# - playing created videos (video generation queue)
# - editing created videos (picture-in-picture mode)

# sample videos:
# - https://youtube.com/playlist?list=PL659KIPAkeqh4xPJF2BaUClsliKemfN5K

def init_args():
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
    arg('-a', '--audios', type=str, nargs='*', default=['orchestral'],
        metavar='(%s | "any"|"orchestral"|"electronic"|"labeled")' % opt)
    arg('-v', '--videos', type=str, nargs='*', default=['flowers'],
        metavar='(%s | "any"|"flowers"|"nightsky"|"girls"|"girls2")' % opt)
    arg('-o', '--output', type=str, nargs='*', default=[],
        metavar='(<file> | <live stream URL> | "-" (stdout))')

    arg('-l', '--labels', type=str, metavar='<labels file>')
    arg('--labels-reinit')
    arg('--labels-public')

    arg('--input', type=str, metavar='<video file>')
    arg('--input-labels', type=str, metavar='<labels file>')

    arg('-p', '--play')
    arg('-k', '--keep')
    arg('-x', '--loop')
    arg('-t', '--time', type=float, default=3600)
    arg('-q', '--queue', type=int, default=2)
    arg('-d', '--delay', type=float, default=0.333)
    arg('-n', '--nowait')
    arg('-s', '--subtitles')

    arg('--reencode')
    arg('--increment')

    arg('--videos-max-number', type=int)
    arg('--output-max-length', type=float)
    arg('--output-format', type=str)
    arg('--output-quality', type=str, choices=['high', 'medium', 'low'])

    arg('--labels-from-input')
    arg('--labels-from-chords')
    arg('--labels-from-chords-chroma')
    arg('--labels-from-chords-cnn')
    arg('--labels-from-beats')
    arg('--labels-from-beats-detection')
    arg('--labels-from-beats-detection-crf')
    arg('--labels-from-beats-tracking')
    arg('--labels-from-beats-tracking-dbn')
    arg('--labels-from-notes')
    arg('--labels-from-notes-min-interval', type=float, default=0.02)
    arg('--labels-from-notes-min-silence', type=float, default=-90)
    arg('--labels-from-notes-rnn')
    arg('--labels-from-notes-cnn')
    arg('--labels-from-onsets')
    arg('--labels-from-onsets-method', type=str,
        choices=['energy', 'hfc', 'complex', 'phase',
            'specdiff', 'kl', 'mkl', 'specflux'],
        default='hfc')
    arg('--labels-from-onsets-threshold', type=float, default=0.3)
    arg('--labels-from-onsets-min-interval', type=float, default=0.02)
    arg('--labels-from-onsets-min-silence', type=float, default=-90)
    arg('--labels-min-length', type=float, default=0.05)
    arg('--labels-max-length', type=float)
    arg('--labels-joints', type=int, default=1)
    arg('--labels-splits', type=int, default=1)

    arg('--visual-filter-retries', type=int, default=5)
    arg('--visual-filter-ordered')
    arg('--visual-filter-chrono')
    arg('--visual-filter-chrono-scope', type=float)
    arg('--visual-filter-chrono-speed', type=float)
    arg('--visual-filter-dark')
    arg('--visual-filter-cuts')
    arg('--visual-filter-cuts-prob', type=float, default=0.05)
    arg('--visual-filter-pace', type=str, choices=['fast', 'slow'])
    arg('--visual-filter-pace-prob', type=float, default=0.02)
    arg('--visual-filter-pace-rate', type=float, default=0.2)
    arg('--visual-filter-face', type=str, choices=['include', 'exclude'])
    arg('--visual-filter-word', type=str, choices=['include', 'exclude'])

    arg('--visual-effect-speedup')
    arg('--visual-effect-speedup-freq', type=float, default=1)
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

    import beauty
    beauty.args = parser.parse_args()
    beauty.output = 'output.%s' % uuid.uuid1()
    from beauty import args, output
    if not args.output_format:
        stream_output = any(
            bool(urllib.parse.urlparse(item).scheme) for item in args.output
        )
    args.output_format = 'flv' if stream_output or args.play else 'mp4'
    args.labels = output + '.txt' if not args.labels else args.labels
    args.video_output = args.video_output % (output, args.output_format)
    args.audio_output = args.audio_output % (output, 'm4a')
    args.cache = 'video.' + output + '.%s.' + args.output_format
    beauty.output += '.' + args.output_format
    if not args.labels or not os.path.isfile(args.labels):
        args.labels_reinit = True
    if not args.reencode and not args.increment:
        args.increment = True
    args.visual_effect = (
        args.visual_effect_speedup or
        args.visual_effect_zooming)

if __name__ == '__main__':
    init_args()
    from beauty import args

    import audios
    import coders
    import labels
    import videos
    import youtube

    if args.play:
        coders.play_video()
        sys.exit()

    with multiprocessing.Manager() as manager:
        labels.labels = manager.list()
        videos.videos = manager.dict()
        random.seed(int.from_bytes(os.getrandom(4), 'big'))
        if not args.labels_reinit:
            labels.read_labels()
        else:
            if args.input_labels:
                shutil.copyfile(args.input_labels, args.labels)
                labels.read_labels()
            else:
                if args.input and args.labels_from_input:
                    new_labels = videos.labels_from_video(args.input)
                    labels.update_labels(new_labels)
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
        labels.write_labels()
        coders.write_video(labels_before)
