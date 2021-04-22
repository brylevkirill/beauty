import inspect
import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

import labels
import videos
from beauty import args
from labels import labels_created, update_labels_filter
from videos import read_video
from effects import visual_effects

def write_video(initial_labels):
    if not labels_created():
        return
    if args.reencode and args.increment:
        write_video_mixed(initial_labels)
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
            shutil.move(args.video_output, args.media_output)

def write_video_reencode():
    for l in labels.labels:
        if l.input_url not in videos.videos:
            read_video(l.input_url)
    def apply(functions, x):
        y = x
        for f in functions:
            y = f(y)
        return y
    concat_filter = ['concat=n=%d:v=1:a=0' % len(labels.labels)]
    effect_filter, effect_mapper = visual_effects()
    rotate_filter = ['transpose=2'] if args.output_rotate else []
    filters = concat_filter + effect_filter + rotate_filter
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        *(['-re'] if args.stream else []),
        *list(itertools.chain.from_iterable([
            '-ss', str(l.input_start_point),
            '-t', '%.3f' % max(0,
                apply(effect_mapper, l.output_final_point) -
                apply(effect_mapper, l.output_start_point) +
                args.reencode_offset),
            '-i', videos.videos[l.input_url].url
            ] for l in labels.labels
            )),
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        *(['-i', args.audio_output] if args.audio_output else []),
        '-filter_complex', ', '.join(filters) + '[v]',
        '-map', '[v]',
        *(['-map', '%d:a' % len(labels.labels)] if args.audio_output else []),
        '-shortest',
        '-vsync', 'vfr',
        '-flags', '+global_header',
        '-codec:v', 'libx264',
        *(['-crf', '17'] if args.output_quality == 'high' else
            ['-crf', '33'] if args.output_quality == 'low' else []),
        *(['-preset', 'slow'] if args.output_quality == 'high' else
            ['-preset', 'veryfast'] if args.output_quality == 'low' else []),
        *(['-tune', 'film'] if args.output_quality == 'high' else []),
        '-codec:a', 'aac',
        '-f', 'tee',
        '-use_fifo', '1',
        '|'.join(
            ('[f=%s%s]' % (
                args.output_format,
                ':flvflags=no_duration_filesize'
                    if args.output_format == 'flv' else ''
                ) if args.output_format else '') +
            (target if target != '-' else 'pipe:1')
            for target in (args.output
                if args.output else [args.media_output])
        ),
        '-y'
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
        '-codec:v', 'copy',
        '-an',
        '-y',
        args.video_output
        ],
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    process.stdin.writelines(
        ('file \'%s\'\n' % args.video_cache % (i + 1)).encode()
        for i in range(len(labels.labels))
    )
    _, errors = process.communicate()
    if process.returncode != 0:
        raise Exception(errors)

def write_video_mixed(initial_labels):
    if not os.path.isfile(args.media_output):
        write_video_mixed_reencode()
    else:
        write_video_mixed_increment(initial_labels)

def write_video_mixed_reencode():
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel] +
        list(itertools.chain.from_iterable([
            '-i', args.video_cache % (i + 1)
            ] for i in range(len(labels.labels))
        )) + [
        '-filter_complex', 'concat=n=%d:v=1:a=0' % len(labels.labels),
        '-y',
        args.video_output
        ],
        check=True
    )

def write_video_mixed_increment(initial_labels):
    labels_delta = sorted(
        set(labels.labels) - set(initial_labels),
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
        '-codec:v', 'copy',
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
                        args.media_output,
                        labels.labels[i0].output_start_point,
                        labels.labels[i - 1].output_final_point +
                            args.mixed_offset
                    )).encode()
                )
                i0 = -1
            if i < len(labels.labels):
                process.stdin.write((
                    'file \'%s\'\n' % (
                        args.video_cache % (i + 1)
                    )).encode()
                )
        else:
            if i0 == -1:
                i0 = i
    _, errors = process.communicate()
    if process.returncode != 0:
        raise Exception(errors)

def write_video_with_audio():
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        *(['-re'] if args.stream else []),
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        '-i', args.video_output,
        '-t', str(args.output_max_length or
            labels.labels[-1].output_final_point),
        '-i', args.audio_output,
        '-map', '0:v',
        '-map', '1:a',
        '-codec:v', 'copy',
        '-codec:a', 'aac',
        '-f', 'tee',
        '-use_fifo', '1',
        '|'.join(
            ('[f=%s%s]' % (
                args.output_format,
                ':flvflags=no_duration_filesize'
                    if args.output_format == 'flv' else ''
                ) if args.output_format else '') +
            (target if target != '-' else 'pipe:1')
            for target in (args.output
                if args.output else [args.media_output])
        ),
        '-y'
        ],
        check=True
    )

def write_video_batch():
    argv = write_video_batch_args()
    if args.play:
        conf_file = player_config()
        cmd = player_args(conf_file)
    else:
        cmd = 'cat '
    cmd += write_video_batch_cmd(argv)
    with tempfile.NamedTemporaryFile(suffix='.sh') as temp_file:
        temp_file.write(cmd.encode())
        temp_file.flush()
        os.system(f'bash "{temp_file.name}"')

def write_video_batch_cmd(argv):
    delay = args.output_max_length if args.output_max_length else 60
    tasks = int(args.time / delay) if args.loop else 1
    if args.queue == 1:
        args.queue_delay = 0
    return ' '.join(
        ('--{ ' if args.play else '') +
            '<( ' +
                ('sleep {}; '.format((i - 1 + args.queue_delay) * delay)
                    if i > 0 else '') +
                ('timeout --foreground {} '.format(args.queue * delay)
                    if args.no_wait else '') +
                'parallel --fg --ungroup --semaphore ' \
                    '-j{} '.format(args.queue) +
                'python "{}"'.format(
                    '" "'.join(
                        re.sub('"', r'\\\\\\"',
                            re.sub("([' ()&])", r'\\\1', arg))
                        for arg in argv + [
                            '--output-id', str(id),
                            '--output'] +
                                (['-'] if args.play else []) + [
                                target for target in args.output
                                if target != '-' or not args.play
                            ] + ([
                                '--subtitles-output',
                                args.subtitles_output % id
                            ] if args.subtitles else [])
                    )) +
            ') ' +
            (player_args_file(id) if args.play else '') +
        ('--} ' if args.play else '')
        for i in range(tasks)
        for id in [uuid.uuid1()]
    )

def write_video_batch_args():
    argv = list(sys.argv)
    argv.remove('--loop')
    argv[1:1] = ['--ppid', str(os.getpid())]
    if args.play:
        play_video_args(argv)
    return argv

def play_video_args(argv):
    argv.remove('--play')
    if '--save' not in argv:
        argv.append('--save')
    if '--reencode' not in argv and '--increment' not in argv:
        argv.append('--reencode')
    if '--output-quality' not in argv:
        argv.extend(['--output-quality', 'low'])
    if '--output-format' not in argv and args.output_format:
        argv.extend(['--output-format', args.output_format])
    if '--videos-max-number' not in argv and len(args.videos) <= 1:
        argv.extend(['--videos-max-number', '1'])
    if '--loglevel' not in argv:
        argv.extend(['--loglevel', 'quiet'])

def player_args(conf_file):
    return (
        'mpv ' +
        ('--input-conf=\'{}\' '.format(conf_file) if args.input else '') +
        ('--mute=yes ' if args.no_audio and args.no_video else '') +
        ('--no-audio ' if args.no_audio and not args.no_video else '') +
        ('--no-video ' if args.no_video else '') +
        '--cache=yes ' \
        '--fs '
    )
    return cmd

def player_args_file(id):
    return (
        ('--sub-file=\'{}\' '.format(args.subtitles_output % id)
            if args.subtitles else '') +
        ('--lavfi-complex=\'' \
            '[vid2]scale=iw/2:ih/2[v],' \
            '[vid1][v]overlay=W-w:H-h[vo]\' ' \
         '--external-file=\'{}\' '.format(args.input)
            if args.input else '')
    )

def player_config():
    conf_file = '%s.input.conf' % args.media_output
    if args.input:
        labels_backup = '%s.labels.txt' % args.media_output
        func = inspect.getsource(update_labels_filter).replace('\n', '\\n')
        call = "update_labels_filter('%s', '%s', ${=time-pos})"
        with open(conf_file, 'w') as f:
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
    return conf_file
