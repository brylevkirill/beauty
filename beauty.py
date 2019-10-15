import random, subprocess, sys

tmp_file="tmp.mp4"

labels = [0.0] + [float(line.split()[0]) for line in open(sys.argv[2])]

video_duration=[]
for i in range(4, len(sys.argv)):
	process = subprocess.run(["ffprobe", "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0", sys.argv[i]], stdout=subprocess.PIPE)
	video_duration.append(float(process.stdout))

args = ["ffmpeg"]
for i in range(0, len(labels)-1):
	video_index=random.randint(0, len(video_duration)-1)
	position = 10 + random.uniform(0, video_duration[video_index]-30)
	args += ["-itsoffset", "-0.7", "-ss", str(position), "-t", str(labels[i+1]-labels[i]), "-i", sys.argv[4+video_index]]
args += ["-filter_complex", "concat=n=%d" % (len(labels)-1), "-y", tmp_file]
print(*args)
subprocess.run(args)

subprocess.run(["ffmpeg", "-i", sys.argv[1], "-itsoffset", "-1.0", "-i", tmp_file, "-c", "copy", "-y", sys.argv[3]])
