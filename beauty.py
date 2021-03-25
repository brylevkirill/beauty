import argparse
import multiprocessing
import os
import random
import sys
import urllib.parse
import uuid

def init_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    def arg(*args, **kwargs):
        kwargs['action'] = 'store' if 'type' in kwargs else 'store_true'
        for a in args:
            if a.startswith('--'):
                kwargs['dest'] = a[2:].replace('-', '_')
        parser.add_argument(*args, **kwargs)

    opt = '<file|URL> | <YT playlist URL> | "ytsearch"[""|<N>|"all"]":"<query>'
    arg('--audios', type=str, nargs='*', default=['orchestral'],
        metavar='(%s|"none"|"any"|"orchestral"|"electronic"|"labeled")' % opt)
    arg('--videos', type=str, nargs='*', default=['flowers'],
        metavar='(%s|"none"|"any"|"flowers"|"nightsky"|"girls"|"girls2")' % opt)
    arg('--output', type=str, nargs='*', default=[],
        metavar='(<file> | <YT or IG live stream URL> | "-" (stdout))')

    arg('--labels', type=str, metavar='<labels file>')
    arg('--labels-reinit')
    arg('--labels-public')
    arg('--labels-serial')

    arg('--input', type=str, metavar='<video file>')
    arg('--input-labels', type=str, metavar='<labels file>')

    arg('--play')
    arg('--save')
    arg('--time', type=float, default=3600)
    arg('--noloop')
    arg('--nowait')
    arg('--queue', type=int, default=2)
    arg('--queue-delay', type=float, default=0.333)
    arg('--cache-delay', type=float)
    arg('--cache-limit', type=str, default='1M')

    arg('--reencode')
    arg('--increment')

    arg('--videos-max-number', type=int)
    arg('--videos-format', type=str)
    arg('--videos-width', type=int)
    arg('--videos-height', type=int)
    arg('--output-rotate')
    arg('--output-max-length', type=float)
    arg('--output-format', type=str)
    arg('--output-quality', type=str, choices=['high', 'medium', 'low'])
    arg('--output-id', type=str)
    arg('--subtitles')

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
    arg('--labels-from-notes-min-length', type=float, default=0.03)
    arg('--labels-from-notes-min-volume', type=float, default=-70)
    arg('--labels-from-notes-rnn')
    arg('--labels-from-notes-cnn')
    arg('--labels-from-onsets')
    arg('--labels-from-onsets-method', type=str,
        choices=['energy', 'hfc', 'complex', 'phase',
            'specdiff', 'kl', 'mkl', 'specflux'],
        default='specflux')
    arg('--labels-from-onsets-threshold', type=float, default=0.3)
    arg('--labels-from-onsets-min-length', type=float, default=0.02)
    arg('--labels-from-onsets-min-volume', type=float, default=-90)
    arg('--labels-min-length', type=float, default=0.2)
    arg('--labels-max-length', type=float)
    arg('--labels-joints', type=int)
    arg('--labels-splits', type=int)

    arg('--visual-filter-threads', type=int, default=os.cpu_count())
    arg('--visual-filter-retries', type=int, default=100)
    arg('--visual-filter-ordered')
    arg('--visual-filter-chrono')
    arg('--visual-filter-chrono-serial')
    arg('--visual-filter-chrono-mapper')
    arg('--visual-filter-chrono-speed', type=float)
    arg('--visual-filter-chrono-speed-factor', type=float, default=1.0)
    arg('--visual-filter-chrono-scope', type=float)
    arg('--visual-filter-chrono-scope-factor', type=float, default=1.0)
    arg('--visual-filter-pace', type=str, choices=['fast', 'slow'])
    arg('--visual-filter-pace-prob', type=float, default=0.02)
    arg('--visual-filter-pace-rate', type=float, default=0.2)
    arg('--visual-filter-cuts', type=str, choices=['exclude', 'include'])
    arg('--visual-filter-cuts-prob', type=float, default=0.05)
    arg('--visual-filter-dark', type=str, choices=['exclude', 'include'])
    arg('--visual-filter-face', type=str, choices=['exclude', 'include'])
    arg('--visual-filter-word', type=str, choices=['exclude', 'include'])

    arg('--visual-effect-speedup')
    arg('--visual-effect-speedup-freq', type=float, default=1)

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
    beauty.output = 'output.%s' % (
        beauty.args.output_id if beauty.args.output_id else uuid.uuid1())
    from beauty import args, output
    if not args.videos_width and not args.videos_height:
        args.videos_height = 1080
    if not args.videos_format:
        args.videos_format = 'mp4'
    beauty.stream = any(
        bool(urllib.parse.urlparse(item).scheme) for item in args.output)
    if not args.output_format:
        args.output_format = 'flv' if beauty.stream or args.play else 'mp4'
    args.labels = output + '.txt' if not args.labels else args.labels
    args.audios = args.audios if args.audios != ['none'] else None
    args.audio_output = (
        args.audio_output % (output, 'm4a') if args.audios else None)
    args.videos = args.videos if args.videos != ['none'] else None
    args.video_output = args.video_output % (output, args.output_format)
    args.cache = 'video.' + output + '.%s.' + args.output_format
    beauty.output += '.' + args.output_format
    if args.save:
        args.output.append(beauty.output)
    if not args.labels or not os.path.isfile(args.labels):
        args.labels_reinit = True
    if not args.reencode and not args.increment:
        args.reencode = True

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
                labels.read_labels(args.input_labels)
            else:
                if args.labels_from_input:
                    assert args.input
                    created_labels = videos.labels_from_video(args.input)
                    labels.update_labels(created_labels)
            if args.labels_serial:
                assert args.input
                labels.update_labels_serial(args.input)
            labels.write_labels()
        if args.audios:
            args.audios[:] = audios.read_audios()
            if not labels.labels:
                if args.labels_public:
                    created_labels = youtube.obtain_labels(args.audios[0])
                if not args.labels_public or not created_labels:
                    created_labels = audios.create_labels()
                labels.update_labels(created_labels)
                labels.write_labels()
        initial_labels = list(labels.labels)
        if args.videos:
            videos.read_videos()
            created_labels = videos.create_labels()
            labels.update_labels(created_labels)
            labels.write_labels()
        coders.write_video(initial_labels)
