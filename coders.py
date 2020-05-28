import itertools
import os
import signal
import subprocess
import sys

import labels
import videos
from beauty import args, output
from videos import read_video, visual_effects

def write_video(labels_before):
    if not labels.labels_created():
        return
    if args.reencode and args.increment:
        write_video_mixed(labels_before)
    elif args.reencode:
        write_video_reencode()
    elif args.increment:
        write_video_increment()
    if args.output != '-':
        if args.audios:
            write_video_with_audio()
            if os.path.isfile(args.audio_output):
                os.remove(args.audio_output)
            os.remove(args.video_output)
        else:
            os.replace(args.video_output, output)

def write_video_reencode():
    for l in labels.labels:
        if l.input_file_name not in videos.videos:
            read_video(l.input_file_name)
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
            '-ss', str(l.input_start_pos),
            '-t', '%.3f' % max(0,
                apply(effects_mappers, l.output_end_pos) -
                apply(effects_mappers, l.output_start_pos) +
                args.offset_reencode),
            '-i', videos.videos[l.input_file_name].url
            ] for l in labels.labels
                   )) + [
        '-t', str(args.output_max_length or
            labels.labels[-1].output_end_pos),
        '-i', args.audio_output,
        '-filter_complex', ', '.join([concat_filter] + effects_filters),
        '-shortest',
        '-c:v', 'libx264',
#       '-crf', '33',
        '-f', 'matroska',
        '-y',
        args.video_output if args.output != '-' else '-'
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
        '-c', 'copy',
        '-an',
        '-y', args.video_output
        ],
        stdin=subprocess.PIPE
    )
    process.stdin.writelines(
        ('file \'%s\'\n' % args.cache % (i + 1)).encode()
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
            '-i', args.cache % (i + 1)
            ] for i in range(len(labels.labels))
        )) + [
        '-filter_complex', 'concat=n=%d' % len(labels.labels),
        '-an',
        '-y', args.video_output
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
        '-c', 'copy',
        '-an',
        '-y', args.video_output
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
                    labels.labels[i0].output_start_pos,
                    labels.labels[i - 1].output_end_pos +
                        args.offset_mixed
                    )).encode()
                )
                i0 = -1
            if i < len(labels.labels):
                process.stdin.write((
                    'file \'%s\'\n' % args.cache % (i + 1)
                    ).encode()
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
        '-t', str(args.output_max_length or
            labels.labels[-1].output_end_pos),
        '-i', args.video_output,
        '-t', str(args.output_max_length or
            labels.labels[-1].output_end_pos),
        '-i', args.audio_output,
        '-c', 'copy',
        '-y', output
        ],
        check=True
    )

def play_video():
    sys.argv.remove('--play')
    if args.loop:
        sys.argv.remove('--loop')
    delay = args.output_max_length if args.output_max_length else 60
    tasks = int(args.time / delay)
    queue = os.cpu_count() // 2
    video = '%d.mp4'
    for i in range(tasks):
        if os.path.isfile(video % i):
            os.remove(video % i)
    command = (
        'bash -c "' \
            'mpv --fs ' + ' '.join(
                '--{ <(' \
                    'sleep %d; ' \
                    'timeout --foreground %f ' \
                        'parallel --semaphore -j %d --fg %s; ' \
                    'cat %s' \
                ') %s --} ' % (
                    max((i - 0.5) * delay, 0),
                    queue * delay,
                    queue,
                    'python \'%s\' --output %s' % (
                        '\' \''.join(sys.argv),
                        video % i
                    ),
                    video % i,
                    '--sub-file \'%s\'' %
                        args.subtitles_output % video % i
                        if args.subtitles else ''
                )
                for i in range(tasks if args.loop else 1)
            ) + '' \
        '"'
    )
    os.system(command)
