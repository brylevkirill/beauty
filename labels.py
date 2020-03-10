import collections
import datetime

import beauty
from beauty import args

Label = collections.namedtuple('Label', '''
    output_start_pos
    output_end_pos
    input_file_name
    input_start_pos
    input_end_pos
    ''')
labels = []

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
    if args.subtitles:
        write_titles()

def write_titles():
    open(beauty.output + '.srt', 'w').writelines(
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
