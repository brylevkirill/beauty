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

parser = argparse.ArgumentParser()
parser.add_argument("-f", "--fromscratch", action = "store_true")
parser.add_argument("-i", "--incremental", action = "store_true")
parser.add_argument("-l", "--labels", metavar = "<labels file>", required = True)
parser.add_argument("-v", "--video", metavar = "<video file|URL>", nargs = "+")
parser.add_argument("-a", "--audio", metavar= "<audio file>")
parser.add_argument("-o", "--output", metavar = "<output file>")
args = parser.parse_args()

create_labels_length_minima = 0.4
create_labels_from_chords = True
create_labels_from_chords_chroma = True
create_labels_from_chords_cnn = False
create_labels_from_beats = False
create_labels_from_beats_join_size = 4
create_labels_from_beats_detection = False
create_labels_from_beats_detection_crf = False
create_labels_from_beats_tracking = False
create_labels_from_beats_tracking_dbn = True
create_labels_from_notes = False
create_labels_from_notes_rnn = True
create_labels_from_notes_cnn = False
visual_filter_chrono = False
visual_filter_drop_hard_cuts = False
visual_filter_drop_hard_cuts_prob = 0.05
visual_filter_drop_slow_pace = False
visual_filter_drop_slow_pace_prob = 0.02
visual_filter_drop_slow_pace_part = 0.2
visual_filter_drop_face_less = False
visual_effect_speedup = True
visual_effect_speedup_tempo_multi = 2
visual_effect_zooming = False
offset_fromscratch = -0.0415
offset_incremental = -0.0245
offset_mixed = -0.045
cache_file_name = "%d.mp4"
tmp_video_file_name = "tmp.mp4"

Label = collections.namedtuple("Label", """
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos
    """)
labels = multiprocessing.Manager().list()

Video = collections.namedtuple("Video", """
    url
    duration
    """)
videos = multiprocessing.Manager().dict()

def parse_timestamp(s):
	try:
		return float(s)
	except ValueError:
		pass
	try:
		t = datetime.datetime.strptime(s, "%H:%M:%S.%f")
	except ValueError:
		try:
			t = datetime.datetime.strptime(s, "%H:%M:%S")
		except ValueError:
			t = datetime.datetime.strptime(s, "%M:%S")
	return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond * 0.000001

def format_timestamp(t):
	return datetime.datetime.utcfromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]

def parse_label(s):
	t = s.split('\t')
	if t[2:] and not os.path.isfile(t[2]) and not validators.url(t[2]):
		raise ValueError("Invalid value '%s'." % t[2:])
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
	        if l.input_file_name else "") +
	    ('\t' + format_timestamp(l.input_start_pos)
	        if l.input_start_pos != -1 else "") +
	    ('\t' + format_timestamp(l.input_end_pos)
	        if l.input_end_pos != -1 else "") + '\n'
	)

def read_labels():
	labels[:] = [parse_label(s) for s in
	    open(args.labels).read().splitlines()
	    ] if os.path.isfile(args.labels) else []

def write_labels():
	open(args.labels, 'w').writelines(format_label(l) for l in labels)

def labels_created():
	return all (
	    l.input_file_name is not None and
	    l.input_start_pos != -1 and
	    l.input_end_pos != -1
	    for l in labels)

def create_labels(audio_file_name):
	L = sorted(set([
	    0,
	    *(labels_from_chords(audio_file_name)
	        if create_labels_from_chords else []),
	    *(labels_from_beats(audio_file_name)
	        if create_labels_from_beats else []),
	    *(labels_from_notes(audio_file_name)
	        if create_labels_from_notes else []),
	    duration(audio_file_name, "a:0")
	]))
	L_last = [L[0]]
	L[1:-1] = [
	    L[i] for i in range(1, len(L) - 1)
	    if L[i] - L_last[0] >= create_labels_length_minima and
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

def labels_from_chords(audio_file_name):
	proc = []
	feat = []
	if create_labels_from_chords_chroma:
		proc.append(
		    madmom.features.chords.DeepChromaChordRecognitionProcessor()
		)
		feat.append(madmom.audio.chroma.DeepChromaProcessor()(
		    audio_file_name
		))
	if create_labels_from_chords_cnn:
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
	proc = []
	if create_labels_from_beats_detection:
		proc.append(madmom.features.beats.BeatDetectionProcessor(
		    look_aside = 0.2,
		    fps = 100
		))
	if create_labels_from_beats_detection_crf:
		proc.append(madmom.features.beats.CRFBeatDetectionProcessor(
		    interval_sigma = 0.18,
		    use_factors = False,
		    fps = 100
		))
	if create_labels_from_beats_tracking:
		proc.append(madmom.features.beats.BeatTrackingProcessor(
		    look_aside = 0.2,
		    fps = 100
		))
	if create_labels_from_beats_tracking_dbn:
		proc.append(madmom.features.beats.DBNBeatTrackingProcessor(
		    min_bpm = 50,
		    max_bpm = 100,
		    transition_lambda = 1,
		    observation_lambda = 16,
		    correct = True,
		    fps = 100
		))
	return set(itertools.chain.from_iterable(
	    p(madmom.features.beats.RNNBeatProcessor()(
	        audio_file_name))[::create_labels_from_beats_join_size]
	    for p in proc))

def labels_from_notes(audio_file_name):
	proc = []
	act = []
	if create_labels_from_notes_rnn:
		proc.append(madmom.features.notes.NoteOnsetPeakPickingProcessor(
		    fps = 100,
		    pitch_offset = 21
		))
		act.append(madmom.features.notes.RNNPianoNoteProcessor()(
		    audio_file_name
		))
	if create_labels_from_notes_cnn:
		proc.append(madmom.features.notes.ADSRNoteTrackingProcessor())
		act.append(madmom.features.notes.CNNPianoNoteProcessor()(
		    audio_file_name
		))
	return set(itertools.chain.from_iterable(
	    (t for (t, *_) in p(a)) for (p, a) in zip(proc, act)
	))

def write_titles():
	open(args.output + ".srt", 'w').writelines(
	    "%d\n%s --> %s\n%d\n\n" % (
	        i + 1,
	        format_timestamp(labels[i].output_start_pos),
	        format_timestamp(labels[i].output_end_pos),
	        i + 1)
	    for i in range(len(labels))
	)

def property(media_file_name, stream, prop):
	process = subprocess.run([
	    "ffprobe",
	    "-select_streams", stream,
	    "-show_entries", "stream=%s" % prop,
	    "-of", "default=noprint_wrappers=1:nokey=1",
	    "-v", "quiet",
	    media_file_name
	    ],
	    check = True,
	    stdout = subprocess.PIPE
	)
	return float(process.stdout.decode())

def duration(media_file_name, stream):
	if validators.url(media_file_name) and stream == "v:0":
		if media_file_name not in videos:
			read_video(media_file_name)
		return videos[media_file_name].duration
	return property(media_file_name, stream, "duration")

def frames_number(video_file_name):
	return property(video_file_name, "v:0", "nb_frames")

def tempo(audio_file_name):
	proc = madmom.features.chords.DeepChromaChordRecognitionProcessor()
	feat = madmom.audio.chroma.DeepChromaProcessor()(audio_file_name)
	intervals = [
	    (e - s - (e - s) % 0.01) for (s, e, _) in proc(feat)] or [
	    duration(audio_file_name, "a:0")
	]
	return collections.Counter(intervals).most_common(1)[0][0]

def check_media_url(url):
	process = subprocess.run([
	    "ffprobe",
	    "-v", "quiet",
	    url
	    ],
	    check = False
	)
	return process.returncode == 0

def youtube_video(url, strict = True):
	try:
		process = subprocess.run([
		    "youtube-dl",
		    "--get-url",
		    "--get-duration",
		    "-f", "bestvideo[ext=mp4][width=1920][height=1080]",
		    "--youtube-skip-dash-manifest",
		    url
		    ],
		    check = True,
		    stdout = subprocess.PIPE,
		    stderr = subprocess.PIPE
		)
	except subprocess.CalledProcessError as e:
		if not strict:
			if any (m in e.stderr.decode() for m in [
			    "This video is unavailable",
			    "requested format not available"
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
		raise Exception("Can't read '%s'." % url)
	return variants[0] if variants else None

def read_video(video_file_name, strict = True):
	if (validators.url(video_file_name) and
	    "youtube.com" in video_file_name or "youtu.be" in video_file_name):
		video = youtube_video(video_file_name, strict)
		if video is not None:
			videos[video_file_name] = video
	else:
		videos[video_file_name] = Video(
		    url = video_file_name,
		    duration = duration(video_file_name, "v:0")
		)

def youtube_playlist(url):
	process = subprocess.run([
	    "youtube-dl",
	    "--get-title",
	    "--get-id",
	    "--flat-playlist",
	    url
	    ],
	    check = True,
	    stdout = subprocess.PIPE
	)
	output = process.stdout.decode().splitlines()
	return [
	    "http://youtu.be/" + id
	    for (title, id) in zip(*[iter(output)] * 2)
	    if (url.startswith("ytsearch") and
	        any (word.lower() not in title.lower()
	            for word in url[url.index(':') + 1:].split()
		)
	    )
	]

def read_videos():
	if not args.video:
		raise Exception("No video file names or URLs given.")
	for v in list(args.video):
		if "youtube.com/playlist" in v or v.startswith("ytsearch"):
			args.video.remove(v)
			args.video.extend(youtube_playlist(v))
	for l in labels:
		if (l.input_file_name is not None and
		    l.input_file_name not in args.video):
			args.video.append(l.input_file_name)
	pool = multiprocessing.pool.ThreadPool(len(args.video))
	res = [pool.apply_async(read_video, (v, False)) for v in args.video]
	pool.close()
	pool.join()
	assert all(r.get() is None for r in res)

def next_input_file_name(progress):
	if not videos:
		return None
	pos = random.uniform(0, sum([v.duration for _, v in videos.items()]))
	for file_name, video in videos.items():
		pos -= video.duration
		if pos < 0:
			break
	return file_name

def next_input_start_pos(input_duration, output_duration, progress):
	scope = (min(1.0, len(videos) / len(labels))
	    if visual_filter_chrono else 1.0)
	return (
	    input_duration * (1 - scope) * progress +
	    random.uniform(0, input_duration * scope - output_duration)
	)

def update_label(l: Label, progress):
	input_file_name = l.input_file_name if (
	    l.input_file_name is not None) else (
	    next_input_file_name(progress))
	input_start_pos = l.input_start_pos if (
	    input_file_name is None or l.input_start_pos >= 0) else (
	    next_input_start_pos(
	        duration(input_file_name, "v:0"),
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

def check_video_hard_cuts(l: Label, v: Video):
	process = subprocess.run([
	    "ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos),
	    "-i", v.url,
	    "-filter:v",
	        "select='gt(scene,%f)',showinfo" %
	            visual_filter_drop_hard_cuts_prob,
	    "-f", "null",
	    "-"
	    ],
	    check = True,
	    stderr = subprocess.PIPE
	)
	return "pts_time:" not in process.stderr.decode()

def check_video_slow_pace(l: Label, v: Video):
	process = subprocess.run([
	    "ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos),
	    "-i", v.url,
	    "-filter:v",
	        "select='gt(scene,%f)',showinfo" %
	            visual_filter_drop_slow_pace_prob,
	    "-f", "null",
	    "-"
	    ],
	    check = True,
	    stderr = subprocess.PIPE
	)
	fast_frames_number = process.stderr.decode().count("pts_time:")
	return (fast_frames_number / frames_number(v.url)
	    >= visual_filter_drop_slow_pace_part)

def check_video_face_less(l: Label, v: Video):
	_, frame_file_name = tempfile.mkstemp(suffix = ".png")
	process = subprocess.run([
	    "ffmpeg",
	    "-ss", str((l.input_start_pos + l.input_end_pos) / 2),
	    "-i", v.url,
	    "-frames:v", str(1),
	    "-vcodec", "png",
	    "-y", frame_file_name
	    ],
	    check = True
	)
	frame = cv2.cvtColor(cv2.imread(frame_file_name), cv2.COLOR_BGR2RGB)
	os.remove(frame_file_name)
	return not not dlib.get_frontal_face_detector()(frame)

def check_video(l: Label, v: Video):
	if visual_filter_drop_face_less:
		if not check_video_face_less(l, v):
			return False
	if visual_filter_drop_slow_pace:
		if not check_video_slow_pace(l, v):
			return False
	if visual_filter_drop_hard_cuts:
		if not check_video_hard_cuts(l, v):
			return False
	return True

def cache_input(l: Label, n):
	if l.input_file_name not in videos:
		read_video(l.input_file_name)
	subprocess.run([
	    "ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos + offset_incremental),
	    "-i", videos[l.input_file_name].url,
	    "-filter_complex", "concat=n=1",
	    "-an",
	    "-y", cache_file_name % (n + 1)
	    ],
	    check = True
	)

def check_label(n):
	while True:
		label, label_changed = update_label(labels[n], n / len(labels))
		if not label_changed:
			break
		if args.incremental:
			cache_input(label, n)
			duration = label.output_end_pos - label.output_start_pos
			cache_label = Label(
			    output_start_pos = label.output_start_pos,
			    output_end_pos = label.output_end_pos,
			    input_file_name = cache_file_name % (n + 1),
			    input_start_pos = 0,
			    input_end_pos = duration
			)
			cache_video = Video(
			    url = cache_file_name % (n + 1),
			    duration = duration
			)
			if check_video(cache_label, cache_video):
				labels[n] = label
				break
		else:
			if check_video(label, videos[label.input_file_name]):
				labels[n] = label
				break
	if label_changed:
		write_labels()
	if args.incremental and not os.path.isfile(cache_file_name % (n + 1)):
		cache_input(labels[n], n)

def update_labels():
	pool = multiprocessing.pool.Pool(os.cpu_count())
	res = [pool.apply_async(check_label, (i,)) for i in range(len(labels))]
	pool.close()
	pool.join()
	assert all(r.get() is None for r in res)

def visual_effects():
	effects = []
	if visual_effect_speedup:
		effects.append(visual_effects_speedup)
	if visual_effect_zooming:
		effects.append(visual_effects_zooming)
	filters = []
	mappers = []
	for e in effects:
		filter, mapper = e()
		filters.append(filter)
		mappers.append(mapper)
	return filters, mappers

def visual_effects_speedup():
	audio_tempo = tempo(args.audio) * visual_effect_speedup_tempo_multi
	def f(x, p, y):
		x0 = x * p + math.pi / 2
		return (2 * (x0 - x0 % math.pi) / math.pi
		    - math.cos(x0 % math.pi)) / p - y
	warnings.filterwarnings(
	    "ignore", "The iteration is not making good progress")
	def fx(p, y):
		return f(math.pi / p, p, y)
	p = scipy.optimize.fsolve(functools.partial(fx, y = audio_tempo), 1)[0]
	filter = "setpts='" \
	    "(2 * (T * %.3f + PI / 2 - mod(T * %.3f + PI / 2, PI)) / PI" \
	    "- cos(mod(T * %.3f + PI / 2, PI))) / %.3f / TB'" % tuple([p] * 4)
	def mapper(y):
		return scipy.optimize.fsolve(
		    functools.partial(f, p = p, y = y), y)[0]
	return filter, mapper

def visual_effects_zooming():
	return "", lambda x: x

def apply(functions, x):
	y = x
	for f in functions:
		y = f(y)
	return y

def write_video_fromscratch():
	for l in labels:
		if l.input_file_name not in videos:
			read_video(l.input_file_name)
	concat_filter = "concat=n=%d" % len(labels)
	effects_filters, effects_mappers = visual_effects()
	subprocess.run([
	    "ffmpeg"] +
	    list(itertools.chain.from_iterable([
	        "-ss", str(l.input_start_pos),
	        "-t", "%.3f" % max(0,
	            apply(effects_mappers, l.output_end_pos) -
	            apply(effects_mappers, l.output_start_pos) +
	            offset_fromscratch),
	        "-i", videos[l.input_file_name].url
	        ] for l in labels
                   )) + [
	    "-filter_complex", ", ".join([concat_filter] + effects_filters),
	    "-an",
	    "-y", tmp_video_file_name
	    ],
	    check = True
	)

def write_video_incremental():
	process = subprocess.Popen([
	    "ffmpeg",
	    "-protocol_whitelist", "file,pipe",
	    "-f", "concat",
	    "-safe", "0",
	    "-i", "pipe:",
	    "-c", "copy",
	    "-an",
	    "-y", tmp_video_file_name
	    ],
	    stdin = subprocess.PIPE
	)
	process.stdin.writelines(
	    ("file '%s'\n" % cache_file_name % (i + 1)).encode()
	    for i in range(len(labels))
	)
	_, errors = process.communicate()
	if process.returncode != 0:
		raise Exception(errors)

def write_video_mixed(labels_before):
	if not os.path.isfile(args.output):
		write_video_mixed_fromscratch()
	else:
		write_video_mixed_incremental(labels_before)

def write_video_mixed_fromscratch():
	process = subprocess.run([
	    "ffmpeg"] +
	    list(itertools.chain.from_iterable([
	        "-i", cache_file_name % (i + 1)
	        ] for i in range(len(labels))
	    )) + [
	    "-filter_complex", "concat=n=%d" % len(labels),
	    "-an",
	    "-y", tmp_video_file_name
	    ],
	    check = True
	)

def write_video_mixed_incremental(labels_before):
	labels_delta = sorted(
	    set(labels) - set(labels_before),
	    key = lambda t: t[0]
	)
	if not labels_delta:
		return
	process = subprocess.Popen([
	    "ffmpeg",
	    "-protocol_whitelist", "file,pipe",
	    "-f", "concat",
	    "-safe", "0",
	    "-i", "pipe:",
	    "-c", "copy",
	    "-an",
	    "-y", tmp_video_file_name
	    ],
	    stdin = subprocess.PIPE,
	    stderr = subprocess.PIPE
	)
	i0 = -1
	for i in range(len(labels) + 1):
		if i == len(labels) or labels[i] in labels_delta:
			if i0 != -1:
				process.stdin.write((
				    "file '%s'\n" \
				    "inpoint %f\n" \
				    "outpoint %f\n" % (
				    args.output,
				    labels[i0].output_start_pos,
				    labels[i - 1].output_end_pos + offset_mixed
				    )).encode()
				)
				i0 = -1
			if i < len(labels):
				process.stdin.write((
				    "file '%s'\n" % cache_file_name % (i + 1)
				    ).encode()
				)
		else:
			if i0 == -1:
				i0 = i
	_, errors = process.communicate()
	if process.returncode != 0:
		raise Exception(errors)

def write_audio():
	subprocess.run([
	    "ffmpeg",
	    "-i", tmp_video_file_name,
	    "-i", args.audio,
	    "-c", "copy",
	    "-y", args.output
	    ],
	    check = True
	)

def write_output(labels_before):
	if not args.fromscratch and not args.incremental:
		args.fromscratch = True
	if args.fromscratch and args.incremental:
		write_video_mixed(labels_before)
	elif args.fromscratch:
		write_video_fromscratch()
	elif args.incremental:
		write_video_incremental()
	if args.audio:
		write_audio()
		os.remove(tmp_video_file_name)
	else:
		os.replace(tmp_video_file_name, args.output)

if __name__== "__main__":
	random.seed(time.time())
	read_labels()
	if not labels and args.audio:
		create_labels(args.audio)
		write_labels()
	if not labels_created() or not args.incremental:
		read_videos()
	labels_before = list(labels)
	update_labels()
	write_labels()
	write_output(labels_before)
	write_titles()
