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
        formatter_class=
            argparse.ArgumentDefaultsHelpFormatter
    )

    def arg(*args, **kwargs):
        if 'action' not in kwargs:
            kwargs['action'] = 'store' \
                if 'type' in kwargs else 'store_true'
        for a in args:
            if a.startswith('--'):
                kwargs['dest'] = a[2:].replace('-', '_')
        parser.add_argument(*args, **kwargs)

    opt = '<file|URL> | <YT playlist URL> |' + \
        '"ytsearch"[""|<N>|"all"]":"<query>'
    arg('--audios', type=str, nargs='+', action='extend',
        metavar=\
        '(%s|"none"|"any"|"orchestral"|"electronic")' % opt)
    arg('--videos', type=str, nargs='+', action='extend',
        metavar=\
        '(%s|"none"|"any"|"flowers"|"nightsky")' % opt)
    arg('--output', type=str, nargs='+', action='extend',
        default=[], metavar=\
        '(<file> | <stream URL> | <stdout "-">)')
    arg('--mappings', type=str, metavar='<mappings file>')

    arg('--input', type=str, metavar='<video file|URL>')

    arg('--loop')
    arg('--loop-time', type=float, default=3600)
    arg('--loop-jobs', type=int, default=1)
    arg('--loop-job-time', type=float)
    arg('--loop-job-wait', type=float, default=0.33)
    arg('--loop-job-kill')
    arg('--loop-ppid', type=int)

    arg('--play')
    arg('--no-audio')
    arg('--no-video')
    arg('--save')

    arg('--stream')
    arg('--youtube-stream-key', type=str)
    arg('--instagram-username', type=str)
    arg('--instagram-password', type=str)

    arg('--output-format', type=str)
    arg('--output-width', type=int)
    arg('--output-height', type=int)
    arg('--output-rotate')
    arg('--output-length', type=float)
    arg('--output-quality', type=str, default='medium',
        choices=['high', 'medium', 'low'])
    arg('--output-subtitles')
    arg('--output-id', type=str)

    arg('--videos-format', type=str)
    arg('--videos-width', type=int)
    arg('--videos-height', type=int)
    arg('--videos-number', type=int)
    arg('--start', type=str, nargs='+', action='extend')
    arg('--final', type=str, nargs='+', action='extend')
    arg('--cuts')

    arg('--mappings-reinit')
    arg('--mappings-from-subs')
    arg('--mappings-from-chords')
    arg('--mappings-from-chords-chroma')
    arg('--mappings-from-chords-cnn')
    arg('--mappings-from-beats')
    arg('--mappings-from-beats-detection')
    arg('--mappings-from-beats-detection-crf')
    arg('--mappings-from-beats-tracking')
    arg('--mappings-from-beats-tracking-dbn')
    arg('--mappings-from-notes')
    arg('--mappings-from-notes-min-length', type=float,
        default=0.03)
    arg('--mappings-from-notes-min-volume', type=float,
        default=-70)
    arg('--mappings-from-notes-rnn')
    arg('--mappings-from-notes-cnn')
    arg('--mappings-from-onsets')
    arg('--mappings-from-onsets-method', type=str,
        default='specflux', choices=[
            'energy', 'hfc', 'complex', 'phase',
            'specdiff', 'kl', 'mkl', 'specflux'
        ])
    arg('--mappings-from-onsets-threshold', type=float,
        default=0.3)
    arg('--mappings-from-onsets-min-length', type=float,
        default=0.02)
    arg('--mappings-from-onsets-min-volume', type=float,
        default=-90)
    arg('--mappings-min-interval', type=float, default=0.2)
    arg('--mappings-max-interval', type=float)
    arg('--mappings-joints', type=int)
    arg('--mappings-splits', type=int)

    arg('--visual-filter-threads', type=int,
        default=os.cpu_count())
    arg('--visual-filter-retries', type=int, default=100)
    arg('--visual-filter-ordered')
    arg('--visual-filter-chrono')
    arg('--visual-filter-chrono-speed', type=float, default=1.0)
    arg('--visual-filter-chrono-scope', type=float, default=1.0)
    arg('--visual-filter-pace', type=str,
        choices=['fast', 'slow'])
    arg('--visual-filter-pace-prob', type=float, default=0.02)
    arg('--visual-filter-pace-rate', type=float, default=0.2)
    arg('--visual-filter-cuts', type=str,
        choices=['exclude', 'include'])
    arg('--visual-filter-cuts-prob', type=float, default=0.05)
    arg('--visual-filter-dark', type=str,
        choices=['exclude', 'include'])
    arg('--visual-filter-face', type=str,
        choices=['exclude', 'include'])
    arg('--visual-filter-word', type=str,
        choices=['exclude', 'include'])

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

    arg('--loglevel', type=str, default='warning',
        choices=['quiet', 'warning', 'verbose'])

    import beauty
    beauty.args = parser.parse_args()
    from beauty import args

    if not args.stream:
        args.stream = any(
            bool(urllib.parse.urlparse(item).scheme)
            for item in args.output
        )
    if not args.loop_ppid:
        if args.youtube_stream_key:
            args.output.append(
                'rtmp://a.rtmp.youtube.com/live2/' +
                    args.youtube_stream_key
            )
        if args.instagram_username and \
            args.instagram_password:
            live = ItsAGramLive.ItsAGramLive(
                username=args.instagram_username,
                password=args.instagram_password)
            if live.login() and live.create_broadcast():
                args.output.append(
                    live.stream_server + live.stream_key
                )
                live.start_broadcast()

    if not args.output_format:
        args.output_format = 'flv' \
            if args.stream or args.play else 'mp4'
    if not args.videos_format:
        args.videos_format = 'mp4'
    if not args.videos_width and not args.videos_height:
        args.videos_height = 1080

    args.media_output = args.media_output % \
        (args.output_id if args.output_id else uuid.uuid1())
    args.mappings = args.media_output + '.txt' \
        if not args.mappings else args.mappings
    args.audios = None if args.audios == ['none'] else \
        (['orchestral'] if not args.audios else args.audios)
    args.audio_output = args.audio_output % \
        (args.media_output, 'm4a') if args.audios else None
    args.videos = None if args.videos == ['none'] else \
        (['flowers'] if not args.videos else args.videos)
    args.video_output = args.video_output % \
        (args.media_output, args.output_format)
    args.video_cache = args.video_cache % \
        (args.media_output + '.%s.' + args.output_format)
    args.media_output += '.' + args.output_format

    if args.save:
        args.output.append(args.media_output)
    if not args.mappings or not os.path.isfile(args.mappings):
        args.mappings_reinit = True
    if not args.reencode and not args.increment:
        args.reencode = True
    if args.loop and not args.play:
        args.no_audio = args.no_video = True

    args.inputs = {}
    last_arg, last_url, start, final = None, None, 0, 0
    for arg in sys.argv:
        if arg == '--start':
            from .mappings import parse_timestamp
            point = parse_timestamp(args.start[start])
            start += 1
            if last_url not in args.inputs:
                args.inputs[last_url] = []
            args.inputs[last_url].append((point, -1))
        elif arg == '--final':
            point = parse_timestamp(args.final[final])
            final += 1
            if last_arg == '--start':
                last_input = args.inputs[last_url][-1]
                args.inputs[last_url][-1] = (
                    (last_input[0], point)
                    if point >= last_input[0]
                    else (point, last_input[0])
                )
            else:
                if last_url not in args.inputs:
                    args.inputs[last_url] = []
                args.inputs[last_url].append((-1, point))
        if arg[0:2] == '--':
            last_arg = arg
        else:
            if last_arg == '--videos':
                last_url = arg

    if args.cuts:
        for url in args.inputs:
            from .videos import mappings_from_cuts
            mappings = mappings_from_cuts(url)
            points = [mappings[0].start]
            for mapping in mappings:
                points.append(mapping.final)
            def bisect_points(point):
                index = bisect.bisect(points, point)
                if index == 0:
                    point = points[index]
                elif index == len(points):
                    point = points[index-1]
                elif abs(point-points[index-1]) > \
                    abs(point-points[index]):
                    point = points[index]
                else:
                    point = points[index-1]
                return point
            for idx, item in enumerate(args.inputs[url]):
                start, final = item
                args.inputs[url][idx] = [
                    points[0] if start == -1 \
                        else bisect_points(start),
                    points[-1] if final == -1 \
                        else bisect_points(final)
                ]

def main():
    init_args()
    from beauty import args

    import beauty.audios as audios
    import beauty.coders as coders
    import beauty.mappings as mappings
    import beauty.videos as videos
    import beauty.youtube as youtube

    if args.loop or args.play:
        coders.write_video_batch()
        sys.exit()

    with multiprocessing.Manager() as manager:
        mappings.mappings = manager.list()
        videos.videos = manager.dict()
        random.seed(int.from_bytes(os.getrandom(4), 'big'))
        if not args.mappings_reinit:
            mappings.read()
        if args.audios:
            args.audios[:] = audios.read()
            if not mappings.mappings:
                if args.mappings_from_subs:
                    mappings.mappings[:] = \
                        youtube.mappings_from_subs(
                            args.audios[0])
                else:
                    mappings.mappings[:] = \
                        audios.generate_mappings()
                mappings.write()
        previous_mappings = list(mappings.mappings)
        if args.videos:
            args.videos[:] = videos.read()
            mappings.mappings[:] = \
                videos.generate_mappings()
            mappings.write()
        coders.write_video(previous_mappings)

if __name__ == '__main__':
    main()
