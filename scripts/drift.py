"""List the differences between this Mac and the playbook config.

Shows what is installed here but missing from the config, and what the config
asks for that is not installed: Homebrew formulae, casks and taps, App Store
apps, global npm packages, and the optional uv_tools and cargo_packages lists.
The config is default.config.yml with config.yml (or --config) laid over it,
key by key, as the playbook loads it. Exits 1 when anything differs.

Needs a Python with PyYAML, such as Homebrew Ansible's:

    "$(brew --prefix ansible)/libexec/bin/python3" scripts/drift.py
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit('drift.py needs PyYAML; run it with "$(brew --prefix ansible)/libexec/bin/python3".')

PLAYBOOK_DIR = Path(__file__).resolve().parent.parent


def run(*cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def names(items):
    return [str(item['name'] if isinstance(item, dict) else item) for item in items or []]


def ids(entry):
    """Every spelling of a config entry: as written and without its tap."""
    return {entry, entry.split('/')[-1]}


def compare(label, here, wanted, here_ids, installed_ids=None):
    """here: names to account for; wanted: config names; here_ids: name -> spellings.

    installed_ids, when given, is every installed spelling (dependencies too)
    and decides what counts as installed; otherwise here_ids does.
    """
    wanted_ids = set().union(*(ids(w) for w in wanted))
    all_here_ids = installed_ids if installed_ids is not None else set().union(*here_ids.values())
    extra = sorted(h for h in here if not here_ids[h] & wanted_ids)
    missing = sorted(w for w in wanted if not ids(w) & all_here_ids)
    if extra:
        print(f'{label}: on this Mac, not in config: {", ".join(extra)}')
    if missing:
        print(f'{label}: in config, not installed: {", ".join(missing)}')
    return bool(extra or missing)


def load_config(path):
    config = yaml.safe_load((PLAYBOOK_DIR / 'default.config.yml').read_text()) or {}
    if path.exists():
        config.update(yaml.safe_load(path.read_text()) or {})
    else:
        print(f'note: {path} not found; comparing against default.config.yml only')
    return config


def app_store_apps():
    """App Store apps in /Applications, by id, read from their receipts."""
    apps = {}
    for app in Path('/Applications').glob('*.app'):
        if (app / 'Contents/_MASReceipt').exists():
            adam = run('mdls', '-raw', '-name', 'kMDItemAppStoreAdamID', str(app)).strip()
            if adam.isdigit():
                apps[adam] = app.stem
    return apps


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--config', type=Path, default=PLAYBOOK_DIR / 'config.yml')
    config = load_config(parser.parse_args().config)
    drift = False

    info = json.loads(run('brew', 'info', '--json=v2', '--installed'))
    formula_ids = {
        f['full_name']: {f['name'], f['full_name'], *f.get('aliases', []), *f.get('oldnames', [])}
        for f in info['formulae']
    }
    implied = []  # Formulae the playbook's roles install on their own.
    if config.get('configure_dock'):
        implied.append('dockutil')
    if config.get('mas_installed_apps') or config.get('mas_installed_app_ids'):
        implied.append('mas')
    leaves = run('brew', 'leaves').split()
    drift |= compare('formulae', leaves, names(config.get('homebrew_installed_packages')) + implied,
                     {leaf: formula_ids.get(leaf, {leaf}) for leaf in leaves},
                     set().union(*formula_ids.values()))

    cask_ids = {c['full_token']: {c['token'], c['full_token'], *c.get('old_tokens', [])} for c in info['casks']}
    drift |= compare('casks', list(cask_ids), names(config.get('homebrew_cask_apps')), cask_ids)

    taps = [t for t in run('brew', 'tap').split() if t not in ('homebrew/core', 'homebrew/cask')]
    drift |= compare('taps', taps, names(config.get('homebrew_taps')), {t: {t} for t in taps})

    store = app_store_apps()
    wanted = [str(a['id'] if isinstance(a, dict) else a)
              for a in (config.get('mas_installed_apps') or []) + (config.get('mas_installed_app_ids') or [])]
    if compare('App Store ids', list(store), wanted, {a: {a} for a in store}):
        drift = True
        print('  (installed App Store apps: ' + ', '.join(f'{k} {v}' for k, v in sorted(store.items())) + ')')

    if shutil.which('npm'):
        tree = json.loads(run('npm', 'ls', '-g', '--depth=0', '--json'))
        npm = [p for p in tree.get('dependencies', {}) if p not in ('npm', 'corepack')]
        drift |= compare('npm -g', npm, names(config.get('npm_packages')), {p: {p} for p in npm})

    for label, key, tool, cmd in (('uv tools', 'uv_tools', 'uv', ('uv', 'tool', 'list')),
                                  ('cargo', 'cargo_packages', 'cargo', ('cargo', 'install', '--list'))):
        if key not in config and not shutil.which(tool):
            continue
        here = [line.split()[0] for line in (run(*cmd) if shutil.which(tool) else '').splitlines()
                if line and not line[0].isspace() and not line.startswith('-') and ' v' in line]
        drift |= compare(label, here, names(config.get(key)), {h: {h} for h in here})

    if not drift:
        print('No drift.')
    return 1 if drift else 0


if __name__ == '__main__':
    sys.exit(main())
