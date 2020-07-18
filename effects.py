import functools
import math
import scipy.optimize
import warnings

from beauty import args
from audios import tempo

def visual_effects():
    effects = []
    if args.visual_effect_speedup:
        effects.append(visual_effects_speedup_cosine)
    if args.visual_effect_zooming:
        effects.append(visual_effects_zooming)
    filters = []
    mappers = []
    for e in effects:
        filter, mapper = e()
        filters.append(filter)
        mappers.append(mapper)
    return filters, mappers

def visual_effects_speedup_cosine():
    audio_tempo = (tempo(args.audio_output) *
        args.visual_effect_speedup_tempo_multi)
    def f(x, p, y):
        x0 = x * p + math.pi / 2
        return (2 * (x0 - x0 % math.pi) / math.pi
            - math.cos(x0 % math.pi)) / p - y
    warnings.filterwarnings(
        'ignore', 'The iteration is not making good progress')
    def fx(p, y):
        return f(math.pi / p, p, y)
    p = scipy.optimize.fsolve(functools.partial(fx, y=audio_tempo), 1)[0]
    filter = 'setpts=\'' \
        '(2 * (T * %.3f + PI / 2 - mod(T * %.3f + PI / 2, PI)) / PI' \
        '- cos(mod(T * %.3f + PI / 2, PI))) / %.3f / TB\'' % tuple([p] * 4)
    def mapper(y):
        return scipy.optimize.fsolve(functools.partial(f, p=p, y=y), y)[0]
    return filter, mapper

def visual_effects_speedup_custom():
    mapping = [(
        labels.labels[i].output_start_pos,
        labels.labels[i].output_end_pos,
        (i % 2) * 3 + 1
        ) for i in range(len(labels.labels))
    ]
    inverse_mapping = []
    filter = '%s'
    time = 0
    for (start, end, speed) in mapping:
        delta = (end - start) / speed
        filter = filter % ('if(lt(T,%f),%f+(T-%f)/%f,%%s)' % (
            time + delta,
            start,
            time,
            speed))
        inverse_mapping.append((time, time + delta, speed))
        time += delta
    filter = 'setpts=\'%s / TB\'' % filter % end
    def mapper(y):
        time = 0
        for (start, end, speed) in inverse_mapping:
            if start <= y <= end:
                return time + (y - start) * speed
            time += (end - start) * speed
        return time
    return filter, mapper

def visual_effects_zooming():
    return '', lambda x: x
