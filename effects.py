import functools
import math
import scipy.optimize
import warnings

import beauty.mappings as mappings
from . import args
from .audios import tempo

def visual_effects():
    effects = []
    if args.visual_effect_speedup:
        effects.append(visual_effects_speedup_cosine)
    filters = []
    mappers = []
    for e in effects:
        filter, mapper = e()
        filters.append(filter)
        mappers.append(mapper)
    return filters, mappers

def visual_effects_speedup_cosine():
    interval = 60 / tempo(args.audio_output) / args.visual_effect_speedup_freq
    def f(x, p, y):
        x0 = x * p + math.pi / 2
        return (2 * (x0 - x0 % math.pi) / math.pi
            - math.cos(x0 % math.pi)) / p - y
    warnings.filterwarnings(
        'ignore', 'The iteration is not making good progress')
    def fx(p, y):
        return f(math.pi / p, p, y)
    p = scipy.optimize.fsolve(functools.partial(fx, y=interval), 1)[0]
    filter = 'setpts=\'' \
        '(2 * (T * %.6f + PI / 2 - mod(T * %.6f + PI / 2, PI)) / PI' \
        '- cos(mod(T * %.6f + PI / 2, PI))) / %.6f / TB\'' % tuple([p] * 4)
    def mapper(y):
        return scipy.optimize.fsolve(functools.partial(f, p=p, y=y), y)[0]
    return filter, mapper

def visual_effects_speedup_custom():
    mapping = [(
        mappings.mappings[i].target.start,
        mappings.mappings[i].target.final,
        (mappings.mappings[i].source.final -
            mappings.mappings[i].source.start) /
        (mappings.mappings[i].target.final -
            mappings.mappings[i].target.start)
        ) for i in range(len(mappings.mappings))
    ]
    inverse_mapping = []
    filter = '%s'
    time = 0
    for (start, final, speed) in mapping:
        delta = (final - start) * speed
        filter = filter % ('if(lt(T,%f),%f+(T-%f)*%f,%%s)' % (
            time + delta,
            start,
            time,
            speed))
        inverse_mapping.append((time, time + delta, speed))
        time += delta
    filter = 'setpts=\'%s / TB\'' % filter % final
    def mapper(y):
        time = 0
        for (start, final, speed) in inverse_mapping:
            if start <= y <= final:
                return time + (y - start) / speed
            time += (final - start) / speed
        return time
    return filter, mapper
