import argparse
import bisect
import ItsAGramLive
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
        if 'action' not in kwargs:
            kwargs['action'] = 'store' if 'type' in kwargs else 'store_true'
        for a in args:
            if a.startswith('--'):
                kwargs['dest'] = a[2:].replace('-', '_')
        parser.add_argument(*args, **kwargs)

    opt = '<file|URL> | <YT playlist URL> | "ytsearch"[""|<N>|"all"]":"<query>'
    arg('--audios', type=str, nargs='+', action='extend',
        metavar='(%s|"none"|"any"|"orchestral"|"electronic"|"ambient")' % opt)
    arg('--videos', type=str, nargs='+', action='extend',
        metavar='(%s|"none"|"any"|"flowers"|"nightsky"|"slow-mo")' % opt)
    arg('--output', type=str, nargs='+', action='extend', default=[],
        metavar='(<file> | <YT or IG live stream URL> | "-" (stdout))')

    arg('--labels', type=str, metavar='<labels file>')
    arg('--labels-reinit')
    arg('--labels-public')

    arg('--input', type=str, metavar='<video file>')
    arg('--input-labels', type=str, metavar='<labels file>')

    arg('--videos-max-number', type=int)
    arg('--start', type=str, nargs='+', action='extend')
    arg('--final', type=str, nargs='+', action='extend')
    arg('--cuts')

    arg('--loop')
    arg('--save')
    arg('--queue-slots', type=int, default=1)
    arg('--queue-delay', type=float, default=0.5)
    arg('--queue-no-pause')
    arg('--time', type=float, default=3600)
    arg('--ppid', type=int)

    arg('--play')
    arg('--no-audio')
    arg('--no-video')

    arg('--stream')
    arg('--youtube-stream-key', type=str)
    arg('--instagram-username', type=str)
    arg('--instagram-password', type=str)

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

    arg('--reencode')
    arg('--increment')
    arg('--reencode-offset', type=float, default=-0.0415)
    arg('--increment-offset', type=float, default=-0.0245)
    arg('--mixed-offset', type=float, default=-0.045)

    arg('--media-output', type=str, default='output.%s')
    arg('--video-output', type=str, default='video.%s.%s')
    arg('--video-cache', type=str, default='video.%s')
    arg('--audio-output', type=str, default='audio.%s.%s')
    arg('--subtitles-output', type=str, default='%s.srt')

    arg('--loglevel', type=str,
        choices=['quiet', 'repeat+level+warning', 'repeat+level+verbose'],
        default='repeat+level+warning')

    import beauty
    beauty.args = parser.parse_args()
    from beauty import args

    if args.youtube_stream_key and not args.ppid:
        args.output.append(
            'rtmp://a.rtmp.youtube.com/live2/' + args.youtube_stream_key)
    if args.instagram_username and args.instagram_password and not args.ppid:
        live = ItsAGramLive.ItsAGramLive(
            username=args.instagram_username,
            password=args.instagram_password)
        if live.login() and live.create_broadcast():
            args.output.append(live.stream_server + live.stream_key)
            live.start_broadcast()
    if not args.stream:
        args.stream = any(
            bool(urllib.parse.urlparse(item).scheme) for item in args.output)

    if not args.output_format:
        args.output_format = 'flv' if args.stream or args.play else 'mp4'
    if not args.videos_format:
        args.videos_format = 'mp4'
    if not args.videos_width and not args.videos_height:
        args.videos_height = 1080

    args.media_output = args.media_output % (
        args.output_id if args.output_id else uuid.uuid1())
    args.labels = args.media_output + '.txt' if not args.labels else args.labels
    args.audios = (
        None if args.audios == ['none'] else
        ['orchestral'] if not args.audios else args.audios
    )
    args.audio_output = (args.audio_output % (
        args.media_output, 'm4a') if args.audios else None)
    args.videos = (
        None if args.videos == ['none'] else
        ['flowers'] if not args.videos else args.videos
    )
    args.video_output = args.video_output % (
        args.media_output, args.output_format)
    args.video_cache = args.video_cache % (
        args.media_output + '.%s.' + args.output_format)
    args.media_output += '.' + args.output_format

    if args.save:
        args.output.append(args.media_output)
    if not args.labels or not os.path.isfile(args.labels):
        args.labels_reinit = True
    if not args.reencode and not args.increment:
        args.reencode = True
    if args.loop and not args.play:
        args.no_audio = args.no_video = True

    import labels

    args.inputs = {}
    last_arg, last_url, start, final = None, None, 0, 0
    for arg in sys.argv:
        if arg == '--start':
            point = labels.parse_timestamp(args.start[start])
            start += 1
            if last_url not in args.inputs:
                args.inputs[last_url] = []
            args.inputs[last_url].append([point, -1])
        elif arg == '--final':
            point = labels.parse_timestamp(args.final[final])
            final += 1
            if last_arg == '--start':
                last_input = args.inputs[last_url][-1]
                args.inputs[last_url][-1] = (
                    (last_input[0], point) if point >= last_input[0]
                    else (point, last_input[0])
                )
            else:
                if last_url not in args.inputs:
                    args.inputs[last_url] = []
                args.inputs[last_url].append([-1, point])
        if arg[0:2] == '--':
            last_arg = arg
        else:
            if last_arg == '--videos':
                last_url = arg

    import videos

    if args.cuts:
        for url in args.inputs:
            labels = videos.labels_from_video(url)
            points = [labels[0].start]
            for label in labels:
                points.append(label.final)
            def bisect_points(point):
                index = bisect.bisect(points, point)
                if index == 0:
                    point = points[index]
                elif index == len(points):
                    point = points[index-1]
                elif abs(point-points[index-1]) > abs(point-points[index]):
                    point = points[index]
                else:
                    point = points[index-1]
                return point
            for i in range(len(args.inputs[url])):
                start, final = args.inputs[url][i]
                args.inputs[url][i] = [
                    points[0] if start == -1 else bisect_points(start),
                    points[-1] if final == -1 else bisect_points(final)
                ]

if __name__ == '__main__':
    init_args()
    from beauty import args

    import audios
    import coders
    import labels
    import videos
    import youtube

    if args.loop or args.play:
        coders.write_video_batch()
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
