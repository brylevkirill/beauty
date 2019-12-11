import collections, datetime, os, random, subprocess, sys, time

def parse_timestamp(s):
	try:
		return float(s)
	except:
		t = datetime.datetime.strptime(s, "%H:%M:%S.%f")
		return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond * 0.000001
def format_timestamp(t):
	return datetime.datetime.utcfromtimestamp(t).strftime("%H:%M:%S.%f")[:-3]

Label = collections.namedtuple("Label", """
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos""")
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
labels = [parse_label(s) for s in open(sys.argv[2]).read().splitlines()]

Video = collections.namedtuple("Video", "duration")
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
	    check=True,
	    stdout=subprocess.PIPE)
	videos[v] = Video(duration = float(process.stdout))

strategy1 = False
strategy1_offset = -0.0415
strategy2 = True
strategy2_offset = -0.0245
drop_hard_cuts = True
drop_hard_cuts_prob = 0.05
skip = 4
#scope = 1.0 * len(sys.argv[4:]) / len(labels)
scope = 1.0
max_len = max(l.output_end_pos - l.output_start_pos for l in labels) + 0.001
random.seed(time.time())

args = []
i = 0
while i < len(labels):
	l = labels[i]
	input_file_name = l.input_file_name if (
	    l.input_file_name is not None) else (
	    sys.argv[4 + (i * skip + 3) % len(sys.argv[4:])])
	input_start_pos = l.input_start_pos if (
	    l.input_start_pos >= 0) else (
	    videos[input_file_name].duration * (1 - scope) * i / len(labels) +
	    random.uniform(0, videos[input_file_name].duration * scope - max_len))
	input_end_pos = l.input_end_pos if (
	    l.input_start_pos >= 0 and l.input_end_pos >= 0) else (
	    input_start_pos + l.output_end_pos - l.output_start_pos)
	if drop_hard_cuts and (
	    input_file_name != l.input_file_name or
	    input_start_pos != l.input_start_pos or
	    input_end_pos != l.input_end_pos):
		process = subprocess.run(["ffmpeg",
		    "-ss", str(input_start_pos),
		    "-t", str(input_end_pos - input_start_pos),
		    "-i", input_file_name,
		    "-filter:v" , "select='gt(scene,%f)',showinfo" % drop_hard_cuts_prob,
		    "-f", "null",
		    "-"],
		    check=True,
		    stderr=subprocess.PIPE)
		if "n:   0" in process.stderr.decode("utf-8"):
			continue
	if strategy1:
		args += [
		    "-ss", str(input_start_pos),
		    "-t", str(input_end_pos - input_start_pos + strategy1_offset),
		    "-i", input_file_name]
	if strategy2 and (
	    not os.path.isfile("%d.mp4" % (i + 1)) or
	    input_file_name != l.input_file_name or
	    input_start_pos != l.input_start_pos or
	    input_end_pos != l.input_end_pos):
		subprocess.run(["ffmpeg",
		    "-ss", str(input_start_pos),
		    "-t", str(input_end_pos - input_start_pos + strategy2_offset),
		    "-i", input_file_name,
		    "-filter_complex", "concat=n=1",
		    "-an",
		    "-y", "%d.mp4" % (i + 1)],
		    check=True)
	labels[i] = Label(
	    l.output_start_pos,
	    l.output_end_pos,
	    input_file_name,
	    input_start_pos,
	    input_end_pos)
	i += 1

open(sys.argv[2], 'w').writelines(format_label(l) for l in labels)

open(sys.argv[3] + ".srt", 'w').writelines("%d\n%s --> %s\n%d\n\n" % (
    i + 1,
    format_timestamp(labels[i].output_start_pos),
    format_timestamp(labels[i].output_end_pos),
    i + 1) for i in range(len(labels)))

if strategy1:
	subprocess.run(["ffmpeg"] + args + [
	     "-filter_complex", "concat=n=%d" % (len(labels)),
	     "-an",
	     "-y", "tmp.mp4"],
	     check=True)
elif strategy2:
	process = subprocess.Popen(["ffmpeg",
	    "-protocol_whitelist", "file,pipe",
	    "-f", "concat",
	    "-safe", "0",
	    "-i", "pipe:",
	    "-c", "copy",
	    "-y", "tmp.mp4"],
	    stdin=subprocess.PIPE)
	process.stdin.writelines(
	    b"file '%d.mp4'\n" % (i + 1) for i in range(len(labels)))
	process.communicate()
	process.stdin.close()
if strategy1 or strategy2:
	subprocess.run(["ffmpeg",
	    "-i", "tmp.mp4",
	    "-i", sys.argv[1],
	    "-c", "copy",
	    "-y", sys.argv[3]],
	    check=True)
