import json
from pathlib import Path
import tempfile
import unittest

from longmu.config import ROOT, load_config, snapshot, from_snapshot
from longmu.context import RunContext, use_context
from longmu.stages.video import make_prompt


class ConcisePromptTests(unittest.TestCase):
    project = ROOT / 'scripts/dry-eye-treatment-ep14-partial-v1/project.interaction.draft.json'

    def test_worker_snapshot_preserves_style_and_times_do_not_change_text(self):
        config = load_config(self.project)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            path.write_text(json.dumps(snapshot(config)))
            restored = from_snapshot(path)
        self.assertEqual(restored.VIDEO_PROMPT_STYLE, 'concise')
        plan = json.loads(self.project.read_text())
        shot = plan['shots'][2]
        with use_context(RunContext(restored)):
            short = make_prompt(shot, 175, 6.667, True, plan)
            long = make_prompt(shot, 226, 9.0, True, plan)
        self.assertEqual(short, long)
        self.assertIn('<Picture 2>', short)
        self.assertIn(shot['text'], short)
        self.assertNotIn('seconds', short)
        self.assertNotIn('post-production', short)

    def test_home_scene_has_only_patient_and_voiceover(self):
        plan = json.loads(self.project.read_text())
        with use_context(RunContext(load_config(self.project))):
            prompt = make_prompt(plan['shots'][7], 175, 6.0, False, plan)
        self.assertNotIn('doctor', prompt.lower())
        self.assertNotIn('<Picture 2>', prompt)
        self.assertIn('off-screen voiceover', prompt)
        self.assertIn('remain silent', prompt)


if __name__ == '__main__':
    unittest.main()
