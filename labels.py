import contextlib
import datetime
import os
import re
import typing
import validators

from beauty import args, output

class Label(typing.NamedTuple):
    output_start_point: float = -1
    output_final_point: float = -1
    input_url: str = None
    input_start_point: float = -1
    input_final_point: float = -1

labels = []

def labels_created():
    return all(
        l.input_url is not None and
        l.input_start_point != -1 and
        l.input_final_point != -1
        for l in labels)

def update_labels(new_labels):
    if not args.output_max_length:
        labels[:] = new_labels
    else:
        labels[:] = [
            l for l in new_labels
            if l.output_start_point < args.output_max_length
            ]
        if labels[-1].output_final_point > args.output_max_length:
            labels[-1] = Label(
                output_start_point = labels[-1].output_start_point,
                output_final_point =
                    min(labels[-1].output_final_point, args.output_max_length),
                input_url = labels[-1].input_url,
                input_start_point = labels[-1].input_start_point,
                input_final_point =
                    labels[-1].input_start_point +
                    min(labels[-1].output_final_point, args.output_max_length) -
                    labels[-1].output_start_point
            )

def update_labels_serial(input_url):
    L, t = [], 0
    for l in labels:
        dt = l.output_final_point - l.output_start_point
        L.append(Label(
            t,
            t + dt,
            input_url,
            l.output_start_point,
            l.output_final_point
        ))
        t += dt
    labels[:] = L

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
            format_label(l) for l in (
                labels if custom_labels is None else custom_labels
            )
        )
    if args.subtitles:
        write_subtitles(
            args.subtitles_output % output if (
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
        output_start_point = parse_timestamp(t[0]),
        output_final_point = parse_timestamp(t[1]),
        input_url = t[2] if t[2:] else None,
        input_start_point = parse_timestamps(t[3]) if t[3:] else -1,
        input_final_point = parse_timestamps(t[4]) if t[4:] else -1
    )

def format_label(l: Label):
    return (format_timestamp(l.output_start_point) +
        '\t' + format_timestamp(l.output_final_point) +
        ('\t' + l.input_url
            if l.input_url else '') +
        ('\t' + format_timestamps(l.input_start_point)
            if l.input_start_point != -1 else '') +
        ('\t' + format_timestamps(l.input_final_point)
            if l.input_final_point != -1 else '') + '\n'
    )

def read_subtitles(file_name):
    with open(file_name) as f:
        return [
            Label(
                output_start_point = parse_timestamp(t[0]),
                output_final_point = parse_timestamp(t[1])
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
                format_timestamps(labels[i].output_start_point),
                format_timestamps(labels[i].output_final_point),
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
