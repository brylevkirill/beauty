import collections
import itertools
import madmom.audio.chroma
import madmom.features.beats
import madmom.features.chords
import madmom.features.notes
import os
import random
import shutil
import subprocess
import validators

from beauty import args
from labels import Label
from youtube import youtube_collections, youtube_playlists, youtube_video

def property(media_url, stream, prop):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'stream=%s' % prop,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        media_url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return float(process.stdout.decode())

def duration(audio_url):
    return property(audio_url, 'a:0', 'duration')

def tempo(audio_file_name):
    proc = madmom.features.chords.DeepChromaChordRecognitionProcessor()
    feat = madmom.audio.chroma.DeepChromaProcessor()(audio_file_name)
    intervals = [
        (e - s - (e - s) % 0.01) for (s, e, _) in proc(feat)] or [
        duration(audio_file_name)
    ]
    return collections.Counter(intervals).most_common(1)[0][0]

def read_audios():
    youtube_collections(args.audios, 'audio')
    youtube_playlists(args.audios)
    if not args.audios:
        return
    while True:
        audio = random.sample(args.audios, 1)[0]
        if not validators.url(audio):
            shutil.copyfile(audio, args.audio_output)
            break
        else:
            if args.labels_reinit or args.visual_effect:
                if read_audio(audio):
                    break
            else:
                if 'youtube.com' in audio or 'youtu.be' in audio:
                    video = youtube_video(
                        audio,
                        filter='bestaudio[ext=m4a]',
                        strict=False
                    )
                    if video:
                        args.audio_output = video[0]
                        break
    return [audio]

def read_audio(audio):
    if os.path.isfile(args.audio_output):
        os.remove(args.audio_output)
    try:
        process = subprocess.run([
            'youtube-dl',
            '--quiet',
            '--extract-audio',
            '--audio-format', 'm4a',
            audio,
            '-o',
            args.audio_output[:-4] + '.mp4'
            ],
            check=True,
            stderr=subprocess.PIPE
        )
    except subprocess.CalledProcessError as e:
        if any (m in e.stderr.decode() for m in [
            'This video is unavailable',
            'This video has been removed',
            'YouTube said:'
        ]):
            return False
        else:
            raise e
    if args.output_max_length:
        output = args.audio_output + '.edit.m4a'
        process = subprocess.run([
            'ffmpeg',
            '-loglevel', args.loglevel,
            '-t', str(args.output_max_length),
            '-i', args.audio_output,
            output
            ],
            check=True
        )
        os.replace(output, args.audio_output)
    return True

def create_labels():
    if (not args.labels_from_chords and
       not args.labels_from_beats and
       not args.labels_from_notes):
        args.labels_from_chords = True
    L = sorted(set([
        0,
        *(labels_from_chords(args.audio_output)
            if args.labels_from_chords else []),
        *(labels_from_beats(args.audio_output)
            if args.labels_from_beats else []),
        *(labels_from_notes(args.audio_output)
            if args.labels_from_notes else []),
        duration(args.audio_output)
    ]))
    if args.output_max_length:
        L[:] = [l for l in L if l < args.output_max_length
            ] + [args.output_max_length]
    if args.labels_joins > 1:
        L[:] = L[::args.labels_joins]
    if args.labels_splits > 1:
        L[:] = [
            L[i] + (L[i + 1] - L[i]) * j / args.labels_splits
            for i in range(len(L) - 1)
            for j in range(args.labels_splits)
        ]
    if args.labels_max_length:
        L[:] = [
            L[i] + j * args.labels_max_length
            for i in range(len(L) - 1)
            for j in range(1 +
                int((L[i + 1] - L[i]) / args.labels_max_length))
        ]
    if args.labels_min_length:
        L_last = [L[0]]
        L[1:-1] = [
            L[i]
            for i in range(1, len(L) - 1)
            if L[i] - L_last[0] >= args.labels_min_length and
                L[-1] - L[i] >= args.labels_min_length and
                not L_last.remove(L_last[0]) and not L_last.append(L[i])
        ]
    return [
        Label(
            output_start_point=L[i],
            output_final_point=L[i + 1]
        )
        for i in range(len(L) - 1)
    ]

def labels_from_chords(audio_file_name):
    if (not args.labels_from_chords_chroma and
        not args.labels_from_chords_cnn):
        args.labels_from_chords_chroma = True
    proc = []
    feat = []
    if args.labels_from_chords_chroma:
        proc.append(
            madmom.features.chords.DeepChromaChordRecognitionProcessor()
        )
        feat.append(madmom.audio.chroma.DeepChromaProcessor()(
            audio_file_name
        ))
    if args.labels_from_chords_cnn:
        proc.append(
            madmom.features.chords.CRFChordRecognitionProcessor()
        )
        feat.append(madmom.features.chords.CNNChordFeatureProcessor()(
            audio_file_name
        ))
    return set(itertools.chain.from_iterable(
        (e for (_, e, _) in p(f)) for (p, f) in zip(proc, feat)
    ))

def labels_from_beats(audio_file_name):
    if (not args.labels_from_beats_detection and
        not args.labels_from_beats_tracking and
        not args.labels_from_beats_detection_crf and
        not args.labels_from_beats_tracking_dbn):
        args.labels_from_beats_tracking_dbn = True
    proc = []
    if args.labels_from_beats_detection:
        proc.append(madmom.features.beats.BeatDetectionProcessor(
            fps=100
        ))
    if args.labels_from_beats_tracking:
        proc.append(madmom.features.beats.BeatTrackingProcessor(
            fps=100
        ))
    if args.labels_from_beats_detection_crf:
        proc.append(madmom.features.beats.CRFBeatDetectionProcessor(
            min_bpm=50,
            max_bpm=100,
            fps=100
        ))
    if args.labels_from_beats_tracking_dbn:
        proc.append(madmom.features.beats.DBNBeatTrackingProcessor(
            min_bpm=50,
            max_bpm=100,
            fps=100
        ))
    return set(itertools.chain.from_iterable(
        p(madmom.features.beats.RNNBeatProcessor()(audio_file_name))
        for p in proc
    ))

def labels_from_notes(audio_file_name):
    if (not args.labels_from_notes_rnn and
        not args.labels_from_notes_cnn):
        args.labels_from_notes_rnn = True
    proc = []
    act = []
    if args.labels_from_notes_rnn:
        proc.append(madmom.features.notes.NoteOnsetPeakPickingProcessor(
            fps=100,
            pitch_offset=21
        ))
        act.append(madmom.features.notes.RNNPianoNoteProcessor()(
            audio_file_name
        ))
    if args.labels_from_notes_cnn:
        proc.append(madmom.features.notes.ADSRNoteTrackingProcessor())
        act.append(madmom.features.notes.CNNPianoNoteProcessor()(
            audio_file_name
        ))
    return set(itertools.chain.from_iterable(
        (t for (t, *_) in p(a)) for (p, a) in zip(proc, act)
    ))
