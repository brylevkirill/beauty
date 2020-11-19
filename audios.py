import collections
import itertools
import madmom.audio.chroma
import madmom.features.beats
import madmom.features.chords
import madmom.features.notes
import os
import pydub
import random
import shutil
import subprocess
import tempfile
import validators

from beauty import args
from labels import Label
from youtube import youtube_collections, youtube_playlists, youtube_video

def property(media_url, stream, prop):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'format=%s' % prop,
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
    return tempo_from_chords(audio_file_name)

def tempo_from_chords(audio_file_name):
    proc = madmom.features.chords.DeepChromaChordRecognitionProcessor()
    feat = madmom.audio.chroma.DeepChromaProcessor()(audio_file_name)
    intervals = [
        (e - s - (e - s) % 0.01) for (s, e, _) in proc(feat)] or [
        duration(audio_file_name)
    ]
    return 60 / collections.Counter(intervals).most_common(1)[0][0]

def tempo_from_beats(audio_file_name):
    ...

def read_audios():
    youtube_collections(args.audios, 'audio')
    youtube_playlists(args.audios)
    if not args.audios:
        return []
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

def read_audio(media_url):
    if not fetch_audio(media_url, args.audio_output):
        return False
    shape_audio(args.audio_output, length=args.output_max_length)
    return True

def fetch_audio(media_url, audio_file_name):
    try:
        process = subprocess.run([
            'youtube-dl',
            '--quiet',
            '--no-continue',
            '--extract-audio',
            '--audio-format', 'm4a',
            media_url,
            '-o',
            audio_file_name
            ],
            check=True,
            stderr=subprocess.PIPE
        )
        return True
    except subprocess.CalledProcessError as e:
        if any (m in e.stderr.decode() for m in [
            'This video',
            'YouTube said:'
        ]):
            return False
        else:
            raise e

def shape_audio(audio_file_name, length=None):
    sound = pydub.AudioSegment.from_file(audio_file_name)
    chunks = pydub.silence.detect_nonsilent(
        sound,
        min_silence_len=500,
        silence_thresh=-50)
    assert chunks
    start, final = chunks[0]
    start, final, total = start / 1000, final / 1000, len(sound) / 1000
    final = length if length and length < final else final
    if start != 0 or final != total:
        _, temp_file_name = tempfile.mkstemp(suffix='.m4a')
        process = subprocess.run([
            'ffmpeg',
            '-loglevel', args.loglevel,
            '-ss', str(start),
            '-to', str(final),
            '-i', audio_file_name,
            '-y',
            temp_file_name
            ],
            check=True
        )
        os.replace(temp_file_name, audio_file_name)

def create_labels():
    if (args.labels_from_chords_chroma or
        args.labels_from_chords_cnn):
        args.labels_from_chords = True
    if (args.labels_from_beats_detection or
        args.labels_from_beats_detection_crf or
        args.labels_from_beats_tracking or
        args.labels_from_beats_tracking_dbn):
        args.labels_from_beats = True
    if (args.labels_from_notes_rnn or
        args.labels_from_notes_cnn):
        args.labels_from_notes = True
    if (not args.labels_from_chords and
       not args.labels_from_beats and
       not args.labels_from_notes):
        args.labels_from_chords = True
        args.labels_from_beats = True
    points = sorted(set([
        0,
        *(points_from_chords(args.audio_output)
            if args.labels_from_chords else []),
        *(points_from_beats(args.audio_output)
            if args.labels_from_beats else []),
        *(points_from_notes(args.audio_output)
            if args.labels_from_notes else []),
        duration(args.audio_output)
    ]))
    if args.output_max_length:
        points[:] = [
            p for p in points
            if p < args.output_max_length
            ] + [args.output_max_length]
    if args.labels_joints > 1:
        points[:] = points[::args.labels_joints]
    if args.labels_splits > 1:
        points[:] = [
            points[i] + (points[i + 1] - points[i]) * j / args.labels_splits
            for i in range(len(points) - 1)
            for j in range(args.labels_splits)
        ]
    if args.labels_max_length:
        points[:] = [
            points[i] + j * args.labels_max_length
            for i in range(len(points) - 1)
            for j in range(1 +
                int((points[i + 1] - points[i]) / args.labels_max_length))
        ]
    if args.labels_min_length:
        p = [points[0]]
        points[1:-1] = [
            points[i]
            for i in range(1, len(points) - 1)
            if points[i] - p[0] >= args.labels_min_length and
                points[-1] - points[i] >= args.labels_min_length and
                not p.remove(p[0]) and not p.append(points[i])
        ]
    return [
        Label(
            output_start_point=points[i],
            output_final_point=points[i + 1]
        )
        for i in range(len(points) - 1)
    ]

def points_from_chords(audio_file_name):
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

def points_from_beats(audio_file_name):
    if (not args.labels_from_beats_detection and
        not args.labels_from_beats_detection_crf and
        not args.labels_from_beats_tracking and
        not args.labels_from_beats_tracking_dbn):
        args.labels_from_beats_tracking = True
        args.labels_joints = 4
    proc = []
    if args.labels_from_beats_detection:
        proc.append(madmom.features.beats.BeatDetectionProcessor(
            fps=100
        ))
    if args.labels_from_beats_detection_crf:
        proc.append(madmom.features.beats.CRFBeatDetectionProcessor(
            min_bpm=50,
            max_bpm=100,
            fps=100
        ))
    if args.labels_from_beats_tracking:
        proc.append(madmom.features.beats.BeatTrackingProcessor(
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

def points_from_notes(audio_file_name):
    if (not args.labels_from_notes_rnn and
        not args.labels_from_notes_cnn):
        args.labels_from_notes_rnn = True
    proc = []
    act = []
    if args.labels_from_notes_rnn:
        proc.append(madmom.features.notes.NotePeakPickingProcessor(
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
