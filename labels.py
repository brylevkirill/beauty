import contextlib
import datetime
import os
import re
import typing
import validators

from beauty import args

class Label(typing.NamedTuple):
    start: float = -1
    final: float = -1
    input: str = None
    input_start: float = -1
    input_final: float = -1

labels = []

def labels_created():
    return all(
        label.input is not None and
        label.input_start != -1 and
        label.input_final != -1
        for label in labels)

def update_labels(new_labels):
    if not args.output_max_length:
        labels[:] = new_labels
    else:
        labels[:] = [
            label for label in new_labels
            if label.start < args.output_max_length
        ]
        if labels[-1].final > args.output_max_length:
            labels[-1] = Label(
                start = labels[-1].start,
                final = min(labels[-1].final, args.output_max_length),
                input = labels[-1].input,
                input_start = labels[-1].input_start,
                input_final =
                    labels[-1].input_start +
                    min(labels[-1].final, args.output_max_length) -
                    labels[-1].start
            )

def update_labels_filter(source_labels, target_labels, timestamp):
    import datetime
    ts = datetime.datetime.utcfromtimestamp(timestamp)
    t = ts.strftime('%H:%M:%S.%f')[:-3]
    lines = []
    with open(target_labels) as f:
        lines.extend(
            s for s in f.readlines()
            if s.split()[1] <= t
        )
    with open(source_labels) as f:
        lines.extend(
            (s[:s.rindex('\t')] + s[-1]) for s in f.readlines()
            if s.split()[0] <= t and t < s.split()[1]
        )
    with open(target_labels) as f:
        lines.extend(
            s for s in f.readlines()
            if t < s.split()[0]
        )
    with open(target_labels, 'w') as f:
        f.writelines(lines)

def read_labels(custom_file_name=None):
    file_name = args.labels if custom_file_name is None else custom_file_name
    with open(file_name) as f:
        labels[:] = [parse_label(s) for s in f.read().splitlines()]

def write_labels(custom_file_name=None, custom_labels=None):
    file_name = args.labels if custom_file_name is None else custom_file_name
    with open(file_name, 'w') as f:
        f.writelines(
            format_label(label) for label in (
                labels if custom_labels is None else custom_labels
            )
        )
    if args.subtitles:
        write_subtitles(
            args.subtitles_output % args.media_output if (
                '%' in args.subtitles_output)
            else args.subtitles_output)

def parse_label(s):
    t = s.split('\t')
    if t[2:]:
        regexp = None
        with contextlib.suppress(re.error):
            regexp = re.compile(t[2])
        if (not 'regexp' in locals() and
            not os.path.isfile(t[2]) and
            not validators.url(t[2].replace('---', '-'))):
            raise ValueError('Invalid value "%s".' % t[2])
    return Label(
        start = parse_timestamp(t[0]),
        final = parse_timestamp(t[1]),
        input = t[2] if t[2:] else None,
        input_start = parse_timestamps(t[3]) if t[3:] else -1,
        input_final = parse_timestamps(t[4]) if t[4:] else -1
    )

def format_label(label: Label):
    return (format_timestamp(label.start) +
        '\t' + format_timestamp(label.final) +
        ('\t' + label.input
            if label.input else '') +
        ('\t' + format_timestamps(label.input_start)
            if label.input_start != -1 else '') +
        ('\t' + format_timestamps(label.input_final)
            if label.input_final != -1 else '') + '\n'
    )

def read_subtitles(file_name):
    with open(file_name) as f:
        return [
            Label(
                start = parse_timestamp(t[0]),
                final = parse_timestamp(t[1])
            )
            for t in (
                s.split(' --> ') for s in f.read().splitlines()
            )
            if t[1:]
            ]

def write_subtitles(file_name):
    with open(file_name, 'w') as f:
        f.writelines(
            '%d\n%s --> %s\n%d\n\n' % (
                i + 1,
                format_timestamps(labels[i].start),
                format_timestamps(labels[i].final),
                i + 1)
            for i in range(len(labels))
        )

def parse_timestamps(s):
    ts = [parse_timestamp(t) for t in s.split(',')]
    return ts if len(ts) > 1 else ts[0]

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
    if '.' not in s:
        s += '.0'
    try:
        t = datetime.datetime.strptime(s, '%H:%M:%S.%f')
    except ValueError:
        try:
            t = datetime.datetime.strptime(s, '%H:%M:%S.%f')
        except ValueError:
            t = datetime.datetime.strptime(s, '%M:%S.%f')
    return t.hour * 3600 + t.minute * 60 + t.second + t.microsecond * 0.000001

def format_timestamps(t):
    ts = t if type(t) is list else [t]
    return ','.join(format_timestamp(x) for x in ts)

def format_timestamp(t):
    return datetime.datetime.utcfromtimestamp(t).strftime('%H:%M:%S.%f')[:-3]
