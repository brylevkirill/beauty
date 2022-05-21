import aubio
import collections
import itertools
import madmom.audio.chroma
import madmom.features.beats
import madmom.features.chords
import madmom.features.notes
import numpy
import pydub
import random
import shutil
import subprocess
import tempfile
import validators

from . import args
from .mappings import Mapping, Resource
from .youtube import youtube_collections, youtube_playlists, youtube_video

def read():
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
            if args.mappings_reinit or args.visual_effect_speedup:
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

def read_audio(url):
    if not fetch_audio(url, args.audio_output):
        return False
    shape_audio(args.audio_output, length=args.output_length)
    return True

def fetch_audio(url, file_name):
    try:
        process = subprocess.run([
            'yt-dlp',
            '--quiet',
            '--no-warnings',
            '--no-continue',
            '--extract-audio',
            '--audio-format', 'm4a',
            url,
            '-o',
            file_name
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

def shape_audio(file_name, length=None):
    sound = pydub.AudioSegment.from_file(file_name)
    chunks = pydub.silence.detect_nonsilent(
        sound,
        min_silence_len=500,
        silence_thresh=-50)
    assert chunks
    start, final = chunks[0]
    start, final, total = start / 1000, final / 1000, len(sound) / 1000
    final = length if length and length < final else final
    if start != 0 or final != total:
        temp_file = tempfile.NamedTemporaryFile(suffix='.m4a', delete=False)
        temp_file.close()
        process = subprocess.run([
            'ffmpeg',
            '-loglevel', args.loglevel,
            '-ss', str(start),
            '-to', str(final),
            '-i', file_name,
            '-y',
            temp_file.name
            ],
            check=True
        )
        shutil.move(temp_file.name, file_name)

def generate_mappings():
    if (args.mappings_from_chords_chroma or
        args.mappings_from_chords_cnn):
        args.mappings_from_chords = True
    if (args.mappings_from_beats_detection or
        args.mappings_from_beats_detection_crf or
        args.mappings_from_beats_tracking or
        args.mappings_from_beats_tracking_dbn):
        args.mappings_from_beats = True
    if (args.mappings_from_notes_rnn or
        args.mappings_from_notes_cnn):
        args.mappings_from_notes = True
    if (not args.mappings_from_chords and
       not args.mappings_from_beats and
       not args.mappings_from_notes and
       not args.mappings_from_onsets):
        args.mappings_from_chords = True
        args.mappings_from_beats = True
    points = sorted(set([
        0,
        *(points_from_chords(args.audio_output)
            if args.mappings_from_chords else []),
        *(points_from_beats(args.audio_output)
            if args.mappings_from_beats else []),
        *(points_from_notes(args.audio_output)
            if args.mappings_from_notes else []),
        *(points_from_onsets(args.audio_output)
            if args.mappings_from_onsets else []),
        duration(args.audio_output)
    ]))
    if args.output_length:
        points[:] = [
            p for p in points
            if p < args.output_length
            ] + [args.output_length]
    if args.mappings_joints and args.mappings_joints > 1:
        points[:] = points[:-1:args.mappings_joints] + [points[-1]]
    if args.mappings_splits and args.mappings_splits > 1:
        points[:] = [
            points[i] + (points[i + 1] - points[i]) * j / args.mappings_splits
            for i in range(len(points) - 1)
            for j in range(args.mappings_splits)
        ] + [points[-1]]
    if args.mappings_max_interval:
        points[:] = [
            points[i] + j * args.mappings_max_interval
            for i in range(len(points) - 1)
            for j in range(
                int((points[i + 1] - points[i]) /
                    args.mappings_max_interval + 1)
            )
        ]
    if args.mappings_min_interval:
        p = [points[0]]
        points[1:-1] = [
            points[i]
            for i in range(1, len(points) - 1)
            if points[i] - p[0] >= args.mappings_min_interval and
                points[-1] - points[i] >= args.mappings_min_interval and
                not p.remove(p[0]) and not p.append(points[i])
        ]
    return [
        Mapping(
            target=Resource(
                start=points[i],
                final=points[i + 1]
            )
        )
        for i in range(len(points) - 1)
    ]

def points_from_chords(file_name):
    if (not args.mappings_from_chords_chroma and
        not args.mappings_from_chords_cnn):
        args.mappings_from_chords_chroma = True
    proc = []
    feat = []
    if args.mappings_from_chords_chroma:
        proc.append(
            madmom.features.chords.DeepChromaChordRecognitionProcessor()
        )
        feat.append(madmom.audio.chroma.DeepChromaProcessor()(
            file_name
        ))
    if args.mappings_from_chords_cnn:
        proc.append(
            madmom.features.chords.CRFChordRecognitionProcessor()
        )
        feat.append(madmom.features.chords.CNNChordFeatureProcessor()(
            file_name
        ))
    return set(itertools.chain.from_iterable(
        (e for (_, e, _) in p(f)) for (p, f) in zip(proc, feat)
    ))

def points_from_beats(file_name):
    if (not args.mappings_from_beats_detection and
        not args.mappings_from_beats_detection_crf and
        not args.mappings_from_beats_tracking and
        not args.mappings_from_beats_tracking_dbn):
        args.mappings_from_beats_tracking = True
        if not args.mappings_joints:
            args.mappings_joints = 4
    proc = []
    if args.mappings_from_beats_detection:
        proc.append(madmom.features.beats.BeatDetectionProcessor(
            fps=100
        ))
    if args.mappings_from_beats_detection_crf:
        proc.append(madmom.features.beats.CRFBeatDetectionProcessor(
            min_bpm=50,
            max_bpm=100,
            fps=100
        ))
    if args.mappings_from_beats_tracking:
        proc.append(madmom.features.beats.BeatTrackingProcessor(
            fps=100
        ))
    if args.mappings_from_beats_tracking_dbn:
        proc.append(madmom.features.beats.DBNBeatTrackingProcessor(
            min_bpm=50,
            max_bpm=100,
            fps=100
        ))
    return set(itertools.chain.from_iterable(
        p(madmom.features.beats.RNNBeatProcessor()(file_name))
        for p in proc
    ))

def points_from_notes(file_name):
    if (not args.mappings_from_notes_rnn and
        not args.mappings_from_notes_cnn):
        return points_from_notes_aubio(file_name)
    proc = []
    act = []
    if args.mappings_from_notes_rnn:
        proc.append(madmom.features.notes.NotePeakPickingProcessor(
            fps=100,
            pitch_offset=21
        ))
        act.append(madmom.features.notes.RNNPianoNoteProcessor()(
            file_name
        ))
    if args.mappings_from_notes_cnn:
        proc.append(madmom.features.notes.ADSRNoteTrackingProcessor())
        act.append(madmom.features.notes.CNNPianoNoteProcessor()(
            file_name
        ))
    return set(itertools.chain.from_iterable(
        (t for (t, *_) in p(a)) for (p, a) in zip(proc, act)
    ))

def points_from_notes_aubio(file_name):
    source = aubio_source(file_name)
    notes = aubio.notes(samplerate=source.samplerate)
    notes.set_minioi_ms(args.mappings_from_notes_min_length * 1000)
    notes.set_silence(args.mappings_from_notes_min_volume)
    points = []
    frames = 0
    while True:
        samples, read = source()
        if notes(samples)[0] != 0:
            points.append(frames / source.samplerate)
        frames += read
        if read < source.hop_size:
            break
    return set(points)

def points_from_onsets(file_name):
    source = aubio_source(file_name)
    onset = aubio.onset(
        args.mappings_from_onsets_method,
        samplerate=source.samplerate)
    onset.set_threshold(args.mappings_from_onsets_threshold)
    onset.set_minioi_ms(args.mappings_from_onsets_min_length * 1000)
    onset.set_silence(args.mappings_from_onsets_min_volume)
    points = []
    while True:
        samples, read = source()
        if onset(samples):
            points.append(onset.get_last() / source.samplerate)
        if read < source.hop_size:
            break
    return set(points)

def property(url, stream, name):
    process = subprocess.run([
        'ffprobe',
        '-select_streams', stream,
        '-show_entries', 'format=%s' % name,
        '-of', 'default=noprint_wrappers=1:nokey=1',
        '-v', 'quiet',
        url
        ],
        check=True,
        stdout=subprocess.PIPE
    )
    return float(process.stdout.decode())

def duration(url):
    return property(url, 'a:0', 'duration')

def tempo(file_name):
    return tempo_from_beats_madmom(file_name)

def tempo_from_beats_madmom(file_name):
    proc = madmom.features.tempo.TempoEstimationProcessor(fps=100)
    act = madmom.features.beats.RNNBeatProcessor()(file_name)
    return proc(act)[0][0]

def tempo_from_beats_aubio(file_name):
    source = aubio_source(file_name)
    win_s, hop_s, samplerate = 1024, 512, 44100
    tempi = aubio.tempo("specdiff", win_s, hop_s, samplerate)
    beats = []
    while True:
        samples, read = source()
        is_beat = tempi(samples)
        if is_beat:
            this_beat = tempi.get_last_s()
            beats.append(this_beat)
        if read < hop_s:
            break
    bpms = 60 / numpy.diff(beats)
    return numpy.median(bpms)

def tempo_from_chords(file_name):
    proc = madmom.features.chords.DeepChromaChordRecognitionProcessor()
    feat = madmom.audio.chroma.DeepChromaProcessor()(file_name)
    intervals = [
        (e - s - (e - s) % 0.01) for (s, e, _) in proc(feat)] or [
        duration(file_name)
    ]
    return 60 / collections.Counter(intervals).most_common(1)[0][0]

def aubio_source(file_name):
    sound = pydub.AudioSegment.from_file(file_name)
    temp_file = tempfile.NamedTemporaryFile(suffix='.wav')
    sound.export(temp_file.name, format='wav')
    samplerate, hop_s = 44100, 512
    return aubio.source(temp_file.name, samplerate, hop_s)
