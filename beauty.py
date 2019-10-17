import random, subprocess, sys, time

tmp_file="tmp.mp4"
skip=4
offset=0.0433

labels = [0.0] + [float(line.split()[0]) for line in open(sys.argv[2])]
max_interval = max([labels[i+1]-labels[i] for i in (0, len(labels)-2)]) + 1

video_duration=[]
for i in range(4, len(sys.argv)):
	process = subprocess.run(["ffprobe", "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0", sys.argv[i]], stdout=subprocess.PIPE)
	video_duration.append(float(process.stdout))
min_duration = min(video_duration)

scope = 1.0 * len(video_duration) / len(labels)

random.seed(time.time())

args = ["ffmpeg"]

for i in range(0, len(labels)-1):
	video_index=(i*skip)%len(video_duration)
	position = video_duration[video_index] * (1 - scope) * i / len(labels) + random.uniform(0, video_duration[video_index] * scope - max_interval)
	duration = labels[i+1]-labels[i]-offset
	args += ["-itsoffset", "0", "-ss", str(position), "-t", str(duration), "-i", sys.argv[4+video_index]]
args += ["-filter_complex", "concat=n=%d" % (len(labels)-1), "-y", tmp_file]

subprocess.run(args)

subprocess.run(["ffmpeg", "-i", sys.argv[1], "-itsoffset", "0", "-i", tmp_file, "-c", "copy", "-y", sys.argv[3]])
