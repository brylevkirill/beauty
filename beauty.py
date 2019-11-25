import random, subprocess, sys, time

tmp_file="tmp.mp4"
skip=4
offset=0.043
strategy1=True
strategy2=False

labels = [0.0] + [float(line.split()[0]) for line in open(sys.argv[2])]
max_interval = max([labels[i+1]-labels[i] for i in (0, len(labels)-2)]) + 1

video_duration=[]
for i in range(4, len(sys.argv)):
	process = subprocess.run(["ffprobe", "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0", sys.argv[i]], stdout=subprocess.PIPE)
	video_duration.append(float(process.stdout))
min_duration = min(video_duration)

scope = 1.0 * len(video_duration) / len(labels)

random.seed(time.time())

args = []
for i in range(0, len(labels)-1):
	video_index=(i*skip)%len(video_duration)
	position = video_duration[video_index] * (1 - scope) * i / len(labels) + random.uniform(0, video_duration[video_index] * scope - max_interval)
	duration = labels[i+1]-labels[i]-offset
	largs = ["-ss", str(position), "-t", str(duration), "-i", sys.argv[4+video_index]]
	if strategy1:
		args += largs
	elif strategy2:
		subprocess.run(["ffmpeg"] + largs + ["-c", "copy", "-an", "-y", "%d.mp4"%i])
if strategy1:
	args += ["-filter_complex", "concat=n=%d" % (len(labels)-1), "-y", tmp_file]
	subprocess.run(["ffmpeg"] + args)
elif strategy2:
	subprocess.run(["ffmpeg", "-i", "concat:" + "|".join(["%d.mp4"%i for i in range(0, len(labels)-1)]), "-c", "copy", "-y", tmp_file])

if strategy1 or strategy2:
	subprocess.run(["ffmpeg", "-i", sys.argv[1], "-i", tmp_file, "-c", "copy", "-y", sys.argv[3]])
