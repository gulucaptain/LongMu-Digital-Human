import json
import tempfile
import unittest
import wave
import sys
import types
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch, Mock
from longmu.config import RuntimeConfig
from longmu.context import RunContext, use_context
from longmu.cache import sha, tts_request
from longmu.reference_source import select_reference, validate_pinned_source
from longmu.workflow import prepare_video_audio

class ReferenceTests(unittest.TestCase):
    def config(self, root):
        return replace(RuntimeConfig(), PROJECT_ROOT=root, ASSET_ROOT=root/'assets', OUTPUT_PATH=root/'run')

    def test_absent_reference_bootstraps_and_single_mp3_auto_selects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root)
            self.assertEqual(select_reference(config),(None,None))
            folder=root/'assets/longmu/reference_audios';folder.mkdir(parents=True)
            audio=folder/'voice.MP3';audio.write_bytes(b'audio')
            self.assertEqual(select_reference(config),(audio.resolve(),None))
            audio.with_suffix('.txt').write_text('真实参考台词',encoding='utf8')
            self.assertEqual(select_reference(config),(audio.resolve(),'真实参考台词'))

    def test_explicit_source_priority_and_multiple_mp3_require_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);folder=root/'assets/longmu/reference_audios';folder.mkdir(parents=True)
            for name in ('a.mp3','b.mp3'): (folder/name).write_bytes(b'audio')
            with self.assertRaises(ValueError):select_reference(config)
            self.assertEqual(select_reference(replace(config,REFERENCE_SOURCE_AUDIO=folder/'b.mp3')),((folder/'b.mp3').resolve(),None))

    def test_project_assets_fallback_and_empty_text_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);config=self.config(root);folder=root/'assets/reference_audios';folder.mkdir(parents=True)
            audio=folder/'voice.mp3';audio.write_bytes(b'audio')
            self.assertEqual(select_reference(config),(audio.resolve(),None))
            audio.with_suffix('.txt').write_text('  ')
            with self.assertRaises(ValueError):select_reference(config)

    def test_pinned_reference_detects_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'voice.mp3';audio.write_bytes(b'original')
            config=replace(self.config(root),REFERENCE_SOURCE_AUDIO=audio)
            path=config.OUTPUT_PATH/'voice_reference/reference.json';path.parent.mkdir(parents=True)
            path.write_text(json.dumps(dict(text=None,x_vector_only_mode=True,origin=dict(mode='import_reference',source=str(audio),source_sha256=sha(audio)))))
            validate_pinned_source(config)
            audio.write_bytes(b'changed')
            with self.assertRaises(RuntimeError):validate_pinned_source(config)

    def test_external_reference_never_reuses_bootstrap_clip(self):
        from longmu.stages.speech import reuse_bootstrap_clip
        shot=dict(id=1,text='相同台词')
        for mode in ('import_reference','import_first_clip'):
            self.assertFalse(reuse_bootstrap_clip(shot,dict(text=shot['text'],origin=dict(mode=mode))))
        self.assertTrue(reuse_bootstrap_clip(shot,dict(text=shot['text'],origin=dict(mode='bootstrap_first_clip'))))

    def test_video_fills_missing_audio_once_and_validates_after_tts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);plan=dict(shots=[dict(id=1),dict(id=2)])
            def launch(stage,python,force):
                self.assertEqual((stage,force),('tts',False))
                folder=root/'audio';folder.mkdir()
                for i in (1,2):
                    (folder/f'clip_{i:02d}_tts.wav').write_bytes(b'audio')
                    (folder/f'clip_{i:02d}_tts.json').write_text('{}')
            with use_context(RunContext(self.config(root))),patch('longmu.project.load_plan',return_value=plan),patch('longmu.cache.prepared_audio') as check:
                config=self.config(root);config.OUTPUT_PATH=root
                with use_context(RunContext(config)):
                    prepare_video_audio(launch)
                    self.assertEqual(check.call_count,2)
                    check.reset_mock()
                    prepare_video_audio(Mock(side_effect=AssertionError('already prepared')))
                    self.assertEqual(check.call_count,4)
                    check.side_effect=RuntimeError('stale cache')
                    with self.assertRaisesRegex(RuntimeError,'stale cache'):prepare_video_audio(Mock(side_effect=AssertionError('must not launch')))

    def test_real_speech_control_flow_clones_all_external_shots(self):
        import numpy as np
        from longmu.stages import speech
        def write(path,data,rate,**kwargs):
            with wave.open(str(path),'wb') as handle:
                handle.setnchannels(1);handle.setsampwidth(2);handle.setframerate(rate)
                handle.writeframes((np.asarray(data)*32767).astype('<i2').tobytes())
        def read(path,**kwargs):
            with wave.open(str(path),'rb') as handle:
                return np.frombuffer(handle.readframes(handle.getnframes()),dtype='<i2').astype(np.float32)/32767,handle.getframerate()
        def info(path):
            with wave.open(str(path),'rb') as handle:return types.SimpleNamespace(frames=handle.getnframes(),samplerate=handle.getframerate())
        sf=types.ModuleType('soundfile');sf.write=write;sf.read=read;sf.info=info
        torch=types.ModuleType('torch');torch.cuda=types.SimpleNamespace(is_available=lambda:True,empty_cache=lambda:None)
        transformers=types.ModuleType('transformers');transformers.set_seed=lambda seed:None
        qwen=types.ModuleType('qwen_tts');qwen.Qwen3TTSModel=object()
        modules={'soundfile':sf,'torch':torch,'transformers':transformers,'qwen_tts':qwen}
        for text in (None,'第一段台词'):
            with self.subTest(reference_text=text),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);source=root/'voice.mp3';write(source,np.full(128000,0.1),32000)
                config=replace(self.config(root),REFERENCE_SOURCE_AUDIO=source,REFERENCE_SOURCE_TEXT=text)
                plan=dict(shots=[dict(id=1,text='第一段台词'),dict(id=2,text='第二段台词')])
                model=Mock();model.generate_voice_clone.return_value=([np.full(128000,0.1)],32000)
                with use_context(RunContext(config)),patch.dict(sys.modules,modules),patch.object(speech,'load_plan',return_value=plan),patch('longmu.backends.qwen_tts.load_model',return_value=model) as load:
                    speech.main([])
                    self.assertEqual(model.generate_voice_clone.call_count,2)
                    self.assertEqual([call.kwargs['text'] for call in model.generate_voice_clone.call_args_list],['第一段台词','第二段台词'])
                    self.assertEqual(model.create_voice_clone_prompt.call_args.kwargs['x_vector_only_mode'],text is None)
                    self.assertEqual(model.create_voice_clone_prompt.call_args.kwargs['ref_text'],text)
                    self.assertEqual(load.call_args.args[-1],'base')
                    self.assertEqual(load.call_count,1)
                    speech.main([])
                    self.assertEqual(model.generate_voice_clone.call_count,2)
                    self.assertTrue((root/'run/audio/clip_01_tts.wav').is_file())

if __name__=='__main__':unittest.main()
