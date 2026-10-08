"""CPU模拟测试：不下载模型、不运行TTS或H3。"""
import sys
import tempfile
import types
import unittest
import wave
import math
from array import array
from pathlib import Path
from unittest.mock import patch

from longmu.context import settings as S
from longmu import cache as C
from longmu import project as P
from longmu.media import ffmpeg as F
from longmu.media import audio as A
from longmu.stages import compose as M
from longmu.stages import video as V



class WorkflowTests(unittest.TestCase):
    def test_current_checkout_source_contract(self):
        from longmu.doctor import check_source
        self.assertIn('retake_audio', check_source())

    def test_audio_import_validates_before_installing(self):
        from longmu.stages.import_audio import import_audio
        from longmu.stages import voice_reference as R
        plan = P.load_plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'old_output'
            with patch.object(S, 'OUTPUT_PATH', source):
                wav, meta = R.reference_paths()
                wav.parent.mkdir(parents=True)
                wav.write_bytes(b'unchanged reference')
                C.atomic_json(meta, dict(text=plan['shots'][0]['text'], sha256=C.sha(wav)))
                for shot in plan['shots']:
                    item = source / 'audio' / f'clip_{shot["id"]:02d}_tts.wav'
                    item.parent.mkdir(exist_ok=True)
                    item.write_bytes(b'cached audio')
                    C.atomic_json(item.with_suffix('.json'), dict(request=C.tts_request(shot),
                                      speech_seconds=4.1, sha256=C.sha(item)))
            with patch.object(S, 'OUTPUT_PATH', root / 'new_output'):
                import_audio(source)
                self.assertEqual(C.sha(S.OUTPUT_PATH/'voice_reference/reference.wav'), C.sha(wav))
                for shot in plan['shots']:
                    C.prepared_audio(shot)
                with self.assertRaises(FileExistsError):
                    import_audio(source)
            (source/'audio/clip_02_tts.wav').write_bytes(b'tampered audio')
            with patch.object(S, 'OUTPUT_PATH', root/'bad_import'):
                with self.assertRaises(RuntimeError):
                    import_audio(source)
                self.assertFalse(S.OUTPUT_PATH.exists())

    def test_reference_is_pinned_and_tampering_rejected(self):
        from longmu.stages import voice_reference as R
        with tempfile.TemporaryDirectory() as tmp, patch.object(S, 'OUTPUT_PATH', Path(tmp)):
            wav, meta = R.reference_paths()
            wav.parent.mkdir(parents=True)
            wav.write_bytes(b'fixed first segment')
            C.atomic_json(meta, dict(text='reference transcript', sha256=C.sha(wav)))
            first = R.reference_identity()
            with patch.object(S, 'TTS_SPEAKER', 'Vivian'):
                self.assertEqual(first, R.reference_identity())
            self.assertEqual(C.tts_request(dict(id=2, text='next clip'))['reference'], first)
            wav.write_bytes(b'different voice')
            with self.assertRaises(RuntimeError):
                R.reference_identity()

    def test_alignment_keeps_tail_and_refuses_truncation(self):
        for length in (3.8, 4.2, 5.3, 6.8, 8.9):
            frames = A.aligned_frames(length)
            self.assertEqual((frames-5) % 17, 0)
            self.assertGreaterEqual(frames/S.FPS, length + S.AUDIO_LEAD_SECONDS + S.AUDIO_TAIL_SECONDS)
            self.assertLessEqual(frames/S.FPS, 10)
        with self.assertRaises(ValueError):
            A.aligned_frames(10)

    def test_missing_audio_preserve_interface_is_rejected(self):
        class OldPipeline:
            def __call__(self, prompt=None, keyframes=None):
                pass
        module = types.ModuleType('diffsynth.pipelines.minimax_h3_audio_video')
        module.MiniMaxH3Pipeline = OldPipeline
        with patch.dict(sys.modules, {'diffsynth.pipelines.minimax_h3_audio_video': module}), patch.object(V.inspect, 'getfile', return_value=str(S.H3_SOURCE_PATH)):
            with self.assertRaises(RuntimeError):
                V.check_interface()

    def test_variable_duration_audio_and_continuation(self):
        plan = P.load_plan()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with patch.object(S, 'OUTPUT_PATH', out), patch.object(S, 'WIDTH', 32), patch.object(S, 'HEIGHT', 64), patch.object(S, 'BURN_SUBTITLES', False):
                from longmu.stages.voice_reference import reference_paths
                ref, meta = reference_paths()
                ref.parent.mkdir(parents=True)
                ref.write_bytes(b'CPU-test-reference')
                C.atomic_json(meta, dict(text=plan['shots'][0]['text'], sha256=C.sha(ref)))
                ready = []
                for shot, duration in zip(plan['shots'][:3], (4.1, 5.3, 7.6)):
                    ident = shot['id']
                    audio = out/'audio'/f'clip_{ident:02d}_tts.wav'
                    audio.parent.mkdir(parents=True, exist_ok=True)
                    with wave.open(str(audio), 'wb') as f:
                        f.setnchannels(1);f.setsampwidth(2);f.setframerate(32000)
                        samples=array('h',(int(5000*math.sin(2*math.pi*440*i/32000)) for i in range(round(duration*32000))))
                        f.writeframes(samples.tobytes())
                    C.atomic_json(audio.with_suffix('.json'), dict(request=C.tts_request(shot), speech_seconds=duration, sha256=C.sha(audio)))
                    _, _, frames = C.prepared_audio(shot)
                    condition = audio.with_name(f'clip_{ident:02d}_condition.wav')
                    count = (frames*32000+S.FPS-1)//S.FPS
                    with wave.open(str(condition), 'wb') as f:
                        f.setnchannels(2);f.setsampwidth(2);f.setframerate(32000)
                        lead=round(S.AUDIO_LEAD_SECONDS*32000)
                        stereo=array('h',[0])*(count*2)
                        for j,value in enumerate(samples):
                            stereo[2*(lead+j)]=value;stereo[2*(lead+j)+1]=value
                        f.writeframes(stereo.tobytes())
                    video = out/'aligned'/f'clip_{ident:02d}.mp4';video.parent.mkdir(exist_ok=True)
                    F.run(['ffmpeg','-v','error','-y','-f','lavfi','-i',f'color=c=blue:s=32x64:r=24:d={frames/24}',
                           '-i',condition,'-af','volume=0','-frames:v',frames,'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-t',f'{frames/24:.9f}',video])
                    meta=dict(frames=frames,speech_seconds=duration,audio_sha=C.sha(audio),condition_sha=C.sha(condition),aligned_sha=C.sha(video),base_settings=V.base_settings())
                    start_path, end_path = V.source_images(shot, plan)
                    prompt = V.make_prompt(shot, frames, duration, end_path is not None, plan)
                    meta['request'] = V.request_fingerprint(shot, frames, audio, start_path, end_path, prompt)
                    C.atomic_json(video.with_suffix('.json'),meta)
                    ready.append(dict(shot=shot,meta=meta))
                    M.compose(ready)
                    final=out/'stitched/latest.mp4'
                    F.validate_video(final,sum(x['meta']['frames'] for x in ready))
                start, end=V.source_images(plan['shots'][2],plan)
                self.assertTrue(start.is_file())
                self.assertEqual(end,S.ASSET_ROOT/'reference_images/img_002.png')
                expected=out/'expected.png'
                F.run(['ffmpeg','-v','error','-y','-i',out/'aligned/clip_02.mp4','-vf',f"select=eq(n\\,{ready[1]['meta']['frames']-1})",'-frames:v','1',expected])
                self.assertEqual(C.sha(start),C.sha(expected))
                M.compose(ready,final=True)
                F.validate_video(out/'final/dry-eye.mp4',sum(x['meta']['frames'] for x in ready))
                srt=(out/'final/captions.srt').read_text()
                self.assertIn('00:00:00,080',srt)
                extracted=out/'verify_audio.wav'
                F.run(['ffmpeg','-v','error','-y','-i',out/'final/dry-eye.mp4','-ss','1','-t','0.2','-vn','-ac','1','-c:a','pcm_s16le',extracted])
                with wave.open(str(extracted),'rb') as f:
                    audible=array('h');audible.frombytes(f.readframes(f.getnframes()))
                self.assertGreater(sum(x*x for x in audible)/len(audible),1000000) # 源视频静音，拼接后应使用给定TTS条件音轨。
                oldmeta=C.read_json(out/'aligned/clip_02.json');oldmeta['request']['base_settings']['steps']+=1
                C.atomic_json(out/'aligned/clip_02.json',oldmeta)
                with self.assertRaises(RuntimeError):
                    V.source_images(plan['shots'][2],plan)
                changed=dict(plan['shots'][0],text='changed')
                with self.assertRaises(RuntimeError):
                    C.prepared_audio(changed)


if __name__=='__main__':
    unittest.main()
