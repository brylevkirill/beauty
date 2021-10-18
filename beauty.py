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

    arg('--mappings', type=str, metavar='<mappings file>')
    arg('--mappings-reinit')
    arg('--mappings-public')

    arg('--input', type=str, metavar='<video file|URL>')
    arg('--input-mappings', type=str, metavar='<mappings file>')

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

    arg('--mappings-from-cuts')
    arg('--mappings-from-chords')
    arg('--mappings-from-chords-chroma')
    arg('--mappings-from-chords-cnn')
    arg('--mappings-from-beats')
    arg('--mappings-from-beats-detection')
    arg('--mappings-from-beats-detection-crf')
    arg('--mappings-from-beats-tracking')
    arg('--mappings-from-beats-tracking-dbn')
    arg('--mappings-from-notes')
    arg('--mappings-from-notes-min-length', type=float, default=0.03)
    arg('--mappings-from-notes-min-volume', type=float, default=-70)
    arg('--mappings-from-notes-rnn')
    arg('--mappings-from-notes-cnn')
    arg('--mappings-from-onsets')
    arg('--mappings-from-onsets-method', type=str,
        choices=['energy', 'hfc', 'complex', 'phase',
            'specdiff', 'kl', 'mkl', 'specflux'],
        default='specflux')
    arg('--mappings-from-onsets-threshold', type=float, default=0.3)
    arg('--mappings-from-onsets-min-length', type=float, default=0.02)
    arg('--mappings-from-onsets-min-volume', type=float, default=-90)
    arg('--mappings-min-interval', type=float, default=0.2)
    arg('--mappings-max-interval', type=float)
    arg('--mappings-joints', type=int)
    arg('--mappings-splits', type=int)

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
    args.mappings = (
        args.media_output + '.txt' if not args.mappings else args.mappings
    )
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
    if not args.mappings or not os.path.isfile(args.mappings):
        args.mappings_reinit = True
    if not args.reencode and not args.increment:
        args.reencode = True
    if args.loop and not args.play:
        args.no_audio = args.no_video = True

    import mappings

    args.inputs = {}
    last_arg, last_url, start, final = None, None, 0, 0
    for arg in sys.argv:
        if arg == '--start':
            point = mappings.parse_timestamp(args.start[start])
            start += 1
            if last_url not in args.inputs:
                args.inputs[last_url] = []
            args.inputs[last_url].append([point, -1])
        elif arg == '--final':
            point = mappings.parse_timestamp(args.final[final])
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
            mappings = videos.mappings_from_cuts(url)
            points = [mappings[0].start]
            for mapping in mappings:
                points.append(mapping.final)
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
    import mappings
    import videos
    import youtube

    if args.loop or args.play:
        coders.write_video_batch()
        sys.exit()

    with multiprocessing.Manager() as manager:
        mappings.mappings = manager.list()
        videos.videos = manager.dict()
        random.seed(int.from_bytes(os.getrandom(4), 'big'))
        if not args.mappings_reinit:
            mappings.read()
        else:
            if args.input_mappings:
                mappings.read(args.input_mappings)
            elif args.mappings_from_cuts:
                assert args.input
                new_mappings = videos.mappings_from_cuts(args.input)
                mappings.update(new_mappings)
            mappings.write()
        if args.audios:
            args.audios[:] = audios.read()
            if not mappings.mappings:
                if args.mappings_public:
                    new_mappings = youtube.mappings_from_subs(args.audios[0])
                if not args.mappings_public or not new_mappings:
                    new_mappings = audios.generate_mappings()
                mappings.update(new_mappings)
                mappings.write()
        old_mappings = list(mappings.mappings)
        if args.videos:
            videos.read()
            new_mappings = videos.generate_mappings()
            mappings.update(new_mappings)
            mappings.write()
        coders.write_video(old_mappings)
