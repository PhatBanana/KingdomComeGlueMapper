"""Registry of data-driven KCD1 work adapters for population work.

A KCD1 work tree is supported once, in every town: an adapter module claims
source trees by structure (``supports``), resolves its workplace from the
source smart area (``resolve``) and binds a native KCD2 program onto the
importer-owned arrival (``bind``). The dispatchers in character_schedule_world
and character_schedule_jobs ask this registry instead of growing one branch per
profession.

Adapter module contract:
  supports(entry) -> bool
  resolve(entry, archive, source, reader) -> entry with ``<key>`` set and ``arrival``
  bind(mission, scheduler, person, entry, target) -> (job, waiting_links, report)
      report carries ``interval``; it is turned into ``intervals`` per pool.
  ACTIVITY (optional): the behaviour name the job's ``_,use`` edge is renamed to.
"""
from collections import namedtuple
import importlib

Adapter = namedtuple('Adapter', 'module key')

# One row per adapter module; each module decides which KCD1 trees it claims.
ADAPTERS = (
    Adapter('character_workplace_work', 'workplace_work'),
    Adapter('character_pub_visitor_work', 'pub_visitor_work'),
)


def _modules():
    for adapter in ADAPTERS:
        try:
            module = importlib.import_module(adapter.module)
        except ModuleNotFoundError as error:
            if error.name != adapter.module:
                raise
            continue
        yield adapter, module


def adapter_for(entry):
    """(Adapter, module) claiming this resolved schedule entry, or None."""
    claims = [(a, m) for a, m in _modules() if m.supports(entry)]
    if len(claims) > 1:
        raise ValueError('Work adapters overlap on ' + entry['behavior']['tree_name'] + ': '
                         + ', '.join(a.module for a, _ in claims))
    return claims[0] if claims else None


def supports(entry):
    return adapter_for(entry) is not None


def resolve(entry, archive, source, reader):
    """Resolved entry, or None when no registered adapter claims it."""
    claim = adapter_for(entry)
    if claim is None:
        return None
    adapter, module = claim
    if source is None or reader is None:
        raise ValueError(adapter.module + ' requires its effective source behavior')
    result = module.resolve(entry, archive, source, reader)
    if not result.get(adapter.key) or not result.get('arrival'):
        raise ValueError(adapter.module + ' resolved no workplace')
    return result


def bind(mission, scheduler, person, entry, target, pools):
    """Bind one entry if an adapter resolved it. Returns None when not ours, else
    (job_or_None, waiting_links, report_or_None, activity). Repeated intervals on the
    same person and anchor extend the first pool instead of binding twice."""
    for adapter, module in _modules():
        contract = entry.get(adapter.key)
        if not contract:
            continue
        key = (adapter.key, person, entry['arrival']['EntityGuid'])
        if key in pools:
            previous, report = pools[key]
            if previous != contract:
                raise ValueError('Different ' + adapter.key + ' pools share one schedule anchor')
            report['intervals'].append([entry['start_minute'], entry['end_minute']])
            return None, [], None, None
        job, waiting, report = module.bind(mission, scheduler, person, entry, target)
        report['intervals'] = [report.pop('interval', [entry['start_minute'], entry['end_minute']])]
        pools[key] = (contract, report)
        return job, waiting, report, getattr(module, 'ACTIVITY', '')
    return None
