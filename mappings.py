import contextlib
import datetime
import os
import re
import typing
import validators

from beauty import args

class Resource(typing.NamedTuple):
    url: str = None
    start: float = -1
    final: float = -1

class Mapping(typing.NamedTuple):
    source: Resource = None
    target: Resource = None

mappings = []

def mappings_complete():
    return all(
        mapping.source is not None and
        mapping.source.url is not None and
        mapping.source.start != -1 and
        mapping.source.final != -1
        for mapping in mappings)

def update(new_mappings):
    if not args.output_max_length:
        mappings[:] = new_mappings
    else:
        mappings[:] = [
            mapping for mapping in new_mappings
            if mapping.target.start < args.output_max_length
        ]
        if mappings[-1].target.final > args.output_max_length:
            mappings[-1] = Mapping(
                source = Resource(
                    url = mappings[-1].source.url,
                    start = mappings[-1].source.start,
                    final = (
                        mappings[-1].source.start +
                        args.output_max_length -
                        mappings[-1].target.start
                    )
                ),
                target = Resource(
                    url = mappings[-1].target.url,
                    start = mappings[-1].target.start,
                    final = args.output_max_length
                )
            )

def update_filter(source_mappings, target_mappings, timestamp):
    import datetime
    ts = datetime.datetime.utcfromtimestamp(timestamp)
    t = ts.strftime('%H:%M:%S.%f')[:-3]
    lines = []
    with open(target_mappings) as f:
        lines.extend(
            s for s in f.readlines()
            if s.split()[1] <= t
        )
    with open(source_mappings) as f:
        lines.extend(
            (s[:s.rindex('\t')] + s[-1]) for s in f.readlines()
            if s.split()[0] <= t and t < s.split()[1]
        )
    with open(target_mappings) as f:
        lines.extend(
            s for s in f.readlines()
            if t < s.split()[0]
        )
    with open(target_mappings, 'w') as f:
        f.writelines(lines)

def read(custom_file_name=None):
    file_name = args.mappings if custom_file_name is None else custom_file_name
    with open(file_name) as f:
        mappings[:] = [parse_mapping(s) for s in f.read().splitlines()]

def write(custom_file_name=None, custom_mappings=None):
    file_name = args.mappings if custom_file_name is None else custom_file_name
    with open(file_name, 'w') as f:
        f.writelines(
            format_mapping(mapping) for mapping in (
                mappings if custom_mappings is None else custom_mappings
            )
        )
    if args.output_subtitles:
        write_subtitles(
            args.subtitles_output % args.media_output if (
                '%' in args.subtitles_output)
            else args.subtitles_output)

def parse_mapping(s):
    t = s.split('\t')
    if t[2:]:
        regexp = None
        with contextlib.suppress(re.error):
            regexp = re.compile(t[2])
        if (not 'regexp' in locals() and
            not os.path.isfile(t[2]) and
            not validators.url(t[2].replace('---', '-'))):
            raise ValueError('Invalid value "%s".' % t[2])
    return Mapping(
        source = Resource(
            url = t[2] if t[2:] else None,
            start = parse_timestamps(t[3]) if t[3:] else -1,
            final = parse_timestamps(t[4]) if t[4:] else -1
        ),
        target = Resource(
            start = parse_timestamp(t[0]),
            final = parse_timestamp(t[1])
        )
    )

def format_mapping(mapping: Mapping):
    return (format_timestamp(mapping.target.start) +
        '\t' + format_timestamp(mapping.target.final) +
        ('\t' + mapping.source.url
            if mapping.source and mapping.source.url else '') +
        ('\t' + format_timestamps(mapping.source.start)
            if mapping.source and mapping.source.start != -1 else '') +
        ('\t' + format_timestamps(mapping.source.final)
            if mapping.source and mapping.source.final != -1 else '') + '\n'
    )

def read_subtitles(file_name):
    with open(file_name) as f:
        return [
            Mapping(
                target = Resource(
                    start = parse_timestamp(t[0]),
                    final = parse_timestamp(t[1])
                )
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
                format_timestamps(mappings[i].target.start),
                format_timestamps(mappings[i].target.final),
                i + 1)
            for i in range(len(mappings))
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
