import itertools
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid

import beauty.mappings as mappings
import beauty.videos as videos
from . import args
from .effects import visual_effects
from .mappings import mappings_complete
from .videos import read_video

def write_video(previous_mappings):
    if not mappings_complete():
        return
    if args.reencode and args.increment:
        write_video_mixed(previous_mappings)
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
    for mapping in mappings.mappings:
        if mapping.source.url not in videos.videos:
            read_video(mapping.source.url)
    def apply(functions, x):
        y = x
        for f in functions:
            y = f(y)
        return y
    if args.output_width and args.output_height:
        padout_filter = ';'.join([
            '[%d:v]pad=%d:%d:(ow-iw)/2:(oh-ih)/2[v%d]' % (
                i,
                args.output_width,
                args.output_height,
                i
            ) for i in range(len(mappings.mappings))
            ] + [''.join(
                '[v%d]' % i for i in
                    range(len(mappings.mappings))
                )]
        )
    else:
        padout_filter = ''
    concat_filter = \
        ['concat=n=%d:v=1:a=0' % len(mappings.mappings)]
    effect_filter, effect_mapper = visual_effects()
    rotate_filter = \
        ['transpose=2'] if args.output_rotate else []
    filters = padout_filter + ','.join([
        *concat_filter,
        *effect_filter,
        *rotate_filter
    ])
    subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel,
        *(['-re'] if args.stream else []),
        *list(itertools.chain.from_iterable([
            '-ss', '{:.3f}'.format(mapping.source.start),
            '-t', '{:.3f}'.format(
                max(0,
                    apply(
                        effect_mapper, mapping.target.final
                    ) - apply(
                        effect_mapper, mapping.target.start
                    ) + args.reencode_offset
                )),
            '-i', videos.videos[mapping.source.url].url
            ] for mapping in mappings.mappings
            )),
        '-t', '{:.3f}'.format(
            args.output_length or
                mappings.mappings[-1].target.final),
        *(['-i', args.audio_output]
            if args.audio_output else []),
        '-filter_complex', filters + '[v]',
        '-map', '[v]',
        *(['-map', '%d:a' % len(mappings.mappings)]
            if args.audio_output else []),
        '-shortest',
        '-vsync', 'vfr',
        '-flags', '+global_header',
        '-codec:v', 'libx264',
        *(['-crf', '17']
            if args.output_quality == 'high'
            else ['-crf', '33']
                if args.output_quality == 'low'
            else []),
        *(['-preset', 'slow']
            if args.output_quality == 'high'
            else ['-preset', 'veryfast']
                if args.output_quality == 'low'
            else []),
        '-codec:a', 'copy' \
            if args.output_format != 'flv' else 'aac',
        '-f', 'tee',
        '-use_fifo', '1',
        '|'.join(
            ('[f=%s%s]' % (
                args.output_format,
                ':flvflags=no_duration_filesize'
                    if args.output_format == 'flv' else ''
                ) if args.output_format else '') +
            (target if target != '-' else 'pipe:1')
            for target in (
                args.output if args.output
                else [args.media_output]
            )
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
        ('file \'%s\'\n' % \
            args.video_cache % (i + 1)).encode()
        for i in range(len(mappings.mappings))
    )
    _, errors = process.communicate()
    if process.returncode != 0:
        raise Exception(errors)

def write_video_mixed(previous_mappings):
    if not os.path.isfile(args.media_output):
        write_video_mixed_reencode()
    else:
        write_video_mixed_increment(previous_mappings)

def write_video_mixed_reencode():
    process = subprocess.run([
        'ffmpeg',
        '-loglevel', args.loglevel] +
        list(itertools.chain.from_iterable([
            '-i', args.video_cache % (i + 1)
            ] for i in range(len(mappings.mappings))
        )) + [
        '-filter_complex',
            'concat=n=%d:v=1:a=0:unsafe=1' % \
                len(mappings.mappings),
        '-y',
        args.video_output
        ],
        check=True
    )

def write_video_mixed_increment(previous_mappings):
    mappings_delta = sorted(
        set(mappings.mappings) - set(previous_mappings),
        key=lambda mapping: mapping.target.start
    )
    if not mappings_delta:
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
    for i in range(len(mappings.mappings) + 1):
        if (i == len(mappings.mappings) or
            mappings.mappings[i] in mappings_delta):
            if i0 != -1:
                process.stdin.write((
                    'file \'%s\'\n' \
                    'inpoint %f\n' \
                    'outpoint %f\n' % (
                        args.media_output,
                        mappings.mappings[i0].target.start,
                        mappings.mappings[i - 1]. \
                            target.final + args.mixed_offset
                    )).encode()
                )
                i0 = -1
            if i < len(mappings.mappings):
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
        '-t', '{:.3f}'.format(
            args.output_length or
                mappings.mappings[-1].target.final),
        '-i', args.video_output,
        '-t', '{:.3f}'.format(
            args.output_length or
                mappings.mappings[-1].target.final),
        '-i', args.audio_output,
        '-map', '0:v',
        '-map', '1:a',
        '-codec:v', 'copy',
        '-codec:a', 'copy' \
            if args.output_format != 'flv' else 'aac',
        '-f', 'tee',
        '-use_fifo', '1',
        '|'.join(
            ('[f=%s%s]' % (
                args.output_format,
                ':flvflags=no_duration_filesize'
                    if args.output_format == 'flv' else ''
                ) if args.output_format else '') +
            (target if target != '-' else 'pipe:1')
            for target in (
                args.output if args.output
                else [args.media_output]
            )
        ),
        '-y'
        ],
        check=True
    )

def write_video_batch():
    argv = write_video_batch_args()
    if args.play:
        cmd = player_args_common()
    else:
        cmd = 'cat '
    cmd += write_video_batch_cmd(argv)
    with tempfile.NamedTemporaryFile(suffix='.sh') as file:
        file.write(cmd.encode())
        file.flush()
        os.system(f'bash "{file.name}"')

def write_video_batch_cmd(argv):
    delay = args.output_length if args.output_length \
        else args.loop_job_time if args.loop_job_time \
        else 60
    tasks = int(args.loop_time / delay) if args.loop else 1
    locks = os.path.join(
        tempfile.gettempdir(),
        'pid{}.lock%d'.format(os.getpid())
    )
    if args.loop_jobs == 1:
        args.loop_job_wait = 0
    return ' '.join(
        ('--{ ' if args.play else '') +
            '<( ' +
                ('sleep {}; '.format(
                    idx * args.loop_job_wait * delay
                    ) if args.loop_job_wait and
                        idx < args.loop_jobs else '') +
                'flock -o {} '.format(locks % idx) +
                'flock -o {} '.format(locks % (idx - 1)) +
                'parallel --semaphore --fg --ungroup ' +
                    '--jobs {} '.format(args.loop_jobs) +
                    ('--timeout {}'.format(
                        args.loop_jobs * delay
                        ) if args.loop_job_kill else '') +
                'flock -u {} '.format(locks % idx) +
                'python "{}"'.format(
                    '" "'.join(
                        re.sub('"', r'\\\\\\"',
                            re.sub("([' ()&])", r'\\\1', arg)
                        )
                        for arg in argv + [
                            '--output-id', str(id),
                            '--output'] +
                            (['-'] if args.play else []) + [
                                target
                                for target in args.output
                                if target != '-' or
                                    not args.play
                            ] + ([
                                '--subtitles-output',
                                args.subtitles_output % id
                            ] if args.output_subtitles
                                else []
                            )
                    )) +
            ') ' +
            (player_args_select(id) if args.play else '') +
        ('--} ' if args.play else '')
        for idx in range(tasks)
        for id in [uuid.uuid1()]
    )

def write_video_batch_args():
    argv = list(sys.argv)
    if '--loop' in argv:
        argv.remove('--loop')
    argv[1:1] = ['--loop-ppid', str(os.getpid())]
    if args.play:
        play_video_args(argv)
    return argv

def play_video_args(argv):
    if '--play' in argv:
        argv.remove('--play')
    if '--save' not in argv:
        argv.append('--save')
    if '--reencode' not in argv and \
        '--increment' not in argv:
        argv.append('--reencode')
    if '--output-quality' not in argv:
        argv.extend(['--output-quality', 'low'])
    if '--output-format' not in argv and \
        args.output_format:
        argv.extend(['--output-format', args.output_format])
    if '--videos-number' not in argv and \
        len(args.videos) <= 1:
        argv.extend(['--videos-number', '1'])
    if '--loglevel' not in argv:
        argv.extend(['--loglevel', 'quiet'])

def player_args_common():
    return (
        'mpv ' +
        ('--mute=yes ' \
            if args.no_audio and args.no_video else '') +
        ('--no-audio ' \
            if args.no_audio and not args.no_video else '') +
        ('--no-video ' \
            if args.no_video else '') +
        '--prefetch-playlist=yes ' \
        '--cache=yes ' \
        '--fs '
    )

def player_args_select(id):
    return (
        '--sub-file=\'{}\' '.format(
            args.subtitles_output % id
        ) if args.output_subtitles else ''
    )
