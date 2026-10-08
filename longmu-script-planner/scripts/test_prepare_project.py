"""验证skill与真实产品契约，不加载模型。LONGMU_REPO可指定仓库。"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
import wave
import sys
import io
from unittest.mock import patch
from contextlib import redirect_stdout
from prepare_project import find_repo, prepare, main

REPO = find_repo(os.environ.get('LONGMU_REPO'))
EXAMPLE = REPO/'scripts/dry-eye'


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root/'project.json'
        self.plan = json.loads((EXAMPLE/'project.json').read_text())
        source_assets = (EXAMPLE/self.plan.get('asset_root', 'assets')).resolve()
        shutil.copytree(source_assets, self.root/'assets')
        self.plan['asset_root'] = 'assets'
        self.save()

    def tearDown(self):
        self.tmp.cleanup()

    def save(self):
        self.project.write_text(json.dumps(self.plan, ensure_ascii=False), encoding='utf-8')

    def test_real_project_and_missing_image(self):
        result = prepare(REPO, self.project)
        self.assertEqual(len(result['shots']), 9)
        self.assertEqual(result['status'], 'project_validated_timing_estimated')
        self.assertEqual(result['shots'][2]['continue_from'], 2)
        (self.root/'assets/reference_images/img_002.png').unlink()
        with self.assertRaises(FileNotFoundError):
            prepare(REPO, self.project)

    def test_unsupported_multi_voice_and_silent_shot(self):
        self.plan['characters']['doctor']['voice_id'] = 'doctor-voice'
        self.save()
        with self.assertRaises(ValueError):
            prepare(REPO, self.project)
        del self.plan['characters']['doctor']['voice_id']
        self.plan['shots'][0]['text'] = ''
        self.save()
        with self.assertRaises(ValueError):
            prepare(REPO, self.project)

    def test_over_budget_is_not_a_validated_timing_plan(self):
        self.plan['shots'][0]['text'] = '这是过长的完整讲解。' * 50
        self.save()
        report = prepare(REPO, self.project)
        self.assertEqual(report['status'], 'needs_resegmentation')
        self.assertIsNone(report['shots'][0]['prompt'])
        self.assertTrue(report['visual_review_required'])
        preview = self.root/'review'
        with patch.object(sys, 'argv', ['prepare_project', '--repo', str(REPO), '--project', str(self.project), '--preview-dir', str(preview)]), redirect_stdout(io.StringIO()):
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads((preview/'review.json').read_text())['status'], 'needs_resegmentation')

    def test_real_audio_budget_and_stale_cache(self):
        # 真实WAV+产品metadata：依赖缓存校验，时长来自已生成记录。
        prepare(REPO, self.project)
        from longmu.config import load_config
        from longmu.context import RunContext, use_context
        from longmu.cache import atomic_json, sha, tts_request
        from longmu.stages.voice_reference import reference_paths
        config = load_config(self.project, output=self.root/'runs/test')
        with use_context(RunContext(config)):
            ref, ref_meta = reference_paths()
            ref.parent.mkdir(parents=True)
            with wave.open(str(ref), 'wb') as stream:
                stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(32000)
                stream.writeframes(b'\x01\x00'*128000)
            atomic_json(ref_meta, dict(text=self.plan['shots'][0]['text'], sha256=sha(ref)))
            for shot in self.plan['shots']:
                path = config.OUTPUT_PATH/'audio'/f'clip_{shot["id"]:02d}_tts.wav'
                path.parent.mkdir(exist_ok=True)
                with wave.open(str(path), 'wb') as stream:
                    stream.setnchannels(1); stream.setsampwidth(2); stream.setframerate(32000)
                    stream.writeframes(b'\x01\x00'*128000)
                atomic_json(path.with_suffix('.json'), dict(request=tts_request(shot),
                                  speech_seconds=4.0, sha256=sha(path)))
        result = prepare(REPO, self.project, output=config.OUTPUT_PATH, use_audio=True)
        self.assertTrue(all(row['frames']==124 for row in result['shots']))
        self.assertEqual(result['status'], 'audio_cache_validated')
        self.plan['shots'][1]['text'] += '新增文字。'
        self.save()
        with self.assertRaises(RuntimeError):
            prepare(REPO, self.project, output=config.OUTPUT_PATH, use_audio=True)


if __name__ == '__main__':
    unittest.main()
