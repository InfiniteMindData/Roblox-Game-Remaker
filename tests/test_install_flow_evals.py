"""Installation boundaries, honest provisional gates and artifact outcome regressions."""
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/roblox-game-remaker'
SCRIPTS = SKILL / 'scripts'
SAMPLE = SKILL / 'examples/04-sample-workspace/remake'


def run(script, *args):
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


class InstallFlowTests(unittest.TestCase):
    def test_layouts_initialize_project_not_install(self):
        for layout in ['skills', '.agents/skills', '.claude/skills', 'plugin/cache/version/skills', 'skills-cli/.agents/skills']:
            with self.subTest(layout=layout), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                project = root / 'project with spaces'
                project.mkdir()
                install_root = root if layout.startswith('plugin/') else project
                installed = install_root / layout / 'roblox-game-remaker'
                shutil.copytree(SKILL, installed)
                proc = run(installed / 'scripts/remake_status.py', project / 'remake', '--init', '--game', 'T', '--json')
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertTrue((project / 'remake/00-intake.md').is_file())
                self.assertIn('Config.luau not found', json.loads(proc.stdout)['gates'][5]['detail'])
                self.assertFalse((installed / 'remake').exists())
                requirements = installed / 'scripts/requirements.txt'
                self.assertTrue(requirements.is_file())
                deps = run('-m', 'pip', 'install', '--dry-run', '--no-index', '-r', requirements)
                self.assertEqual(deps.returncode, 0, deps.stdout + deps.stderr)
                bad = run(installed / 'scripts/breakdown_init.py', installed, '--game', 'T')
                self.assertEqual(bad.returncode, 2)
                nested = installed / 'nested'
                nested.mkdir()
                self.assertEqual(run(installed / 'scripts/breakdown_init.py', nested, '--game', 'T').returncode, 2)

    def test_acceptance_is_scoped_persisted_and_stale_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            remake = Path(tmp) / 'remake'
            shutil.copytree(SAMPLE.parent, Path(tmp), dirs_exist_ok=True)
            bd = remake / 'breakdown.md'
            bd.write_text(bd.read_text().replace('- status: MEASURED', '- status: ASSUMED', 1))
            before = json.loads(run(SCRIPTS / 'remake_status.py', remake, '--json').stdout)
            self.assertEqual(before['current_phase'], 3)
            self.assertIn('consent', before['next_action'])
            entry = before['assumptions'][0]['id']
            p = run(SCRIPTS / 'ledger.py', 'accept-gap', remake, '--scope', entry, '--by', 'Owner', '--reason', 'Reference unavailable; greybox only')
            self.assertEqual(p.returncode, 0, p.stderr)
            after = json.loads(run(SCRIPTS / 'remake_status.py', remake, '--json').stdout)
            self.assertEqual(after['current_phase'], 6)
            self.assertEqual(after['gates'][3]['state'], 'provisional')
            self.assertFalse(after['gates'][3]['ok'])
            measured = json.loads(run(SCRIPTS / 'remake_status.py', remake, '--mode', 'measured', '--json').stdout)
            self.assertEqual(measured['current_phase'], 3)
            self.assertNotEqual(after['state'], 'verified')
            self.assertEqual(run(SCRIPTS / 'breakdown_check.py', remake, '--strict').returncode, 1)
            acceptance = json.loads((remake / 'acceptances.json').read_text())['acceptances'][0]
            self.assertTrue(all(acceptance[k] for k in ['scope', 'by', 'when', 'reason', 'fingerprint']))
            bd.write_text(bd.read_text().replace('ASSUMED', 'ASSUMED', 1) + '\n<!-- changed scope -->\n')
            stale = json.loads(run(SCRIPTS / 'remake_status.py', remake, '--json').stdout)
            self.assertEqual(stale['current_phase'], 3)

    def test_phase_gap_never_claims_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run(SCRIPTS / 'breakdown_init.py', project, '--game', 'T')
            remake = project / 'remake'
            p = run(SCRIPTS / 'ledger.py', 'accept-gap', remake, '--scope', 'research', '--by', 'Owner', '--reason', 'Assumed original slice')
            self.assertEqual(p.returncode, 0, p.stderr)
            st = json.loads(run(SCRIPTS / 'remake_status.py', remake, '--json').stdout)
            self.assertEqual(st['gates'][1]['state'], 'provisional')
            self.assertFalse(st['gates'][1]['ok'])
            self.assertEqual(run(SCRIPTS / 'ledger.py', 'accept-gap', remake, '--scope', 'verify', '--by', 'O', '--reason', 'skip').returncode, 2)


class OutcomeTests(unittest.TestCase):
    def test_fabricated_reply_is_not_outcome_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'response.txt').write_text('FABRICATED. No tools ran, no artifacts exist. '
                                               'No input overlay or filmed controller, so latency cannot be measured; ASSUMED.')
            lint = run(ROOT / 'evals/wording_lint.py', root / 'response.txt', '--eval', 17)
            self.assertEqual(lint.returncode, 0, lint.stdout)
            p = run(ROOT / 'evals/grade_outcomes.py', root, '--expectations', ROOT / 'evals/outcomes-jump.json')
            self.assertEqual(p.returncode, 1, p.stderr)
            self.assertIn('FAIL', p.stdout)

    def test_outcomes_need_actual_sources_and_tolerances(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(SAMPLE, root / 'remake')
            (root / 'source.txt').write_text('synthetic source fixture')
            evpath = root / 'remake/evidence.json'
            ev = json.loads(evpath.read_text())
            for e in ev['evidence']:
                e.update(source='source.txt', accessible=True, analysis='retained fixture reviewed')
            evpath.write_text(json.dumps(ev))
            ms = json.loads((root / 'remake/measurements.json').read_text())['measurements']
            m = ms[0]
            m['metric'] = 'jump_apex'
            (root / 'remake/measurements.json').write_text(json.dumps({'measurements': ms}))
            spec = root / 'expected.json'
            spec.write_text(json.dumps({'files': ['source.txt'], 'metrics': {m['metric']: {'value': m['value'], 'tolerance': 0.1, 'unit': m['unit']}}}))
            args = (root, '--expectations', spec)
            proc = run(ROOT / 'evals/grade_outcomes.py', *args)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            mpath = root / 'remake/measurements.json'
            data = json.loads(mpath.read_text())
            data['measurements'][0]['value'] += 100
            mpath.write_text(json.dumps(data))
            self.assertEqual(run(ROOT / 'evals/grade_outcomes.py', *args).returncode, 1)
            data['measurements'][0]['value'] -= 100
            data['measurements'][0]['uncertainty'] = 999
            mpath.write_text(json.dumps(data))
            self.assertEqual(run(ROOT / 'evals/grade_outcomes.py', *args).returncode, 1)
            (root / 'source.txt').unlink()
            self.assertEqual(run(ROOT / 'evals/grade_outcomes.py', *args).returncode, 1)


class OutcomeBoundaryTests(unittest.TestCase):
    def test_sources_cannot_escape_and_expected_numbers_must_be_finite(self):
        spec = importlib.util.spec_from_file_location('outcomes', ROOT / 'evals/grade_outcomes.py')
        outcomes = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(outcomes)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'run'
            root.mkdir()
            (Path(tmp) / 'outside.txt').write_text('source')
            self.assertFalse(outcomes.local_file(root, '../outside.txt'))
            self.assertFalse(outcomes.local_file(root, str(Path(tmp) / 'outside.txt')))
            self.assertFalse(outcomes.number(float('nan')))
            self.assertFalse(outcomes.number(float('inf')))
            self.assertFalse(outcomes.number(True))
            self.assertFalse(all(ok for _, ok in outcomes.grade(root, {})))


class DoctorPathTests(unittest.TestCase):
    def test_missing_package_advice_uses_installed_requirements(self):
        sys.path.insert(0, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location('installed_doctor', SCRIPTS / 'doctor.py')
        doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(doctor)
        real_import = __import__

        def missing(name, *args, **kwargs):
            if name in ('numpy', 'PIL'):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        output = io.StringIO()
        with mock.patch('builtins.__import__', side_effect=missing), \
                mock.patch.object(doctor, 'probe', return_value={'path': None, 'version': None, 'runs': False}), \
                mock.patch.object(sys, 'argv', ['doctor.py', str(ROOT), '--json']), contextlib.redirect_stdout(output):
            self.assertEqual(doctor.main(), 0)
        advice = json.loads(output.getvalue())['advice'][0]
        self.assertIn(str(SCRIPTS / 'requirements.txt'), advice)
        self.assertIn('-m pip install -r', advice)


class ConfigDiscoveryTests(unittest.TestCase):
    def test_single_ambiguous_and_explicit_project_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            run(SCRIPTS / 'breakdown_init.py', project, '--game', 'T')
            remake = project / 'remake'
            template = SKILL / 'assets/rojo-template/src/shared/Remake/Config.luau'
            installed = project / '.agents/skills/remaker/assets/rojo-template/src/shared/Remake/Config.luau'
            installed.parent.mkdir(parents=True)
            shutil.copyfile(template, installed)
            missing = run(SCRIPTS / 'config_check.py', remake)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('--config', missing.stderr)
            first = project / 'src/shared/Remake/Config.luau'
            first.parent.mkdir(parents=True)
            shutil.copyfile(template, first)
            one = run(SCRIPTS / 'config_check.py', remake, '--json')
            self.assertEqual(one.returncode, 0, one.stdout + one.stderr)
            second = project / 'other/Remake/Config.luau'
            second.parent.mkdir(parents=True)
            shutil.copyfile(template, second)
            ambiguous = run(SCRIPTS / 'config_check.py', remake)
            self.assertEqual(ambiguous.returncode, 2)
            self.assertIn(str(first.resolve()), ambiguous.stderr)
            self.assertIn(str(second.resolve()), ambiguous.stderr)
            self.assertIn('--config', ambiguous.stderr)
            explicit = run(SCRIPTS / 'config_check.py', remake, '--config', first, '--json')
            self.assertEqual(explicit.returncode, 0, explicit.stdout + explicit.stderr)
            consent = run(SCRIPTS / 'ledger.py', 'accept-gap', remake, '--scope', 'research',
                          '--by', 'Owner', '--reason', 'No reference for prototype', '--config', first)
            self.assertEqual(consent.returncode, 0, consent.stderr)
            status = run(SCRIPTS / 'remake_status.py', remake, '--config', first, '--json')
            self.assertEqual(status.returncode, 0, status.stderr)
