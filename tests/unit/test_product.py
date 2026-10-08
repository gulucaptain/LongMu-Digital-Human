import copy
from dataclasses import replace
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from longmu.config import RuntimeConfig, load_config, snapshot, from_snapshot, ROOT
from longmu.context import RunContext, use_context, settings as S
from longmu.project import load_plan
from longmu.cache import atomic_json, sha
from longmu.stages import video as V
from longmu.media.subtitles import captions
from longmu.workflow import run_lock, execute
from longmu.cli import main

SAMPLE=ROOT/'scripts/dry-eye/project.json'

class ConfigTests(unittest.TestCase):
    def test_relative_paths_and_project_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve()
            runtime=base/'runtime.toml'
            runtime.write_text('tts_model_path="weights/base"\ntts_seed=12\nwidth=640\n')
            config=load_config(SAMPLE,runtime,base/'run')
            self.assertEqual(config.TTS_MODEL_PATH,base/'weights/base')
            self.assertEqual(config.TTS_SEED,12)
            self.assertEqual(config.WIDTH,576)
            self.assertEqual(config.OUTPUT_PATH,base/'run')
            snap=base/'snapshot.json';atomic_json(snap,snapshot(config))
            self.assertEqual(from_snapshot(snap),config)

    def test_reject_unknown_and_invalid_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'runtime.toml'
            for body in ['unknown=1','h3_steps=true','width=17','tts_tempo=nan','audio_lead_seconds=-1']:
                with self.subTest(body=body):
                    path.write_text(body)
                    with self.assertRaises(ValueError):load_config(runtime=path)

    def test_python_symlink_preserves_virtual_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory).resolve()
            interpreter=base/'venv/bin/python'
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(sys.executable)
            runtime=base/'runtime.toml'
            runtime.write_text('h3_python="venv/bin/python"')
            self.assertEqual(load_config(runtime=runtime).H3_PYTHON,str(interpreter))

    def test_nested_context_does_not_leak(self):
        original=S.OUTPUT_PATH
        with use_context(RunContext(replace(RuntimeConfig(),OUTPUT_PATH=Path('/tmp/one')))):
            self.assertEqual(S.OUTPUT_PATH,Path('/tmp/one'))
            with use_context(RunContext(replace(RuntimeConfig(),OUTPUT_PATH=Path('/tmp/two')))):
                self.assertEqual(S.OUTPUT_PATH,Path('/tmp/two'))
            self.assertEqual(S.OUTPUT_PATH,Path('/tmp/one'))
        self.assertEqual(S.OUTPUT_PATH,original)

class ProjectTests(unittest.TestCase):
    def test_reject_unknown_character_conflicting_and_empty_shots(self):
        plan=json.loads(SAMPLE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'project.json'
            changes=[lambda x:x.update(shots=[]),lambda x:x['shots'][0].update(scene='unknown'),
                     lambda x:x['shots'][1].update(continue_from=1),
                     lambda x:x['shots'][0].update(first_image='../outside.png')]
            for change in changes:
                changed=copy.deepcopy(plan);change(changed)
                path.write_text(json.dumps(changed))
                config=replace(RuntimeConfig(),PLAN_PATH=path)
                with use_context(RunContext(config)),self.assertRaises(ValueError):load_plan()

    def test_plan_cli_does_not_import_gpu_modules(self):
        with patch.dict(sys.modules,{'torch':None,'transformers':None,'qwen_tts':None}),redirect_stdout(io.StringIO()) as out:
            main(['plan','--project',str(SAMPLE)])
        self.assertIn('实际时长',out.getvalue())

    def test_prompt_uses_character_and_aspect(self):
        plan=json.loads(SAMPLE.read_text());shot=dict(plan['shots'][0],scene='teacher')
        plan['characters']['teacher']={'description':'a mathematics teacher','speech_mode':'on_camera'}
        with use_context(RunContext(replace(RuntimeConfig(),WIDTH=1024,HEIGHT=576))):
            prompt=V.make_prompt(shot,124,4,False,plan)
        self.assertIn('a mathematics teacher',prompt)
        self.assertIn('aspect ratio 1024:576',prompt)
        self.assertIn('visible character speaks',prompt)
        self.assertNotIn('female doctor',prompt)

    def test_strict_fields_scene_continuity_and_action_mode(self):
        plan=json.loads(SAMPLE.read_text())
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'project.json'
            changes=[lambda x:x.update(voices={}),
                     lambda x:x['shots'][0].update(tts_instruct='unused'),
                     lambda x:x['characters']['doctor'].update(voice_id='unused'),
                     lambda x:x['shots'][1].update(scene='doctor', first_image=None, continue_from=1),
                     lambda x:x['shots'][0].update(scene='doctor',shot_type='simple_action'),
                     lambda x:x['shots'][0].update(shot_type='unknown')]
            for change in changes:
                changed=copy.deepcopy(plan);change(changed)
                path.write_text(json.dumps(changed))
                config=replace(RuntimeConfig(),PLAN_PATH=path)
                with use_context(RunContext(config)),self.assertRaises(ValueError):load_plan()

    def test_prompt_reference_dialogue_and_demonstration_contract(self):
        plan=json.loads(SAMPLE.read_text());shot=dict(plan['shots'][0],scene='patient',shot_type='simple_action')
        with use_context(RunContext(RuntimeConfig())):
            prompt=V.make_prompt(shot,124,4,True,plan)
        visual, sound = prompt.split('overall_soundscape:')
        self.assertIn('<Picture 1>', visual)
        self.assertIn('<Picture 2>', visual)
        self.assertIn('5.12 seconds', visual)
        self.assertEqual(visual.count('<d>'),1)
        self.assertNotIn('<d>',sound)
        self.assertIn('off-screen voiceover',visual)
        self.assertIn('Move existing props only as required',visual)
        self.assertNotIn('subtle natural head movements and relaxed hands',visual)
        self.assertIn('speaker identity (S1)',sound)


class CacheTests(unittest.TestCase):
    def fixture(self,base):
        plan=json.loads(SAMPLE.read_text());plan['shots']=plan['shots'][:1]
        assets=base/'assets/reference_images';assets.mkdir(parents=True)
        image=assets/'img_000.png';image.write_bytes(b'first frame')
        audio=base/'audio/clip_01_tts.wav';audio.parent.mkdir();audio.write_bytes(b'audio')
        condition=audio.with_name('clip_01_condition.wav');condition.write_bytes(b'condition')
        video=base/'aligned/clip_01.mp4';video.parent.mkdir();video.write_bytes(b'video')
        config=replace(RuntimeConfig(),ASSET_ROOT=base/'assets',OUTPUT_PATH=base)
        return plan,image,audio,condition,video,config

    def test_compose_rejects_changed_seed_and_image(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory)
            plan,image,audio,condition,video,config=self.fixture(base)
            with use_context(RunContext(config)):
                shot=plan['shots'][0]
                prompt=V.make_prompt(shot,124,4,False,plan)
                request=V.request_fingerprint(shot,124,audio,image,None,prompt)
                meta=dict(request=request,aligned_sha=sha(video),condition_sha=sha(condition),frames=124,speech_seconds=4)
                atomic_json(video.with_suffix('.json'),meta)
                with patch.object(V,'load_plan',return_value=plan),patch.object(V,'prepared_audio',return_value=(audio,{'speech_seconds':4},124)),patch.object(V,'validate_video'),patch.object(V,'compose') as compose:
                    V.main(['--compose-only']);self.assertTrue(compose.called)
                    with patch.object(S,'H3_SEED',config.H3_SEED+1),self.assertRaises(RuntimeError):V.main(['--compose-only'])
                    image.write_bytes(b'changed frame')
                    with self.assertRaises(RuntimeError):V.main(['--compose-only'])

    def test_subtitle_edit_keeps_video_request(self):
        with tempfile.TemporaryDirectory() as directory:
            plan,image,audio,condition,video,config=self.fixture(Path(directory))
            with use_context(RunContext(config)):
                shot=plan['shots'][0]
                before=V.request_fingerprint(shot,124,audio,image,None,V.make_prompt(shot,124,4,False,plan))
                shot['keypoint']='新的字幕要点';plan['notice']='新的片尾提示'
                after=V.request_fingerprint(shot,124,audio,image,None,V.make_prompt(shot,124,4,False,plan))
                self.assertEqual(before,after)

class WorkflowTests(unittest.TestCase):
    def test_lock_prevents_same_run_and_releases_after_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'run'
            with self.assertRaises(ValueError):
                with run_lock(output):
                    with self.assertRaises(RuntimeError):
                        with run_lock(output):pass
                    raise ValueError('failed')
            with run_lock(output):pass

    def test_worker_uses_module_entry_and_records_failure(self):
        from argparse import Namespace
        with tempfile.TemporaryDirectory() as directory:
            context=RunContext(replace(RuntimeConfig(),OUTPUT_PATH=Path(directory)/'run',BURN_SUBTITLES=False))
            args=Namespace(stage='tts',force=False,only=None,source=None)
            with use_context(context),patch('longmu.workflow.subprocess.run',side_effect=RuntimeError('worker failed')) as run:
                with self.assertRaises(RuntimeError):execute(context,args)
            command=run.call_args.args[0]
            self.assertEqual(command[1:4],['-m','longmu','_worker'])
            state=json.loads((context.config.OUTPUT_PATH/'state.json').read_text())
            self.assertEqual(state['status'],'failed')
            self.assertEqual(state['active_stage'],'tts')

    def test_subtitle_uses_canvas_and_notice_without_ninth_shot(self):
        plan=json.loads(SAMPLE.read_text());plan['shots']=plan['shots'][:1];plan['notice']='自定义片尾'
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory)
            context=RunContext(replace(RuntimeConfig(),WIDTH=1024,HEIGHT=576))
            ready=[{'shot':plan['shots'][0],'meta':{'frames':124,'speech_seconds':4}}]
            with use_context(context),patch('longmu.media.subtitles.load_plan',return_value=plan):captions(ready,folder)
            text=(folder/'captions.ass').read_text()
            self.assertIn('PlayResX: 1024',text)
            self.assertIn('PlayResY: 576',text)
            self.assertIn('自定义片尾',text)
