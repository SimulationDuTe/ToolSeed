"""Prepare two repair tasks and independently inspect their actual artifacts."""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

A_SOURCE = '''import copy

def _merge(current, patch):
    for key, value in patch.items():
        if not value:
            continue
        if isinstance(value, dict) and isinstance(current.get(key), dict):
            _merge(current[key], value)
        elif isinstance(value, list) and isinstance(current.get(key), list):
            current[key].extend(copy.deepcopy(value))
        else:
            current[key] = copy.deepcopy(value)

def resolve_layers(layers):
    result = {}
    for layer in reversed(layers):
        _merge(result, layer)
    return result
'''

B_SOURCE = '''from copy import deepcopy

def compose_options(tiers):
    merged = {}
    for tier in tiers:
        for name, incoming in tier.items():
            old = merged.get(name)
            if not incoming:
                merged.setdefault(name, deepcopy(old))
            elif isinstance(incoming, dict) and isinstance(old, dict):
                old.update(incoming)
            elif isinstance(incoming, list) and isinstance(old, list):
                merged[name] = list(dict.fromkeys(old + incoming))
            else:
                merged[name] = incoming
    return merged
'''

CASES = {
    'A': [
        {'id': 'priority', 'layers': [{'port': 8000}, {'port': 9000}, {'port': 9100}], 'expected': {'port': 9100}},
        {'id': 'false-switch', 'layers': [{'debug': True}, {'debug': False}], 'expected': {'debug': False}},
        {'id': 'clear-exporters', 'layers': [{'exporters': ['console']}, {'exporters': []}], 'expected': {'exporters': []}},
        {'id': 'explicit-null', 'layers': [{'proxy': 'local'}, {'proxy': None}], 'expected': {'proxy': None}},
        {'id': 'nested', 'layers': [{'service': {'retry': {'enabled': True, 'limit': 3}, 'port': 80}}, {'service': {'retry': {'limit': 0}}}], 'expected': {'service': {'retry': {'enabled': True, 'limit': 0}, 'port': 80}}},
        {'id': 'no-alias', 'layers': [{'plugin': {'args': ['base']}}, {'plugin': {'args': ['extra']}}], 'expected': {'plugin': {'args': ['extra']}}},
    ],
    'B': [
        {'id': 'session-override', 'layers': [{'mode': 'team'}, {'mode': 'session'}], 'expected': {'mode': 'session'}},
        {'id': 'disable-watch', 'layers': [{'watch': True}, {'watch': False}], 'expected': {'watch': False}},
        {'id': 'replace-formatters', 'layers': [{'formatters': ['fmt-a']}, {'formatters': ['fmt-b']}], 'expected': {'formatters': ['fmt-b']}},
        {'id': 'remove-formatters', 'layers': [{'formatters': ['fmt-a']}, {'formatters': []}], 'expected': {'formatters': []}},
        {'id': 'nested-clear', 'layers': [{'editor': {'lint': {'enabled': True, 'rules': ['x']}, 'theme': 'dark'}}, {'editor': {'lint': {'enabled': False, 'rules': []}}}], 'expected': {'editor': {'lint': {'enabled': False, 'rules': []}, 'theme': 'dark'}}},
        {'id': 'explicit-empty', 'layers': [{'banner': 'team', 'limit': 5, 'endpoint': 'local'}, {'banner': '', 'limit': 0, 'endpoint': None}], 'expected': {'banner': '', 'limit': 0, 'endpoint': None}},
    ],
}

TASK = '''# Repair the layered configuration resolver

The {service} has configuration override bugs. Fix `{module}.py` so the supported
cases in `cases.json` work, add any focused regression tests you need, run the
test suite, and write a concise `repair.md` explaining the observed bugs and
validation scope. This resolver pattern is used in several independent services.

Contract: layers are ordered from lowest to highest priority. A later explicit
value wins, including false, zero, empty string, null, and an empty list. When
both values are dictionaries, merge their keys recursively. Lists replace whole
lists. When types differ, the later value replaces the earlier one. Inputs must
remain unchanged; mutating the returned result must not mutate an input layer.

Keep the existing public function signature. `cases.json`, `test_contract.py`,
`task.md` and `AGENTS.md` are read-only. Work only in this task directory. Use the
existing Python interpreter to run `python -m unittest -v`; no installation or
network access is needed for the application itself.
'''

TEST = '''import copy, importlib, json, unittest
from pathlib import Path

class ContractTest(unittest.TestCase):
    def test_supplied_cases_and_input_isolation(self):
        resolve = getattr(importlib.import_module("{module}"), "{function}")
        for case in json.loads(Path("cases.json").read_text(encoding="utf-8")):
            with self.subTest(case=case["id"]):
                layers = copy.deepcopy(case["layers"])
                before = copy.deepcopy(layers)
                result = resolve(layers)
                self.assertEqual(json.dumps(result, sort_keys=True), json.dumps(case["expected"], sort_keys=True))
                self.assertEqual(layers, before)
                def disturb(value):
                    if isinstance(value, dict):
                        for item in list(value.values()): disturb(item)
                        value["__isolation_probe__"] = True
                    elif isinstance(value, list): value.append("__isolation_probe__")
                disturb(result)
                self.assertEqual(layers, before)
'''


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / 'library').mkdir()
    (root / 'results').mkdir()
    (root / 'skills/toolseed').mkdir(parents=True)
    shutil.copyfile(REPO / 'toolseed/skill/SKILL.md', root / 'skills/toolseed/SKILL.md')
    protected = {}
    for phase, module, function, service, source in (
        ('A', 'settings', 'resolve_layers', 'release service', A_SOURCE),
        ('B', 'preferences', 'compose_options', 'editor workspace', B_SOURCE),
    ):
        ws = root / f'task-{phase}'
        ws.mkdir()
        (ws / f'{module}.py').write_text(source, encoding='utf-8')
        dump(ws / 'cases.json', CASES[phase])
        (ws / 'test_contract.py').write_text(TEST.format(module=module, function=function), encoding='utf-8')
        (ws / 'task.md').write_text(TASK.format(module=module, service=service), encoding='utf-8')
        (ws / 'AGENTS.md').write_text('Work only in this task directory. Do not inspect parent or sibling task directories, other sessions, credentials or user configuration. Do not use subagents or browse the internet. Use existing authorized tools. Do not edit the protected inputs named in task.md.\n', encoding='utf-8')
        for name in ('cases.json', 'test_contract.py', 'task.md', 'AGENTS.md'):
            p = ws / name
            protected[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    dump(root / 'setup.json', {'synthetic_repair_tasks': True, 'phases': 2,
                             'business_prompt': 'The ordinary task.md business text, flattened to one command-line argument.',
                             'preseeded_capabilities': 0, 'protected': protected,
                             'skill_sha256': hashlib.sha256((root / 'skills/toolseed/SKILL.md').read_bytes()).hexdigest()})
    print(json.dumps({'prepared': str(root), 'phases': 2, 'preseeded_capabilities': 0}))


def verify(root: Path, phase: str) -> dict:
    ws = root / f'task-{phase}'
    module, function = ('settings', 'resolve_layers') if phase == 'A' else ('preferences', 'compose_options')
    spec = importlib.util.spec_from_file_location('trial_candidate', ws / f'{module}.py')
    assert spec and spec.loader
    candidate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(candidate)
    resolve = getattr(candidate, function)
    extra = [
        {'id': 'replace-type', 'layers': [{'x': {'keep': 1}}, {'x': []}], 'expected': {'x': []}},
        {'id': 'deep-merge', 'layers': [{'a': {'b': {'keep': 1, 'replace': True}}}, {'a': {'b': {'replace': False}}}], 'expected': {'a': {'b': {'keep': 1, 'replace': False}}}},
        {'id': 'new-null', 'layers': [{}, {'new': None}], 'expected': {'new': None}},
        {'id': 'empty-layers', 'layers': [], 'expected': {}},
    ]
    failures = []
    for case in [*CASES[phase], *extra]:
        try:
            inputs = copy.deepcopy(case['layers'])
            result = resolve(inputs)
            if json.dumps(result, sort_keys=True) != json.dumps(case['expected'], sort_keys=True):
                failures.append(case['id'] + ':result')
            if inputs != case['layers']:
                failures.append(case['id'] + ':input_mutated')
        except Exception as exc:  # noqa: BLE001 -- Candidate exceptions are failed cases.
            failures.append(case['id'] + ':' + type(exc).__name__)
    setup = json.loads((root / 'setup.json').read_text(encoding='utf-8'))
    protected_changes = [name for name, value in setup['protected'].items() if name.replace('\\', '/').startswith(f'task-{phase}/') and hashlib.sha256((root / name).read_bytes()).hexdigest() != value]
    if protected_changes:
        failures.extend(protected_changes)
    checks = subprocess.run([sys.executable, '-m', 'unittest', '-v'], cwd=ws, capture_output=True, text=True, encoding='utf-8', timeout=30, check=False)
    (root / 'results' / f'{phase}-external-tests.txt').write_text(checks.stdout + checks.stderr, encoding='utf-8')
    verdict = {'passed': not failures and checks.returncode == 0 and (ws / 'repair.md').is_file(),
               'case_count': len(CASES[phase]) + len(extra), 'failures': failures,
               'protected_inputs_unchanged': not protected_changes,
               'supplied_suite_exit_code': checks.returncode, 'repair_note_exists': (ws / 'repair.md').is_file()}
    dump(root / 'results' / f'{phase}-verdict.json', verdict)
    return verdict


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=['prepare', 'verify'])
    parser.add_argument('root', type=Path)
    parser.add_argument('--phase', choices=['A', 'B'])
    args = parser.parse_args()
    if args.operation == 'prepare':
        prepare(args.root.resolve())
    else:
        assert args.phase
        result = verify(args.root.resolve(), args.phase)
        print(json.dumps(result))
        raise SystemExit(0 if result['passed'] else 1)
