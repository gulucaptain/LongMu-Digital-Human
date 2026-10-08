import json
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from longmu.config import RuntimeConfig
from longmu.context import RunContext,use_context
from longmu.project import load_plan
from longmu.stages.video import make_prompt
from longmu.cache import tts_request

class SpeakingActionTests(unittest.TestCase):
    def fixture(self, root, mode='on_camera'):
        (root/'start.png').write_bytes(b'image')
        plan={'schema_version':1,'project_id':'speaking-action-test','characters':{'doctor':{'description':'a doctor holding the existing bottle','speech_mode':mode}},'shots':[dict(id=1,text='用合适的产品护理镜片。',scene='doctor',shot_type='speaking_action',first_image='start.png',last_image=None,continue_from=None,action='Lower the existing capped bottle onto the tray.',keypoint='护理镜片')]}
        path=root/'project.json';path.write_text(json.dumps(plan))
        return replace(RuntimeConfig(),PLAN_PATH=path,ASSET_ROOT=root),plan

    def test_accepts_on_camera_action_and_rejects_voiceover_action(self):
        for mode in ['on_camera','voiceover']:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as tmp:
                config,plan=self.fixture(Path(tmp),mode)
                with use_context(RunContext(config)):
                    if mode=='on_camera':self.assertEqual(load_plan()['shots'][0]['shot_type'],'speaking_action')
                    else:
                        with self.assertRaisesRegex(ValueError,'speaking_action使用on_camera'):load_plan()

    def test_prompt_combines_speech_and_prop_action_without_silent_template(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,plan=self.fixture(Path(tmp))
            with use_context(RunContext(config)):
                for has_end in [False,True]:
                    with self.subTest(has_end=has_end):
                        prompt=make_prompt(plan['shots'][0],175,6.5,has_end,plan)
                        self.assertIn('doctor herself delivers',prompt)
                        self.assertIn('articulating lips and jaw',prompt)
                        self.assertIn('Lower the existing capped bottle',prompt)
                        self.assertIn('same doctor continues her explanation',prompt)
                        self.assertNotIn('lips closed',prompt)
                        self.assertNotIn('off-screen voiceover',prompt)
                        self.assertNotIn('minimal ongoing body motion',prompt)
                        self.assertNotIn('subtle natural head movements and relaxed hands',prompt)
                        self.assertEqual(prompt.count('<d>'),1)
                        self.assertEqual('<Picture 2>' in prompt,has_end)

    def test_switching_presentation_reuses_tts_request_but_changes_video_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            config,new=self.fixture(Path(tmp));old=json.loads(json.dumps(new));old['characters']['doctor']['speech_mode']='voiceover';old['shots'][0]['shot_type']='simple_action'
            with use_context(RunContext(config)),patch('longmu.stages.voice_reference.reference_identity',return_value=dict(sha256='samevoice',text=None)):
                self.assertEqual(tts_request(new['shots'][0]),tts_request(old['shots'][0]))
                self.assertNotEqual(make_prompt(new['shots'][0],175,6.5,False,new),make_prompt(old['shots'][0],175,6.5,False,old))

if __name__=='__main__':unittest.main()
