import functools
import math
import warnings

from . import args
from .audios import tempo

def visual_effects():
    effects = []
    if args.visual_effect_speedup:
        effects.append(
            visual_effects_speedup_cosine
        )
    filters = []
    mappers = []
    for e in effects:
        filter, mapper = e()
        filters.append(filter)
        mappers.append(mapper)
    return filters, mappers

def visual_effects_speedup_cosine():
    interval = 60 * (
        args.visual_effect_speedup_freq /
            tempo(args.audio_output)
    )
    def f(x, p, y):
        x0 = x * p + math.pi / 2
        return (
            2 * (x0 - x0 % math.pi) / math.pi
                - math.cos(x0 % math.pi)
            ) / p - y
    warnings.filterwarnings(
        'ignore',
        'The iteration is not '
            'making good progress'
    )
    def fx(p, y): return f(math.pi / p, p, y)
    import scipy.optimize
    p = scipy.optimize.fsolve(
        functools.partial(fx, y=interval), 1
        )[0]
    filter = (
        'setpts=\'('
            '('
                'T * :.6f + PI / 2 - '
                    'mod(T * :.6f + PI / 2, PI)'
                ') / PI * 2 - cos('
                    'mod(T * :.6f + PI / 2, PI)'
                    ')'
            ') / :.6f / TB\''
        ).format(*([p] * 4))
    def mapper(y):
        return scipy.optimize.fsolve(
            functools.partial(f, p=p, y=y), y
        )[0]
    return filter, mapper

def visual_effects_speedup_custom(mappings):
    mapping = [
        (
            item.target.start,
            item.target.final,
            (item.source.final -
                item.source.start) /
            (item.target.final -
                item.target.start)
        ) for item in mappings
    ]
    inverse_mapping = []
    filter = '{}'
    time = 0
    for (start, final, speed) in mapping:
        delta = (final - start) * speed
        filter = filter.format(
            'if(lt(T,{}),{}+(T-{})*{},{{}})'
                .format(
                    time + delta,
                    start,
                    time,
                    speed
                )
            )
        inverse_mapping.append(
            (time, time + delta, speed)
        )
        time += delta
    filter = \
        f'setpts=\'{filter} / TB\'' \
            .format(final)
    def mapper(y):
        time = 0
        for start, final, speed \
            in inverse_mapping:
            if start <= y <= final:
                return time + \
                    (y - start) / speed
            time += (final - start) / speed
        return time
    return filter, mapper
