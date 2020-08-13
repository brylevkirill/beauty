import inspect
import itertools
import os
import shutil
import signal
import subprocess
import sys
import urllib.parse

import labels
import videos
from beauty import args, output
from labels import update_labels_filter
from videos import read_video
from effects import visual_effects

def write_video(labels_before):
    if not labels.labels_created():
        return
    if args.reencode and args.increment:
        write_video_mixed(labels_before)
    elif args.reencode:
        write_video_reencode()
    elif args.increment:
        write_video_increment()
    if args.increment:
        if args.audios:
            write_video_with_audio()
            if os.path.isfile(args.audio_output):
                os.remove(args.audio_output)
            os.remove(args.video_output)
        else:
            os.replace(args.video_output, output)

def write_video_reencode():
    stream_output = urllib.parse.urlparse(args.output).scheme
    for l in labels.labels:
        if l.input_url not in videos.videos:
            read_video(l.input_url)
    def apply(functions, x):
        y = x
        for f in functions:
            y = f(y)
        return y
    concat_filter = 'concat=n=%d' % len(labels.labels)
    effects_filters, effects_mappers = visual_effects()
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel] +
        list(itertools.chain.from_iterable([
            '-ss', str(l.input_start_point),
            '-t', '%.3f' % max(0,
                apply(effects_mappers, l.output_final_point) -
                apply(effects_mappers, l.output_start_point) +
                args.offset_reencode),
            '-i', videos.videos[l.input_url].url
            ] for l in labels.labels
                   )) + [
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        '-i', args.audio_output,
        '-filter_complex', ', '.join([concat_filter] + effects_filters),
        '-shortest',
        '-c:v', 'libx264',
        *(['-crf', '17'] if args.output_quality == 'high' else
            ['-crf', '33'] if args.output_quality == 'low' else []),
        *(['-preset', 'slow'] if args.output_quality == 'high' else
            ['-preset', 'fast'] if args.output_quality == 'low' else []),
        *(['-tune', 'film'] if args.output_quality == 'high' else []),
        '-f', args.output_format,
        '-c:a', 'copy',
        '-y',
        args.output if stream_output else args.video_output
        ],
        check=True
    )

def write_video_increment():
    process = subprocess.Popen([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-protocol_whitelist', 'file,pipe',
        '-f', 'concat',
        '-safe', '0',
        '-i', 'pipe:',
        '-c:v', 'copy',
        '-an',
        '-y',
        args.video_output
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    process.stdin.writelines(
        ('file \'%s\'\n' % args.cache % (
            i + 1,
            args.output_format
        )).encode()
        for i in range(len(labels.labels))
    )
    _, errors = process.communicate()
    if process.returncode != 0:
        raise Exception(errors)

def write_video_mixed(labels_before):
    if not os.path.isfile(output):
        write_video_mixed_reencode()
    else:
        write_video_mixed_increment(labels_before)

def write_video_mixed_reencode():
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel] +
        list(itertools.chain.from_iterable([
            '-i', args.cache % (
                i + 1,
                args.output_format
            )] for i in range(len(labels.labels))
        )) + [
        '-filter_complex', 'concat=n=%d' % len(labels.labels),
        '-an',
        '-y',
        args.video_output
        ],
        check=True
    )

def write_video_mixed_increment(labels_before):
    labels_delta = sorted(
        set(labels.labels) - set(labels_before),
        key=lambda t: t[0]
    )
    if not labels_delta:
        return
    process = subprocess.Popen([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-protocol_whitelist', 'file,pipe',
        '-f', 'concat',
        '-safe', '0',
        '-i', 'pipe:',
        '-c:v', 'copy',
        '-an',
        '-y',
        args.video_output
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    i0 = -1
    for i in range(len(labels.labels) + 1):
        if i == len(labels.labels) or labels.labels[i] in labels_delta:
            if i0 != -1:
                process.stdin.write((
                    'file \'%s\'\n' \
                    'inpoint %f\n' \
                    'outpoint %f\n' % (
                    output,
                    labels.labels[i0].output_start_point,
                    labels.labels[i - 1].output_final_point +
                        args.offset_mixed
                    )).encode()
                )
                i0 = -1
            if i < len(labels.labels):
                process.stdin.write((
                    'file \'%s\'\n' % args.cache % (
                        i + 1,
                        args.output_format
                    )).encode()
                )
        else:
            if i0 == -1:
                i0 = i
    _, errors = process.communicate()
    if process.returncode != 0:
        raise Exception(errors)

def write_video_with_audio():
    stream_output = urllib.parse.urlparse(args.output).scheme
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        '-i', args.video_output,
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        '-i', args.audio_output,
        '-c', 'copy',
        '-f', args.output_format,
        '-y',
        args.output if stream_output else output
        ],
        check=True
    )

def play_video():
    play_video_prepare()
    video = '%d.' + output
    delay = args.output_max_length if args.output_max_length else 60
    tasks = int(args.time / delay) if args.loop else 1
    command = (
        'bash -c "' \
            'mpv ' +
                ('--input-conf=\'%s\' ' % player_config
                    if args.input and args.input_labels else '') +
                '--fs ' + ' '.join(
                '--{ <( ' \
                    'sleep %d; ' \
                    'timeout --foreground %f ' \
                        'parallel --semaphore -j %d --fg %s; ' \
                    'cat %s; ' \
                    'rm -f %s ' \
                    ') ' \
                    '--stream-buffer-size=16MiB ' \
                    '%s' \
                    '%s' \
                '--} ' % (
                    max((i - 0.5) * delay, 0),
                    args.queue * delay if not args.wait else 0,
                    args.queue,
                    'python \\\'%s\\\'' % ('\\\' \\\''.join(
                        arg.replace(' ', '\\ ').
                            replace('(', '\\(').
                            replace(')', '\\)').
                            replace('&', '\\&')
                        for arg in sys.argv + [
                            '--output',
                            args.output if args.output else video % i
                        ]
                    )),
                    args.output if args.output else video % i,
                    (args.output if args.output else video % i)
                        if not args.keep else '',
                    '--sub-file=\'%s\' ' % args.subtitles_output %
                        (args.output if args.output else video % i)
                        if args.subtitles else '',
                    '--lavfi-complex=\'' \
                        '[vid2]scale=iw/2:ih/2[v],' \
                        '[vid1][v]overlay=W-w:H-h[vo]\' ' \
                    '--external-file=\'%s\' ' % args.input
                        if args.input else ''
                )
                for i in range(tasks)
            ) + '' \
        '"'
    )
    os.system(command)
    play_video_cleanup()

def play_video_prepare():
    play_video_prepare_args()
    if args.input_labels:
        play_video_prepare_edit()

def play_video_prepare_args():
    sys.argv.remove('--play')
    if args.loop:
        sys.argv.remove('--loop')
    if not args.audios:
        sys.argv.extend(['--audios', 'any'])
    if not args.videos:
        sys.argv.extend(['--videos', 'any'])
        sys.argv.extend(['--videos-max-number', str(1)])
    sys.argv.extend(['--output-quality', 'low'])

def play_video_prepare_edit():
    global player_config
    player_config = '%s.input.conf' % output
    global labels_backup
    labels_backup = '%s.labels.txt' % output
    func = inspect.getsource(update_labels_filter).replace('\n', '\\n')
    call = "update_labels_filter('%s', '%s', ${=time-pos})"
    with open(player_config, 'w') as f:
        f.write(
            """
                MBTN_LEFT_DBL run python -c \"%s\"
                MBTN_RIGHT_DBL run python -c \"%s\"
                MBTN_RIGHT ignore
            """ % (
                func + call % (args.labels, args.input_labels),
                func + call % (labels_backup, args.input_labels)
            )
        )
    shutil.copyfile(args.input_labels, labels_backup)

def play_video_cleanup():
    if args.input_labels:
        os.remove(player_config)
        os.remove(labels_backup)
