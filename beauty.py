import argparse
import collections
import cv2
import datetime
import dlib
import functools
import itertools
import madmom.audio.chroma
import madmom.features.beats
import madmom.features.chords
import madmom.features.notes
import math
import multiprocessing.pool
import os
import random
import scipy.optimize
import subprocess
import sys
import tempfile
import time
import validators
import warnings

parser = argparse.ArgumentParser(
    formatter_class = argparse.ArgumentDefaultsHelpFormatter
)
def arg(*args, **kwargs):
	kwargs['action'] = 'store' if 'type' in kwargs else 'store_true'
	for a in args:
		if a.startswith('--'):
			kwargs['dest'] = a[2:].replace('-', '_')
	parser.add_argument(*args, **kwargs)

arg('-n', '--new-labels')
arg('-l', '--labels', metavar = '<labels file>', type = str)
opt = '<file|URL> | <YT playlist URL> | "ytsearch"[""|<N>|"all"]":"<query>"'
arg('-a', '--audios', metavar = '(%s | "orchestra")' % opt,
    type = str, nargs = '+', default = [])
arg('-v', '--videos', metavar = '(%s | "night sky"|"flowers"|"girls")' % opt,
    type = str, nargs = '+', default = [])
arg('-o', '--output', metavar = '<file> | "-" (stdout)', type = str)

arg('-m', '--videos-max-number', type = int)
arg('-d', '--output-max-length', type = float)
arg('-f', '--output-format', type = str, default = "mp4")
arg('-r', '--reencode')
arg('-i', '--increment')

arg('--create-labels-min-length', type = float, default = 0.2)
arg('--create-labels-max-length', type = float)
arg('--create-labels-joins', type = int, default = 1)
arg('--create-labels-splits', type = int, default = 1)
arg('--create-labels-from-chords')
arg('--create-labels-from-chords-chroma')
arg('--create-labels-from-chords-cnn')
arg('--create-labels-from-beats')
arg('--create-labels-from-beats-detection')
arg('--create-labels-from-beats-detection-crf')
arg('--create-labels-from-beats-tracking')
arg('--create-labels-from-beats-tracking-dbn')
arg('--create-labels-from-notes')
arg('--create-labels-from-notes-rnn')
arg('--create-labels-from-notes-cnn')

arg('--visual-filter-chrono')
arg('--visual-filter-drop-black-frame')
arg('--visual-filter-drop-hard-cuts')
arg('--visual-filter-drop-hard-cuts-prob', type = float, default = 0.05)
arg('--visual-filter-drop-slow-pace')
arg('--visual-filter-drop-slow-pace-prob', type = float, default = 0.02)
arg('--visual-filter-drop-slow-pace-rate', type = float, default = 0.2)
arg('--visual-filter-drop-face-less')

arg('--visual-effect-speedup')
arg('--visual-effect-speedup-tempo-multi', type = float, default = 1)
arg('--visual-effect-zooming')

arg('--video-output', type = str, default = '%s.video')
arg('--audio-output', type = str, default = '%s.audio')
arg('--cache', metavar = '<cache file>', type = str, default = '%d.mp4')
arg('--offset-reencode', type = float, default = -0.0415)
arg('--offset-increment', type = float, default = -0.0245)
arg('--offset-mixed', type = float, default = -0.045)

args = parser.parse_args()

output = args.output if args.output != '-' else 'stdout.mp4'
if not output.endswith('.' + args.output_format):
	args.output_format = output[output.rfind('.') + 1:]
args.video_output = args.video_output % output + '.' + args.output_format
args.audio_output = args.audio_output % output + '.m4a'
if not args.labels:
	args.labels = output + '.labels.txt'

Label = collections.namedtuple('Label', '''
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos
    ''')
labels = multiprocessing.Manager().list()

Video = collections.namedtuple('Video', '''
    url
    duration
    ''')
videos = multiprocessing.Manager().dict()

# implemented functionality:
# - reading audios & videos
# - YT videos/lists/search
# - reading/writing labels
# - creating labels (audio)
# - creating labels (video)
# - applying visual filters
# - applying visual effects
# - encoding/writing videos (reencoding/incrementing)

def main():
	random.seed(time.time())
	if not args.reencode and not args.increment:
		args.reencode = True
	if args.new_labels:
		collections()
	else:
		read_labels()
	read_audios()
	if not labels:
		if not args.audios:
			raise Exception('No audio file names or URLs given.')
		create_labels_audio()
	read_videos()
	labels_before = list(labels)
	create_labels_video()
	write_video(labels_before)

def collections():
	def populate(items, collection):
		if not items:
			items.add(collection.values()[
			    random.randint(0, len(collection) - 1)])
		else:
			for item in list(items):
				if item in collection:
					items.append(collection[item])
					items.remove(item)
	audios = {
	    'orchestra': 'https://youtube.com/playlist?' \
	        'list=PL659KIPAkeqgZtrIadb7YXGlFJBqZp9SX'
	}
	populate(args.audios, audios)
	videos = {
	    'night sky': 'https://youtube.com/playlist?' \
	        'list=PL659KIPAkeqhsK80VGeiQ4g06mdYcJxt7',
	    'flowers': 'https://youtube.com/playlist?' \
	        'list=PL659KIPAkeqj_VlAKEuFRpHvCkl-03Fw1',
	    'girls': 'https://youtube.com/playlist?' \
	        'list=PL659KIPAkeqjaerr91OSBWPHRFbkY5jaD'
	}
	populate(args.videos, videos)

def read_playlists(items, populate = True):
	for item in list(items):
		if (validators.url(item) and 'youtube.com/playlist' in item or
		    item.startswith('ytsearch') or
		    item.startswith('ytdl://ytsearch')
		):
			items.remove(item)
			if populate:
				if item.startswith('ytdl://ytsearch'):
					item = item[7:]
				items.extend(youtube_playlist(item))

def read_audios():
	read_playlists(args.audios)
	if not args.audios:
		return
	audio = random.sample(args.audios, 1)[0]
	if not validators.url(audio):
		args.audio_output = audio
	else:
		if not labels:
			if os.path.isfile(args.audio_output):
				os.remove(args.audio_output)
			process = subprocess.run([
			    'youtube-dl',
			    '--quiet',
			    '--extract-audio',
			    '--audio-format', 'm4a',
			    audio,
			    '-o',
			    args.audio_output[:-4] + '.mp4'
			    ],
			    check = True
			)
		else:
			if 'youtube.com' in audio or 'youtu.be' in audio:
				args.audio_output = youtube_video(
				    audio, filter = 'bestaudio[ext=m4a]').url

def read_videos():
	if labels_created() and args.increment:
		return
	read_playlists(args.videos, not labels_created())
	if args.videos_max_number and len(args.videos) > args.videos_max_number:
		args.videos = random.sample(args.videos, args.videos_max_number)
	for l in labels:
		if (l.input_file_name is not None and
		    l.input_file_name not in args.videos):
			args.videos.append(l.input_file_name)
	if not args.videos:
		raise Exception('No video file names or URLs given.')
	pool = multiprocessing.pool.ThreadPool(len(args.videos))
	res = [pool.apply_async(read_video, (v, False)) for v in args.videos]
	pool.close()
	pool.join()
	assert all(r.get() is None for r in res)

def read_video(video_file_name, strict = True):
	if (validators.url(video_file_name) and
	    'youtube.com' in video_file_name or 'youtu.be' in video_file_name):
		video = youtube_video(video_file_name, strict = strict)
		if video is not None:
			videos[video_file_name] = video
	else:
		videos[video_file_name] = Video(
		    url = video_file_name,
		    duration = duration(video_file_name, 'v:0')
		)

def check_media_url(url):
	process = subprocess.run([
	    'ffprobe',
	    '-v', 'quiet',
	    url
	    ],
	    check = False
	)
	return process.returncode == 0

def youtube_video(
    url,
    filter = 'bestvideo[ext=mp4][width=1920][height=1080]',
    strict = True):
	try:
		process = subprocess.run([
		    'youtube-dl',
		    '--get-url',
		    '--get-duration',
		    '-f', filter,
		    '--youtube-skip-dash-manifest',
		    url
		    ],
		    check = True,
		    stdout = subprocess.PIPE,
		    stderr = subprocess.PIPE
		)
	except subprocess.CalledProcessError as e:
		if not strict:
			if any (m in e.stderr.decode() for m in [
			    'This video is unavailable',
			    'requested format not available'
			]):
				return None
		raise e
	output = process.stdout.decode().splitlines()
	variants = [Video(
	        url = url,
	        duration = parse_timestamp(duration)
	    )
	    for (url, duration) in zip(*[iter(output)] * 2)
	    if check_media_url(url)
	]
	if strict and not variants:
		raise Exception('Can\'t read "%s".' % url)
	return variants[0] if variants else None

def youtube_playlist(url):
	process = subprocess.run([
	    'youtube-dl',
	    '--get-title',
	    '--get-id',
	    '--flat-playlist',
	    url
	    ],
	    check = True,
	    stdout = subprocess.PIPE
	)
	output = process.stdout.decode().splitlines()
	return [
	    'http://youtu.be/' + id
	    for (title, id) in zip(*[iter(output)] * 2)
	    if (not url.startswith('ytsearch') or
	        all (word.lower() in title.lower()
	            for word in url[url.index(':') + 1:].split()
		)
	    )
	]

def property(media_file_name, stream, prop):
	process = subprocess.run([
	    'ffprobe',
	    '-select_streams', stream,
	    '-show_entries', 'stream=%s' % prop,
	    '-of', 'default=noprint_wrappers=1:nokey=1',
	    '-v', 'quiet',
	    media_file_name
	    ],
	    check = True,
	    stdout = subprocess.PIPE
	)
	return float(process.stdout.decode())

def duration(media_file_name, stream):
	if validators.url(media_file_name) and stream == 'v:0':
		if media_file_name not in videos:
			read_video(media_file_name)
		return videos[media_file_name].duration
	return property(media_file_name, stream, 'duration')

def frames_number(video_file_name):
	return property(video_file_name, 'v:0', 'nb_frames')

def tempo(audio_file_name):
	proc = madmom.features.chords.DeepChromaChordRecognitionProcessor()
	feat = madmom.audio.chroma.DeepChromaProcessor()(audio_file_name)
	intervals = [
	    (e - s - (e - s) % 0.01) for (s, e, _) in proc(feat)] or [
	    duration(audio_file_name, 'a:0')
	]
	return collections.Counter(intervals).most_common(1)[0][0]

def parse_timestamp(s):
	try:
		return float(s)
	except ValueError:
		pass
	t = s.split(':')
	if t[1:] and int(t[0]) >= 60:
		s = ':'.join([
		    str(int(t[0]) // 60), str(int(t[0]) % 60).zfill(2), *t[1:]
		])
	try:
		t = datetime.datetime.strptime(s, '%H:%M:%S.%f')
	except ValueError:
		try:
			t = datetime.datetime.strptime(s, '%H:%M:%S')
		except ValueError:
			t = datetime.datetime.strptime(s, '%M:%S')
	return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond * 0.000001

def format_timestamp(t):
	return datetime.datetime.utcfromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]

def parse_label(s):
	t = s.split('\t')
	if t[2:] and not os.path.isfile(t[2]) and not validators.url(t[2]):
		raise ValueError('Invalid value "%s".' % t[2:])
	return Label(
	    output_start_pos = parse_timestamp(t[0]),
	    output_end_pos = parse_timestamp(t[1]),
	    input_file_name = t[2] if t[2:] else None,
	    input_start_pos = parse_timestamp(t[3]) if t[3:] else -1,
	    input_end_pos = parse_timestamp(t[4]) if t[4:] else -1
	)

def format_label(l: Label):
	return (format_timestamp(l.output_start_pos) +
	    '\t' + format_timestamp(l.output_end_pos) +
	    ('\t' + l.input_file_name
	        if l.input_file_name else '') +
	    ('\t' + format_timestamp(l.input_start_pos)
	        if l.input_start_pos != -1 else '') +
	    ('\t' + format_timestamp(l.input_end_pos)
	        if l.input_end_pos != -1 else '') + '\n'
	)

def read_labels():
	labels[:] = [parse_label(s) for s in
	    open(args.labels).read().splitlines()
	    ] if os.path.isfile(args.labels) else []

def write_labels():
	open(args.labels, 'w').writelines(format_label(l) for l in labels)
	write_titles()

def write_titles():
	open(output + '.srt', 'w').writelines(
	    '%d\n%s --> %s\n%d\n\n' % (
	        i + 1,
	        format_timestamp(labels[i].output_start_pos),
	        format_timestamp(labels[i].output_end_pos),
	        i + 1)
	    for i in range(len(labels))
	)

def labels_created():
	return all (
	    l.input_file_name is not None and
	    l.input_start_pos != -1 and
	    l.input_end_pos != -1
	    for l in labels)

def create_labels_audio():
	if (not args.create_labels_from_chords and
	   not args.create_labels_from_beats and
	   not args.create_labels_from_notes):
		args.create_labels_from_chords = True
	L = sorted(set([
	    0,
	    *(labels_from_chords(args.audio_output)
	        if args.create_labels_from_chords else []),
	    *(labels_from_beats(args.audio_output)
	        if args.create_labels_from_beats else []),
	    *(labels_from_notes(args.audio_output)
	        if args.create_labels_from_notes else []),
	    duration(args.audio_output, 'a:0')
	]))
	if args.output_max_length:
		L[:] = [l for l in L if l < args.output_max_length
		    ] + [args.output_max_length]
	if args.create_labels_joins > 1:
		L[:] = L[::args.create_labels_joins]
	if args.create_labels_splits > 1:
		L[:] = [
		    L[i] + (L[i + 1] - L[i]) * j / args.create_labels_splits
		    for i in range(len(L) - 1)
		    for j in range(args.create_labels_splits)
		]
	if args.create_labels_max_length:
		L[:] = [
		    L[i] + j * args.create_labels_max_length
		    for i in range(len(L) - 1)
		    for j in range(1 +
		        int((L[i + 1] - L[i]) / args.create_labels_max_length))
		]
	if args.create_labels_min_length:
		L_last = [L[0]]
		L[1:-1] = [
		    L[i]
		    for i in range(1, len(L) - 1)
		    if L[i] - L_last[0] >= args.create_labels_min_length and
		        L[-1] - L[i] >= args.create_labels_min_length and
		        not L_last.remove(L_last[0]) and not L_last.append(L[i])
		]
	labels[:] = [
	    Label(
	        output_start_pos = L[i],
	        output_end_pos = L[i + 1],
	        input_file_name = None,
	        input_start_pos = -1,
	        input_end_pos = -1
	    )
	    for i in range(len(L) - 1)
	]
	write_labels()

def labels_from_chords(audio_file_name):
	if (not args.create_labels_from_chords_chroma and
	    not args.create_labels_from_chords_cnn):
		args.create_labels_from_chords_chroma = True
	proc = []
	feat = []
	if args.create_labels_from_chords_chroma:
		proc.append(
		    madmom.features.chords.DeepChromaChordRecognitionProcessor()
		)
		feat.append(madmom.audio.chroma.DeepChromaProcessor()(
		    audio_file_name
		))
	if args.create_labels_from_chords_cnn:
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
	if (not args.create_labels_from_beats_detection and
	    not args.create_labels_from_beats_detection_crf and
	    not args.create_labels_from_beats_tracking and
	    not args.create_labels_from_beats_tracking_dbn):
		args.create_labels_from_beats_tracking_dbn = True
	proc = []
	if args.create_labels_from_beats_detection:
		proc.append(madmom.features.beats.BeatDetectionProcessor(
		    look_aside = 0.2,
		    fps = 100
		))
	if args.create_labels_from_beats_detection_crf:
		proc.append(madmom.features.beats.CRFBeatDetectionProcessor(
		    interval_sigma = 0.18,
		    use_factors = False,
		    fps = 100
		))
	if args.create_labels_from_beats_tracking:
		proc.append(madmom.features.beats.BeatTrackingProcessor(
		    look_aside = 0.2,
		    fps = 100
		))
	if args.create_labels_from_beats_tracking_dbn:
		proc.append(madmom.features.beats.DBNBeatTrackingProcessor(
		    min_bpm = 50,
		    max_bpm = 100,
		    transition_lambda = 1,
		    observation_lambda = 16,
		    correct = True,
		    fps = 100
		))
	return set(itertools.chain.from_iterable(
	    p(madmom.features.beats.RNNBeatProcessor()(audio_file_name))
	    for p in proc
	))

def labels_from_notes(audio_file_name):
	if (not args.create_labels_from_notes_rnn and
	    not args.create_labels_from_notes_cnn):
		args.create_labels_from_notes_rnn = True
	proc = []
	act = []
	if args.create_labels_from_notes_rnn:
		proc.append(madmom.features.notes.NoteOnsetPeakPickingProcessor(
		    fps = 100,
		    pitch_offset = 21
		))
		act.append(madmom.features.notes.RNNPianoNoteProcessor()(
		    audio_file_name
		))
	if args.create_labels_from_notes_cnn:
		proc.append(madmom.features.notes.ADSRNoteTrackingProcessor())
		act.append(madmom.features.notes.CNNPianoNoteProcessor()(
		    audio_file_name
		))
	return set(itertools.chain.from_iterable(
	    (t for (t, *_) in p(a)) for (p, a) in zip(proc, act)
	))

def create_labels_video():
	pool = multiprocessing.pool.Pool(os.cpu_count())
	res = [
	    pool.apply_async(check_label_video, (i,))
	    for i in range(len(labels))
	]
	pool.close()
	pool.join()
	assert all(r.get() is None for r in res)

def check_label_video(n):
	while True:
		label, label_changed = update_label_video(
		    labels[n], n / len(labels))
		if not label_changed:
			break
		if args.increment:
			cache_input_video(label, n)
			duration = label.output_end_pos - label.output_start_pos
			cache_label = Label(
			    output_start_pos = label.output_start_pos,
			    output_end_pos = label.output_end_pos,
			    input_file_name = args.cache % (n + 1),
			    input_start_pos = 0,
			    input_end_pos = duration
			)
			cache_video = Video(
			    url = args.cache % (n + 1),
			    duration = duration
			)
			if visual_filter(cache_label, cache_video):
				labels[n] = label
				break
		else:
			if visual_filter(label, videos[label.input_file_name]):
				labels[n] = label
				break
	if label_changed:
		write_labels()
	if args.increment and not os.path.isfile(args.cache % (n + 1)):
		cache_input_video(labels[n], n)

def update_label_video(l: Label, progress):
	input_file_name = l.input_file_name if (
	    l.input_file_name is not None) else (
	    next_input_video_file_name(progress))
	input_start_pos = l.input_start_pos if (
	    input_file_name is None or l.input_start_pos >= 0) else (
	    next_input_video_start_pos(
	        duration(input_file_name, 'v:0'),
	        l.output_end_pos - l.output_start_pos,
	        progress))
	input_end_pos = l.input_end_pos if (
	    input_file_name is None or
	    l.input_start_pos >= 0 and l.input_end_pos >= 0) else (
	    input_start_pos + (l.output_end_pos - l.output_start_pos))
	label_changed = (
	    input_file_name != l.input_file_name or
	    input_start_pos != l.input_start_pos or
	    input_end_pos != l.input_end_pos)
	return Label(
	    l.output_start_pos,
	    l.output_end_pos,
	    input_file_name,
	    input_start_pos,
	    input_end_pos
	    ), label_changed

def next_input_video_file_name(progress):
	if not videos:
		return None
	pos = random.uniform(0, sum([v.duration for _, v in videos.items()]))
	for file_name, video in videos.items():
		pos -= video.duration
		if pos < 0:
			break
	return file_name

def next_input_video_start_pos(input_duration, output_duration, progress):
	scope = (min(1.0, len(videos) / len(labels))
	    if args.visual_filter_chrono else 1.0)
	return (
	    input_duration * (1 - scope) * progress +
	    random.uniform(0, input_duration * scope - output_duration)
	)

def cache_input_video(l: Label, n):
	if l.input_file_name not in videos:
		read_video(l.input_file_name)
	subprocess.run([
	    'ffmpeg',
	    '-ss', str(l.input_start_pos),
	    '-t', str(l.input_end_pos - l.input_start_pos +
	        args.offset_increment),
	    '-i', videos[l.input_file_name].url,
	    '-filter_complex', 'concat=n=1',
	    '-an',
	    '-y', args.cache % (n + 1)
	    ],
	    check = True
	)

def visual_filter(l: Label, v: Video):
	if args.visual_filter_drop_face_less:
		if not visual_filter_face_less(l, v):
			return False
	if args.visual_filter_drop_black_frame:
		if not visual_filter_black_frame(l, v):
			return False
	if args.visual_filter_drop_hard_cuts:
		if not visual_filter_hard_cuts(l, v):
			return False
	if args.visual_filter_drop_slow_pace:
		if not visual_filter_slow_pace(l, v):
			return False
	return True

def visual_filter_base(l: Label, v: Video, filter_expr, filter_func):
	process = subprocess.run([
	    'ffmpeg',
	    '-ss', str(l.input_start_pos),
	    '-t', str(l.input_end_pos - l.input_start_pos),
	    '-i', v.url,
	    '-vf', filter_expr,
	    '-f', 'null',
	    '-'
	    ],
	    check = True,
	    stderr = subprocess.PIPE
	)
	return filter_func(process.stderr.decode())

def visual_filter_black_frame(l: Label, v: Video):
	visual_filter_base(l, v, 'blackframe', lambda x: 'pblack:' not in x)

def visual_filter_hard_cuts(l: Label, v: Video):
	filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
	    args.visual_filter_drop_hard_cuts_prob)
	visual_filter_base(l, v, filter_expr, lambda x: 'pts_time:' not in x)

def visual_filter_slow_pace(l: Label, v: Video):
	filter_expr = ('select=\'gt(scene,%f)\',showinfo' %
	    args.visual_filter_drop_slow_pace_prob)
	def filter_func(x):
		fast_frames_number = x.count('pts_time:')
		return (fast_frames_number / frames_number(v.url)
		    >= args.visual_filter_drop_slow_pace_rate)
	visual_filter_base(l, v, filter_expr, filter_func)

def visual_filter_face_less(l: Label, v: Video):
	_, frame_file_name = tempfile.mkstemp(suffix = '.png')
	process = subprocess.run([
	    'ffmpeg',
	    '-ss', str((l.input_start_pos + l.input_end_pos) / 2),
	    '-i', v.url,
	    '-frames:v', str(1),
	    '-vcodec', 'png',
	    '-y', frame_file_name
	    ],
	    check = True
	)
	frame = cv2.cvtColor(cv2.imread(frame_file_name), cv2.COLOR_BGR2RGB)
	os.remove(frame_file_name)
	return not not dlib.get_frontal_face_detector()(frame)

def visual_effects():
	effects = []
	if args.visual_effect_speedup:
		effects.append(visual_effects_speedup)
	if args.visual_effect_zooming:
		effects.append(visual_effects_zooming)
	filters = []
	mappers = []
	for e in effects:
		filter, mapper = e()
		filters.append(filter)
		mappers.append(mapper)
	return filters, mappers

def visual_effects_speedup():
	audio_tempo = (tempo(args.audio_output) *
	    args.visual_effect_speedup_tempo_multi)
	def f(x, p, y):
		x0 = x * p + math.pi / 2
		return (2 * (x0 - x0 % math.pi) / math.pi
		    - math.cos(x0 % math.pi)) / p - y
	warnings.filterwarnings(
	    'ignore', 'The iteration is not making good progress')
	def fx(p, y):
		return f(math.pi / p, p, y)
	p = scipy.optimize.fsolve(functools.partial(fx, y = audio_tempo), 1)[0]
	filter = 'setpts=\'' \
	    '(2 * (T * %.3f + PI / 2 - mod(T * %.3f + PI / 2, PI)) / PI' \
	    '- cos(mod(T * %.3f + PI / 2, PI))) / %.3f / TB\'' % tuple([p] * 4)
	def mapper(y):
		return scipy.optimize.fsolve(
		    functools.partial(f, p = p, y = y), y)[0]
	return filter, mapper

def visual_effects_zooming():
	return '', lambda x: x

def write_video(labels_before):
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
			os.replace(args.video_output, args.output)

def write_video_reencode():
	for l in labels:
		if l.input_file_name not in videos:
			read_video(l.input_file_name)
	def apply(functions, x):
		y = x
		for f in functions:
			y = f(y)
		return y
	concat_filter = 'concat=n=%d' % len(labels)
	effects_filters, effects_mappers = visual_effects()
	subprocess.run([
	    'ffmpeg'] +
	    list(itertools.chain.from_iterable([
	        '-ss', str(l.input_start_pos),
	        '-t', '%.3f' % max(0,
	            apply(effects_mappers, l.output_end_pos) -
	            apply(effects_mappers, l.output_start_pos) +
	            args.offset_reencode),
	        '-i', videos[l.input_file_name].url
	        ] for l in labels
                   )) + [
	    '-t', str(args.output_max_length or labels[-1].output_end_pos),
	    '-i', args.audio_output,
	    '-filter_complex', ', '.join([concat_filter] + effects_filters),
	    '-shortest',
	    '-c:v', 'libx264',
	    '-crf', '33',
	    '-f', 'matroska',
	    '-y',
	    args.video_output if args.output != '-' else '-'
	    ],
	    check = True
	)

def write_video_increment():
	process = subprocess.Popen([
	    'ffmpeg',
	    '-protocol_whitelist', 'file,pipe',
	    '-f', 'concat',
	    '-safe', '0',
	    '-i', 'pipe:',
	    '-c', 'copy',
	    '-an',
	    '-y', args.video_output
	    ],
	    stdin = subprocess.PIPE
	)
	process.stdin.writelines(
	    ('file \'%s\'\n' % args.cache % (i + 1)).encode()
	    for i in range(len(labels))
	)
	_, errors = process.communicate()
	if process.returncode != 0:
		raise Exception(errors)

def write_video_mixed(labels_before):
	if not os.path.isfile(args.output):
		write_video_mixed_reencode()
	else:
		write_video_mixed_increment(labels_before)

def write_video_mixed_reencode():
	process = subprocess.run([
	    'ffmpeg'] +
	    list(itertools.chain.from_iterable([
	        '-i', args.cache % (i + 1)
	        ] for i in range(len(labels))
	    )) + [
	    '-filter_complex', 'concat=n=%d' % len(labels),
	    '-an',
	    '-y', args.video_output
	    ],
	    check = True
	)

def write_video_mixed_increment(labels_before):
	labels_delta = sorted(
	    set(labels) - set(labels_before),
	    key = lambda t: t[0]
	)
	if not labels_delta:
		return
	process = subprocess.Popen([
	    'ffmpeg',
	    '-protocol_whitelist', 'file,pipe',
	    '-f', 'concat',
	    '-safe', '0',
	    '-i', 'pipe:',
	    '-c', 'copy',
	    '-an',
	    '-y', args.video_output
	    ],
	    stdin = subprocess.PIPE,
	    stderr = subprocess.PIPE
	)
	i0 = -1
	for i in range(len(labels) + 1):
		if i == len(labels) or labels[i] in labels_delta:
			if i0 != -1:
				process.stdin.write((
				    'file \'%s\'\n' \
				    'inpoint %f\n' \
				    'outpoint %f\n' % (
				    args.output,
				    labels[i0].output_start_pos,
				    labels[i - 1].output_end_pos +
				        args.offset_mixed
				    )).encode()
				)
				i0 = -1
			if i < len(labels):
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
	    '-t', str(args.output_max_length or labels[-1].output_end_pos),
	    '-i', args.video_output,
	    '-t', str(args.output_max_length or labels[-1].output_end_pos),
	    '-i', args.audio_output,
	    '-c', 'copy',
	    '-y', args.output
	    ],
	    check = True
	)

if __name__== '__main__':
	main()
