import collections
import cv2
import datetime
import face_recognition
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
import time

global labels_file_name
global audio_file_names
global video_file_names
global output_file_name
global cache_file_names
global tmp_video_file_name
global tmp_image_file_name

create_labels_chords = False
create_labels_beats = False
create_labels_notes = True
create_labels_neural = False
create_labels_length = 0.4
create_labels_splits = 1
create_labels_chrono = False
drop_hard_cuts = False
drop_hard_cuts_prob = 0.05
drop_face_less = False
strategy1 = True
strategy1_offset = -0.0415
strategy2 = False
strategy2_offset = -0.0245

Label = collections.namedtuple("Label", """
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos
    """)
labels = []

Video = collections.namedtuple("Video", """
    url
    duration
    """)
videos = {}

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
	return Label(
	    output_start_pos = parse_timestamp(t[0]),
	    output_end_pos = parse_timestamp(t[1]),
	    input_file_name = t[2] if t[2:] and os.path.isfile(t[2]) else None,
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
	global labels
	labels = [parse_label(s) for s in
	    open(labels_file_name).read().splitlines()
	    ] if os.path.isfile(labels_file_name) else []

def write_labels():
	open(labels_file_name, 'w').writelines(format_label(l) for l in labels)

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
	global labels
	labels = [
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

def duration(media_file_name, stream):
	process = subprocess.run([
	    "ffprobe",
	    "-select_streams", stream,
	    "-show_entries", "stream=duration",
	    "-of", "default=noprint_wrappers=1:nokey=1",
	    "-v", "quiet",
	    media_file_name
	    ],
	    check = True,
	    stdout = subprocess.PIPE
	)
	return float(process.stdout)

def read_audios():
	global labels
	if not labels:
		labels = [Label(
		    output_start_pos = 0,
		    output_end_pos = duration(audio_file_names[0], "a:0"),
		    input_file_name = None,
		    input_start_pos = -1,
		    input_end_pos = -1
		)]
		write_labels()

def read_videos():
	global videos
	videos = {}
	for l in labels:
		if l.input_file_name is not None:
			video_file_names.append(l.input_file_name)
	for v in video_file_names:
		if "youtube.com" in v or "youtu.be" in v:
			process = subprocess.run([
			    "youtube-dl",
			    "--get-id",
			    "--get-url",
			    "--get-duration",
			    "-f", "bestvideo[ext=mp4][height=1080][fps<=30]",
			    v
			    ],
			    check = True,
			    stdout = subprocess.PIPE
			)
			output = process.stdout.decode().splitlines()
			videos.update(dict((
			    "http://youtu.be/" + id,
			    Video(
			        url = url,
			        duration = parse_timestamp(duration)
			    ))
			    for (id, url, duration) in zip(*[iter(output)] * 3)
			))
		else:
			videos[v] = Video(
			    url = v,
			    duration = duration(v, "v:0"))

def next_input_file_name(progress):
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
	    l.input_start_pos >= 0) else (
	    next_input_start_pos(
	        videos[input_file_name].duration,
	        l.output_end_pos - l.output_start_pos,
	        progress))
	input_end_pos = l.input_end_pos if (
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

def match_label(l: Label):
	if drop_face_less:
		process = subprocess.run([
		    "ffmpeg",
		    "-ss", str((l.input_start_pos + l.input_end_pos) / 2),
		    "-i", videos[l.input_file_name].url,
		    "-frames:v", str(1),
		    "-vcodec", "png",
		    "-y", tmp_image_file_name
		    ],
		    check = True
		)
		frame = cv2.imread(tmp_image_file_name)
		os.remove(tmp_image_file_name)
		rgb_frame = frame[:, :, ::-1]
		faces = face_recognition.face_locations(rgb_frame)
		if not faces:
			return False
	if drop_hard_cuts:
		process = subprocess.run([
		    "ffmpeg",
		    "-ss", str(l.input_start_pos),
		    "-t", str(l.input_end_pos - l.input_start_pos),
		    "-i", videos[l.input_file_name].url,
		    "-filter:v",
		        "select='gt(scene,%f)',showinfo" % drop_hard_cuts_prob,
		    "-f", "null",
		    "-"
		    ],
		    check = True,
		    stderr = subprocess.PIPE
		)
		if "n:   0" in process.stderr.decode():
			return False
	return True

def cache_input(l: Label, n):
	subprocess.run([
	    "ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos + strategy2_offset),
	    "-i", videos[l.input_file_name].url,
	    "-filter_complex", "concat=n=1",
	    "-an",
	    "-y", cache_file_names % (n + 1)
	    ],
	    check = True
	)

def create_output():
	global cache_input_tasks
	cache_input_tasks = multiprocessing.pool.ThreadPool(os.cpu_count() // 2)
	for i in range(len(labels)):
		while True:
			l, label_changed = update_label(labels[i], i / len(labels))
			if not label_changed:
				break
			elif match_label(l):
				labels[i] = l
				break
		if label_changed:
			write_labels()
		if strategy2 and (
		    label_changed or
		    not os.path.isfile(cache_file_names % (i + 1))
		):
			cache_input_tasks.apply_async(cache_input, (l, i))

def write_output():
	if strategy1:
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
		global cache_input_tasks
		cache_input_tasks.close()
		cache_input_tasks.join()
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
		    ("file '%s'\n" % cache_file_names % (i + 1)).encode()
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

def process_options():
	global labels_file_name
	labels_file_name = sys.argv[1]
	global audio_file_names
	audio_file_names = [sys.argv[2]]
	global video_file_names
	video_file_names = sys.argv[3:-1]
	global output_file_name
	output_file_name = sys.argv[-1]
	global cache_file_names
	cache_file_names = "%d.mp4"
	global tmp_video_file_name
	tmp_video_file_name = "tmp.mp4"
	global tmp_image_file_name
	tmp_image_file_name = "tmp.png"

if __name__== "__main__":
	process_options()
	random.seed(time.time())
	read_labels()
	if not labels:
		create_labels(audio_file_names[0])
		write_labels()
	read_audios()
	read_videos()
	create_output()
	write_labels()
	write_titles()
	write_output()
