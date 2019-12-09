import random, subprocess, sys, time

tmp_file="tmp.mp4"
skip=4
offset=0.043
strategy1=True
strategy2=False

labels = [
    (float(line.split('\t')[0]),
    float(line.split('\t')[1]),
    next(iter(line.split('\t')[2:3]), None),
    float(next(iter(line.split('\t')[3:4]), 0)),
    float(next(iter(line.split('\t')[4:5]), 0)))
    for line in open(sys.argv[2]).read().splitlines()]
max_interval = max([labels[i][1]-labels[i][0] for i in range(len(labels))]) + 1

videos={}
for v in sys.argv[4:]:
	videos[v] = None
for l in labels:
	if l[2] is not None:
		videos[l[2]] = None
for v in videos:
	process = subprocess.run(["ffprobe", "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0", v], stdout=subprocess.PIPE)
	videos[v] = float(process.stdout)

scope = 1.0 * len(videos) / len(labels)

random.seed(time.time())

args = []
for i in range(len(labels)):
	l = labels[i]
	file_name = l[2] if l[2] is not None else sys.argv[4 + (i*skip+3)%len(sys.argv[4:])]
	start_position = l[3] if l[3] != 0 else videos[file_name] * (1 - scope) * i / len(labels) + random.uniform(0, videos[file_name] * scope - max_interval)
	finish_position = l[4] if l[4] != 0 else start_position + l[1] - l[0] - offset
	labels[i] = (l[0], l[1], file_name, start_position, finish_position)
	largs = ["-ss", str(start_position), "-t", str(finish_position - start_position), "-i", file_name]
	if strategy1:
		args += largs
	elif strategy2:
		subprocess.run(["ffmpeg"] + largs + ["-c", "copy", "-an", "-y", "%d.mp4"%i])

open(sys.argv[2], 'w').writelines("%f\t%f\t%s\t%f\t%f\n" % (l[0], l[1], l[2], l[3], l[4]) for l in labels)

if strategy1:
	args += ["-filter_complex", "concat=n=%d" % (len(labels)), "-y", tmp_file]
	subprocess.run(["ffmpeg"] + args)
elif strategy2:
	subprocess.run(["ffmpeg", "-i", "concat:" + "|".join(["%d.mp4"%i for i in range(0, len(labels))]), "-c", "copy", "-y", tmp_file])

if strategy1 or strategy2:
	subprocess.run(["ffmpeg", "-i", sys.argv[1], "-i", tmp_file, "-c", "copy", "-y", sys.argv[3]])
