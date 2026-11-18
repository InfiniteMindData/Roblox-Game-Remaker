"""Capture contracts; Blender option tests are Prepared, not run in Blender."""
import importlib
import json
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/roblox-game-remaker'
sys.path.insert(0, str(SKILL / 'scripts'))
shots = importlib.import_module('studio_snippets')
measure = importlib.import_module('measure_compare')
export = importlib.import_module('blender_roblox_export')


class CaptureRegressions(unittest.TestCase):
    def test_elapsed_latency_not_last_frame_duration(self):
        out = measure.derive([], [], [{'key': 'W', 'f': 3, 'fd': 0.1, 'dt': 0.12}])
        self.assertEqual(out['input_latency'], [0.12])
        self.assertEqual(out['input_latency_frames'], [3.0])

    def test_unknown_elapsed_time_is_not_guessed(self):
        for dt in (None, -1, float('nan'), float('inf')):
            out = measure.derive([], [], [{'key': 'W', 'f': 3, 'fd': 0.1, 'dt': dt}])
            self.assertEqual(out['input_latency'], [])
            self.assertEqual(out['input_latency_frames'], [3.0])

    def test_hud_sample_and_projection(self):
        entry = json.loads((SKILL / 'examples/04-sample-workspace/remake/shots.json').read_text())['shots'][0]
        table = shots.shot_table(entry)
        self.assertIn('guiPolicy = "hide_developer"', table)
        self.assertIn('projection = "Perspective"', table)
        self.assertNotIn('hideGui = true', table)

    def test_orthographic_shot(self):
        entry = {'camera': {'position': [1, 2, 3], 'look_at': [0, 0, 0], 'projection': 'orthographic',
                            'orthographic_size': 40, 'orthographic_axis': 'Horizontal'}, 'gui_policy': 'keep'}
        table = shots.shot_table(entry)
        for text in ('projection = "Orthographic"', 'orthographicSize = 40', 'orthographicAxis = "Horizontal"', 'guiPolicy = "keep"'):
            self.assertIn(text, table)

    def test_invalid_shot_policy_and_projection_rejected(self):
        base = {'camera': {'position': [1, 2, 3], 'look_at': [0, 0, 0]}}
        for extra in ({'gui_policy': 'typo'}, {'camera': {**base['camera'], 'projection': 'typo'}},
                      {'camera': {**base['camera'], 'projection': 'orthographic'}},
                      {'camera': {**base['camera'], 'fov_mode': 'typo'}}):
            with self.assertRaises(shots.rc.ToolError):
                shots.shot_table({**base, **extra})

    def test_single_clip_export_options(self):
        args = export.parse_args(['--out', 'clip.fbx', '--animation', '--action', 'Walk', '--frame-start', '3', '--frame-end', '20'])
        self.assertEqual(args.action, 'Walk')
        self.assertEqual((args.frame_start, args.frame_end), (3, 20))
        options = export.fbx_animation_options(args)
        self.assertTrue(options['bake_anim'])
        self.assertFalse(options['bake_anim_use_all_actions'])
        self.assertFalse(options['bake_anim_use_nla_strips'])

    def test_invalid_clip_arguments(self):
        for extra in (['--action', 'Walk'], ['--animation', '--frame-start', '4'],
                      ['--animation', '--frame-start', '9', '--frame-end', '3']):
            with self.assertRaises(SystemExit):
                export.parse_args(['--out', 'clip.fbx', *extra])

    def test_ci_runs_python_luau_integrations_and_linux_demo(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        job = workflow.split('\n  luau:', 1)[1]
        for command in ('actions/setup-python@v5', 'requirements-dev.txt', 'unittest discover -s tests',
                        'examples/demo/run_demo.sh'):
            self.assertIn(command, job)

    def test_selected_action_and_frame_range_prepared_not_run(self):
        walk = SimpleNamespace(name="Walk", frame_range=(1.5, 30.2))
        run = SimpleNamespace(name="Run", frame_range=(40, 60))
        data = SimpleNamespace(action=run, use_nla=True)
        arm = SimpleNamespace(animation_data=data, animation_data_create=lambda: None)
        scene = SimpleNamespace(frame_start=0, frame_end=100)
        bpy = SimpleNamespace(data=SimpleNamespace(actions={"Walk": walk, "Run": run}),
                              context=SimpleNamespace(scene=scene))
        args = export.parse_args(["--out", "clip.fbx", "--animation", "--action", "Walk"])
        result = export.prepare_animation(bpy, args, [arm])
        self.assertIs(data.action, walk)
        self.assertFalse(data.use_nla)
        self.assertEqual(result, {"action": "Walk", "frame_start": 1, "frame_end": 31})
        self.assertEqual((scene.frame_start, scene.frame_end), (1, 31))
        args.frame_start, args.frame_end = 3, 20
        self.assertEqual(export.prepare_animation(bpy, args, [arm])["frame_end"], 20)
        self.assertEqual(scene.frame_start, 3)
        args.action = None
        self.assertEqual(export.prepare_animation(bpy, args, [arm])["action"], "Walk")
        for arms in ([], [arm, arm]):
            with self.assertRaises(ValueError):
                export.prepare_animation(bpy, args, arms)
        data.action = None
        with self.assertRaises(ValueError):
            export.prepare_animation(bpy, args, [arm])
        args.action = "Missing"
        with self.assertRaises(ValueError):
            export.prepare_animation(bpy, args, [arm])
