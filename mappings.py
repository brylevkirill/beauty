import contextlib
import datetime
import os
import re
import typing
import validators

from . import args

class Resource(typing.NamedTuple):
    url: str = None
    start: float = -1
    final: float = -1

class Mapping(typing.NamedTuple):
    source: Resource = None
    target: Resource = None

def read(file):
    file = file or args.mappings
    if not os.path.exists(file):
        return []
    with open(file, 'r') as f:
        mappings = \
            list(
                map(
                    parse_mapping,
                    f.read().splitlines()
                )
            )
        return mappings

def write(file, mappings):
    with open(args.mappings, 'w') as f:
        f.writelines(
            map(format_mapping, mappings)
        )
    if args.output_subtitles:
        write_subtitles(
            args.subtitles_output
                .format(args.media_output)
            if '{}' in args.subtitles_output
                else args.subtitles_output,
            mappings
        )

def parse_mapping(s):
    t = s.split('\t')
    if t[2:]:
        regexp = None
        with contextlib.suppress(re.error):
            regexp = re.compile(t[2])
        if not 'regexp' in locals() and \
            not os.path.isfile(t[2]) and \
            not validators.url(
                t[2].replace('---', '-')
            ):
            raise ValueError(
                f'Invalid value "{t[2]}".'
            )
    return Mapping(
        source=
            Resource(
                url=t[2] if t[2:] else None,
                start=parse_timestamp(t[3])
                    if t[3:] else -1,
                final=parse_timestamp(t[4])
                    if t[4:] else -1
            ),
        target=
            Resource(
                start=parse_timestamp(t[0]),
                final=parse_timestamp(t[1])
            )
    )

def format_mapping(mapping):
    _mapping = [
        format_timestamp(mapping.target.start),
        format_timestamp(mapping.target.final)
    ]
    if mapping.source:
        if mapping.source.url:
            _mapping.append(mapping.source.url)
        if mapping.source.start != -1:
            _mapping.append(
                format_timestamp(
                    mapping.source.start
                )
            )
        if mapping.source.final != -1:
            _mapping.append(
                format_timestamp(
                    mapping.source.final
                )
            )
    return '\t'.join(_mapping) + '\n'

def read_subtitles(file):
    with open(file, 'r') as f:
        return [
            Mapping(
                target=
                    Resource(
                        start=
                            parse_timestamp(t[0]),
                        final=
                            parse_timestamp(t[1])
                    )
            ) for s in f.read().splitlines()
                for t in s.split(' --> ')
                    if t[1:]
        ]

def write_subtitles(file, mappings):
    with open(file, 'w') as f:
        f.writelines(
            '{}\n{} --> {}\n{}\n\n'
                .format(
                    index + 1,
                    format_timestamp(
                        item.target.start
                    ),
                    format_timestamp(
                        item.target.final
                    ),
                    index + 1
                ) for index, item in
                    enumerate(mappings)
        )

def parse_timestamp(s):
    try:
        return float(s)
    except ValueError:
        pass
    t = s.split(':')
    if t[1:] and int(t[0]) >= 60:
        s = ':'.join((
            str(int(t[0]) // 60),
            str(int(t[0]) % 60).zfill(2),
            *t[1:]
        ))
    if '.' not in s:
        s += '.0'
    try:
        t = datetime.datetime \
            .strptime(s, '%H:%M:%S.%f')
    except ValueError:
        try:
            t = datetime.datetime \
                .strptime(s, '%H:%M:%S.%f')
        except ValueError:
            t = datetime.datetime \
                .strptime(s, '%M:%S.%f')
    return t.hour * 3600 + \
        t.minute * 60 + \
        t.second + \
        t.microsecond * 0.000001

def format_timestamp(t):
    return datetime.datetime \
        .utcfromtimestamp(t) \
            .strftime('%H:%M:%S.%f')[:-3]
