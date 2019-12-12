import collections
import datetime
import multiprocessing.pool
import os
import random
import subprocess
import sys
import time

strategy1 = False
strategy1_offset = -0.0415
strategy2 = True
strategy2_offset = -0.0245
drop_hard_cuts = True
drop_hard_cuts_prob = 0.05
cache_file_name = "%d.mp4"
temp_file_name = "tmp.mp4"

Label = collections.namedtuple("Label", """
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos""")
labels = []

Video = collections.namedtuple("Video", "duration")
videos = {}

def parse_timestamp(s):
	try:
		return float(s)
	except:
		pass
	t = datetime.datetime.strptime(s, "%H:%M:%S.%f")
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
	    input_end_pos = parse_timestamp(t[4]) if t[4:] else -1)

def format_label(l: Label):
	return "%s\t%s\t%s\t%s\t%s\n" % (
	    format_timestamp(l.output_start_pos),
	    format_timestamp(l.output_end_pos),
	    l.input_file_name,
	    format_timestamp(l.input_start_pos),
	    format_timestamp(l.input_end_pos))

def read_labels():
	global labels
	labels = [parse_label(s) for s in open(sys.argv[2]).read().splitlines()]

def write_labels():
	open(sys.argv[2], 'w').writelines(format_label(l) for l in labels)

def write_subtitles():
	open(sys.argv[3] + ".srt", 'w').writelines("%d\n%s --> %s\n%d\n\n" % (
	    i + 1,
	    format_timestamp(labels[i].output_start_pos),
	    format_timestamp(labels[i].output_end_pos),
	    i + 1) for i in range(len(labels)))

def read_videos():
	global videos
	videos = {}
	for v in sys.argv[4:]:
		videos[v] = None
	for l in labels:
		if l.input_file_name is not None:
			videos[l.input_file_name] = None
	for v in videos:
		process = subprocess.run(["ffprobe",
		    "-select_streams", "v:0",
		    "-show_entries", "stream=duration",
		    "-of", "default=noprint_wrappers=1:nokey=1",
		    "-v", "quiet",
		    v],
		    check = True,
		    stdout = subprocess.PIPE)
		videos[v] = Video(duration = float(process.stdout))

def handle_label(l: Label, n):
	scope = 1.0  # len(videos) / len(labels)
	input_file_name = l.input_file_name if (
	    l.input_file_name is not None) else (
	    sys.argv[4 + (n * 4 + 3) % len(sys.argv[4:])])
	input_start_pos = l.input_start_pos if (
	    l.input_start_pos >= 0) else (
	    videos[input_file_name].duration * (1 - scope) * n / len(labels) +
	    random.uniform(0, videos[input_file_name].duration * scope -
	    max(x.output_end_pos - x.output_start_pos for x in labels)))
	input_end_pos = l.input_end_pos if (
	    l.input_start_pos >= 0 and l.input_end_pos >= 0) else (
	    input_start_pos + l.output_end_pos - l.output_start_pos)
	label_changed = (
	    input_file_name != l.input_file_name or
	    input_start_pos != l.input_start_pos or
	    input_end_pos != l.input_end_pos)
	return Label(
	    l.output_start_pos,
	    l.output_end_pos,
	    input_file_name,
	    input_start_pos,
	    input_end_pos), label_changed

def match_input_video(l: Label):
	if drop_hard_cuts:
		process = subprocess.run(["ffmpeg",
		    "-ss", str(l.input_start_pos),
		    "-t", str(l.input_end_pos - l.input_start_pos),
		    "-i", l.input_file_name,
		    "-filter:v", "select='gt(scene,%f)',showinfo" % drop_hard_cuts_prob,
		    "-f", "null",
		    "-"],
		    check = True,
		    stderr = subprocess.PIPE)
		if "n:   0" in process.stderr.decode():
			return False
	return True

def cache_input_video(l: Label, n):
	subprocess.run(["ffmpeg",
	    "-ss", str(l.input_start_pos),
	    "-t", str(l.input_end_pos - l.input_start_pos + strategy2_offset),
	    "-i", l.input_file_name,
	    "-filter_complex", "concat=n=1",
	    "-an",
	    "-y", "%d.mp4" % (n + 1)],
	    check = True)

def write_output_video():
	read_labels()
	read_videos()
	strategy1_args = []
	strategy2_pool = multiprocessing.pool.ThreadPool(os.cpu_count()//2)
	for i in range(len(labels)):
		while True:
			l, label_changed = handle_label(labels[i], i)
			if not label_changed or match_input_video(l):
				labels[i] = l
				break
		if strategy1:
			strategy1_args += [
			    "-ss", str(l.input_start_pos),
			    "-t", str(l.input_end_pos - l.input_start_pos + strategy1_offset),
			    "-i", l.input_file_name]
		if strategy2 and (
		    label_changed or not os.path.isfile("%d.mp4" % (i + 1))):
			strategy2_pool.apply_async(cache_input_video, (l, i))
	write_labels()
	write_subtitles()
	if strategy1:
		subprocess.run(["ffmpeg"] + strategy1_args + [
		     "-filter_complex", "concat=n=%d" % len(labels),
		     "-an",
		     "-y", temp_file_name],
		     check = True)
	elif strategy2:
		strategy2_pool.close()
		strategy2_pool.join()
		process = subprocess.Popen(["ffmpeg",
		    "-protocol_whitelist", "file,pipe",
		    "-f", "concat",
		    "-safe", "0",
		    "-i", "pipe:",
		    "-c", "copy",
		    "-y", temp_file_name],
		    stdin = subprocess.PIPE)
		process.stdin.writelines(
		    ("file '%s'\n" % cache_file_name % (i + 1)).encode()
		    for i in range(len(labels)))
		process.communicate()
		process.stdin.close()
	if strategy1 or strategy2:
		subprocess.run(["ffmpeg",
		    "-i", temp_file_name,
		    "-i", sys.argv[1],
		    "-c", "copy",
		    "-y", sys.argv[3]],
		    check = True)
		os.remove(temp_file_name)

def main():
	random.seed(time.time())
	write_output_video()

if __name__== "__main__":
	main()
