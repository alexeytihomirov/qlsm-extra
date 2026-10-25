"""Which cvars the Live Settings tab lists for an instance, and where each
value comes from.

Two kinds of rows:

- plugin cvars: for every plugin in the instance's `qlx_plugins`, the cvars
  its `<plugin>.ql-plugin.json` sidecar declares (the same file qlsm's own
  Plugins tab uses for its edit form). Looked up through core's manifest
  resolver so the pool copy wins, exactly like the Plugins tab.
- pinned cvars: engine cvars the operator added to this instance's list
  (timelimit, g_password, ...). Stored in the addon's own per-instance
  settings as a comma-separated string, so the Addons page shows and edits
  the same list.

The server.cfg column reads qlsm's copy of the file
(configs/<host>/<instance>/server.cfg); the live column is filled by the
caller from one rcon round trip.
"""
import os
import re

from .cvar_text import CVAR_NAME_RE, read_cvar

CVAR_TYPES = ('bool', 'number', 'string')
PINNED_KEY = 'pinned_cvars'
MAX_PINNED = 60


def plugin_names(instance):
    raw = getattr(instance, 'qlx_plugins', None) or ''
    seen, out = set(), []
    for part in re.split(r'[,\s]+', raw):
        name = part.strip()
        if name and name not in seen:
            seen.add(name)
            out.append(name)
    return out


def normalize_cvars(manifest):
    """The sidecar's `cvars` list in a safe, uniform shape (mirrors
    getPluginCvars in qlsm's pluginManifest.js): a bad entry is dropped."""
    cvars = (manifest or {}).get('cvars')
    if not isinstance(cvars, list):
        return []
    out = []
    for entry in cvars:
        if not isinstance(entry, dict):
            continue
        name = entry.get('cvar')
        if not isinstance(name, str) or not CVAR_NAME_RE.match(name):
            continue
        ctype = entry.get('type') if entry.get('type') in CVAR_TYPES else 'string'
        row = {
            'name': name,
            'label': _text(entry.get('label')),
            'description': _text(entry.get('description')),
            'type': ctype,
            'default': _default_text(ctype, entry.get('default')),
        }
        for bound in ('min', 'max'):
            value = entry.get(bound)
            if ctype == 'number' and isinstance(value, (int, float)) and not isinstance(value, bool):
                row[bound] = value
        out.append(row)
    return out


def _text(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def _default_text(ctype, value):
    """A manifest default as the string the engine would hold."""
    if value is None:
        return None
    if ctype == 'bool':
        if isinstance(value, bool):
            return '1' if value else '0'
        return '1' if str(value).strip().lower() in ('1', 'true') else '0'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def plugin_groups(instance):
    """One group per plugin that declares cvars, in qlx_plugins order."""
    from ui.plugin_manifest import read_plugin_manifest
    from ui.runtime import normalize_runtime

    runtime = normalize_runtime(getattr(instance.host, 'runtime', None)) if instance.host else None
    groups = []
    for name in plugin_names(instance):
        manifest = read_plugin_manifest(name + '.py', runtime=runtime)
        cvars = normalize_cvars(manifest)
        if not cvars:
            continue
        groups.append({
            'id': f'plugin:{name}',
            'label': _text((manifest or {}).get('label')) or name,
            'subtitle': f'plugin {name}.py',
            'cvars': cvars,
        })
    return groups


def pinned_cvars(settings, instance_id):
    raw = (settings.get('instance', instance_id) or {}).get(PINNED_KEY) or ''
    seen, out = set(), []
    for part in re.split(r'[,\s]+', raw):
        name = part.strip()
        if name and CVAR_NAME_RE.match(name) and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out[:MAX_PINNED]


def set_pinned_cvars(settings, instance_id, names):
    """Validate and store the pinned list; returns the stored names."""
    cleaned, seen = [], set()
    for name in names:
        if not isinstance(name, str):
            raise ValueError('cvar names must be strings')
        name = name.strip()
        if not CVAR_NAME_RE.match(name) or len(name) > 64:
            raise ValueError(f'"{name}" is not a cvar name (letters, digits and _ only)')
        if name.lower() not in seen:
            seen.add(name.lower())
            cleaned.append(name)
    if len(cleaned) > MAX_PINNED:
        raise ValueError(f'at most {MAX_PINNED} pinned cvars')
    settings.set('instance', instance_id, {PINNED_KEY: ', '.join(cleaned)})
    return cleaned


def pinned_group(settings, instance_id, descriptions=None):
    names = pinned_cvars(settings, instance_id)
    descriptions = descriptions or {}
    return {
        'id': 'pinned',
        'label': 'Server',
        'subtitle': 'cvars you pinned to this instance',
        'cvars': [{
            'name': name, 'label': None,
            'description': descriptions.get(name.lower()),
            'type': 'string', 'default': None,
        } for name in names],
    }


def server_cfg_path(instance):
    if not instance.host:
        return None
    return os.path.join('configs', instance.host.name, str(instance.id), 'server.cfg')


def read_server_cfg(instance):
    """(path, text) -- text is None when qlsm has no copy of the file."""
    path = server_cfg_path(instance)
    if not path:
        return None, None
    try:
        with open(path, 'r', encoding='utf-8', errors='replace', newline='') as f:
            return path, f.read()
    except OSError:
        return path, None


def catalog_descriptions():
    """{lower name: description} from qlsm's own cvar catalog, for pinned
    rows and the add-a-cvar suggestions. Empty when the catalog is missing."""
    try:
        from ui.routes.cvar_catalog_routes import load_catalog
        payload, _etag = load_catalog()
        payload = payload or {}
    except Exception:
        return {}
    out = {}
    for entry in payload.get('cvars') or []:
        name = entry.get('name') if isinstance(entry, dict) else None
        if isinstance(name, str) and name:
            out[name.lower()] = _text(entry.get('description'))
    return out


def all_names(groups):
    seen, out = set(), []
    for group in groups:
        for cvar in group['cvars']:
            if cvar['name'].lower() not in seen:
                seen.add(cvar['name'].lower())
                out.append(cvar['name'])
    return out


def fill_values(groups, cfg_text, live):
    """Attach `cfg`, `live`, `live_default`, `latched`, `reported` to every
    row. `live` is the parsed rcon reply ({lower name: entry}) or None when
    the server could not be asked."""
    for group in groups:
        for cvar in group['cvars']:
            cvar['cfg'] = read_cvar(cfg_text, cvar['name']) if cfg_text is not None else None
            entry = (live or {}).get(cvar['name'].lower())
            cvar['reported'] = entry is not None
            cvar['live'] = entry['value'] if entry else None
            cvar['live_default'] = entry['default'] if entry else None
            cvar['latched'] = entry['latched'] if entry else None
    return groups
