import collections
import cv2
import datetime
import dlib
import itertools
import madmom.audio.chroma
import madmom.features.beats
import madmom.features.chords
import madmom.features.notes
import multiprocessing.pool
import os
import random
import subprocess
import sys
import tempfile
import time
import validators

labels_file_name = sys.argv[1]
audio_file_names = [sys.argv[2]]
video_file_names = sys.argv[3:-1]
output_file_name = sys.argv[-1]
cache_file_name = "%d.mp4"
tmp_video_file_name = "tmp.mp4"

create_labels_chords = True
create_labels_beats = False
create_labels_notes = False
create_labels_neural = False
create_labels_length = 0.4
create_labels_splits = 1
create_labels_chrono = False
drop_hard_cuts = False
drop_hard_cuts_prob = 0.05
drop_slow_pace = False
drop_slow_pace_prob = 0.02
drop_slow_pace_part = 0.2
drop_face_less = False
strategy1 = False
strategy1_offset = -0.0415
strategy2 = True
strategy2_offset = -0.0245

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
		raise ValueError("invalid value '%s'" % t[2:])
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
	    open(labels_file_name).read().splitlines()
	    ] if os.path.isfile(labels_file_name) else []

def write_labels():
	open(labels_file_name, 'w').writelines(format_label(l) for l in labels)

def labels_created():
	return all (l.input_file_name is not None for l in labels)

def create_labels(audio_file_name):
	if create_labels_chords:
		create_labels_from_chords(audio_file_name)
	elif create_labels_beats:
		create_labels_from_beats(audio_file_name)
	elif create_labels_notes:
		create_labels_from_notes(audio_file_name)

def create_labels_from_notes(audio_file_name):
	if create_labels_neural:
		proc = madmom.features.notes.ADSRNoteTrackingProcessor()
		act = madmom.features.notes.CNNPianoNoteProcessor()(audio_file_name)
	else:
		proc = madmom.features.notes.NoteOnsetPeakPickingProcessor(
		    fps = 100,
		    pitch_offset = 21)
		act = madmom.features.notes.RNNPianoNoteProcessor()(audio_file_name)
	notes = [0,
	    *sorted(set([t for (t, *_) in proc(act)])),
	    duration(audio_file_name, "a:0")]
	init_labels(notes)

def create_labels_from_beats(audio_file_name):
	#proc = madmom.features.beats.BeatDetectionProcessor(
	#    look_aside = 2,
	#    fps = 100)
	#proc = madmom.features.beats.BeatTrackingProcessor(
	#    look_aside = 0.2,
	#    fps = 100)
	#proc = madmom.features.beats.CRFBeatDetectionProcessor(
	#    interval_sigma = 0.18,
	#    use_factors = False,
	#    fps = 100)
	proc = madmom.features.beats.DBNBeatTrackingProcessor(
	    min_bpm = 50,
	    max_bpm = 100,
	    transition_lambda = 1,
	    observation_lambda = 16,
	    correct = True,
	    fps = 100)
	act = madmom.features.beats.RNNBeatProcessor()(audio_file_name)
	beats = [0, *proc(act), duration(audio_file_name, "a:0")]
	init_labels(beats)

def create_labels_from_chords(audio_file_name):
	if create_labels_neural:
		cfp = madmom.features.chords.CNNChordFeatureProcessor()
		features = cfp(audio_file_name)
		crp = madmom.features.chords.CRFChordRecognitionProcessor()
		chords = crp(features)
	else:
		dcp = madmom.audio.chroma.DeepChromaProcessor()
		chroma = dcp(audio_file_name)
		crp = madmom.features.chords.DeepChromaChordRecognitionProcessor()
		chords = crp(chroma)
	chords = [0] + [e for (_, e, *_) in chords]
	init_labels(chords)

def init_labels(T: list):
	T_last = [T[0]]
	T[1:-1] = [
	    T[i] for i in range(1, len(T) - 1)
	    if T[i] - T_last[0] >= create_labels_length and
	        not T_last.remove(T_last[0]) and not T_last.append(T[i])
	]
	labels[:] = [
	    Label(
	        output_start_pos = (T[j] +
	            (T[j + 1] - T[j]) * i / create_labels_splits),
	        output_end_pos = (T[j] +
	            (T[j + 1] - T[j]) * (i + 1) / create_labels_splits),
	        input_file_name = None,
	        input_start_pos = -1,
	        input_end_pos = -1
	    )
	    for i in range(create_labels_splits)
	    for j in range(len(T) - 1)
	]

def write_titles():
	open(output_file_name + ".srt", 'w').writelines(
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

def read_audios():
	if not labels:
		labels[:] = [Label(
		    output_start_pos = 0,
		    output_end_pos = duration(audio_file_names[0], "a:0"),
		    input_file_name = None,
		    input_start_pos = -1,
		    input_end_pos = -1
		)]
		write_labels()

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
		raise Exception("can't read '%s'" % url)
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
		    duration = duration(video_file_name, "v:0"))

def read_playlist(url):
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
	for (title, id) in zip(*[iter(output)] * 2):
		if (url.startswith("ytsearch") and
		    any (word.lower() not in title.lower()
		    for word in url[url.index(':') + 1:].split()
		)):
			continue
		video_file_names.append("http://youtu.be/" + id)

def read_videos():
	if not video_file_names:
		raise Exception("no video files given")
	for v in list(video_file_names):
		if "youtube.com/playlist" in v or v.startswith("ytsearch"):
			video_file_names.remove(v)
			read_playlist(v)
	for l in labels:
		if (l.input_file_name is not None and
		    l.input_file_name not in video_file_names):
			video_file_names.append(l.input_file_name)
	pool = multiprocessing.pool.ThreadPool(len(video_file_names))
	res = [
	    pool.apply_async(read_video, (v, False))
	    for v in video_file_names]
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
	scope = min(1.0, len(videos) / len(labels)) if (
	    create_labels_chrono) else 1.0
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
	        "select='gt(scene,%f)',showinfo" % drop_hard_cuts_prob,
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
	        "select='gt(scene,%f)',showinfo" % drop_slow_pace_prob,
	    "-f", "null",
	    "-"
	    ],
	    check = True,
	    stderr = subprocess.PIPE
	)
	fast_frames_number = process.stderr.decode().count("pts_time:")
	return fast_frames_number / frames_number(v.url) >= drop_slow_pace_part

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
	if drop_face_less:
		if not check_video_face_less(l, v):
			return False
	if drop_slow_pace:
		if not check_video_slow_pace(l, v):
			return False
	if drop_hard_cuts:
		if not check_video_hard_cuts(l, v):
			return False
	return True

def cache_input(l: Label, n):
	if l.input_file_name not in videos:
		read_video(l.input_file_name)
	subprocess.run([
	    "ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos + strategy2_offset),
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
		if strategy2:
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
	if strategy2 and not os.path.isfile(cache_file_name % (n + 1)):
		cache_input(labels[n], n)

def create_output():
	pool = multiprocessing.pool.Pool(os.cpu_count())
	res = [pool.apply_async(check_label, (i,)) for i in range(len(labels))]
	pool.close()
	pool.join()
	assert all(r.get() is None for r in res)

def write_output():
	if strategy1:
		for l in labels:
			if l.input_file_name not in videos:
				read_video(l.input_file_name)
		subprocess.run([
		    "ffmpeg"] +
		    list(itertools.chain.from_iterable([
		        "-ss", str(l.input_start_pos),
		        "-t", str(l.input_end_pos - l.input_start_pos +
		            strategy1_offset),
		        "-i", videos[l.input_file_name].url
		        ] for l in labels
                    )) + [
		    "-filter_complex", "concat=n=%d" % len(labels),
		    "-an",
		    "-y", tmp_video_file_name
		    ],
		    check = True
		)
	elif strategy2:
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
		process.communicate()
		process.stdin.close()
	if strategy1 or strategy2:
		subprocess.run([
		    "ffmpeg",
		    "-i", tmp_video_file_name,
		    "-i", audio_file_names[0],
		    "-c", "copy",
		    "-y", output_file_name
		    ],
		    check = True
		)
		os.remove(tmp_video_file_name)

if __name__== "__main__":
	random.seed(time.time())
	read_labels()
	if not labels:
		create_labels(audio_file_names[0])
		write_labels()
	read_audios()
	if not labels_created() or strategy1:
		read_videos()
	create_output()
	write_labels()
	write_titles()
	write_output()
