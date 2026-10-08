"""多卡调度的CPU验证：真实子进程模拟H3，验证并行、依赖、失败与顺序。"""
from argparse import Namespace
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from longmu.cache import atomic_json
from longmu.config import RuntimeConfig
from longmu.context import RunContext, use_context
from longmu.parallel_video import assignments, parse_gpus, run_parallel
from longmu.stages import compose as C
from longmu.workflow import worker, execute

PLAN = {'project_id':'parallel-test','shots':[
    {'id':i,'continue_from':{2:1,4:3}.get(i),'text':str(i)} for i in range(1,7)]}
STUB = '''import argparse,json,os,pathlib,sys,time
p=argparse.ArgumentParser()
p.add_argument('--snapshot');p.add_argument('--stage');p.add_argument('--only')
p.add_argument('--no-compose',action='store_true');p.add_argument('--progress-file');p.add_argument('--force',action='store_true')
a=p.parse_args(); assert a.no_compose
settings=json.loads(pathlib.Path(a.snapshot).read_text());root=pathlib.Path(settings['output'])
progress=pathlib.Path(a.progress_file); gpu=os.environ['CUDA_VISIBLE_DEVICES']; ids=list(map(int,a.only.split(',')))
started=time.time();completed=[]
(root/'aligned').mkdir(exist_ok=True)
for ident in ids:
    previous=settings['shots'][ident-1]['continue_from']
    if previous is not None: assert (root/'aligned'/f'clip_{previous:02d}.json').exists()
    time.sleep(5 if os.environ.get('STUB_FAILURE') and gpu=='0' else (0.12 if gpu=='0' else 0.03))
    (root/'aligned'/f'clip_{ident:02d}.json').write_text(json.dumps({'frames':124,'speech_seconds':4}))
    completed.append(ident)
    pending=progress.with_suffix('.pending');pending.write_text(json.dumps({'completed':completed,'status':'running'}));pending.replace(progress)
    if os.environ.get('STUB_FAILURE') and gpu=='1': sys.exit(2)
pending=progress.with_suffix('.pending');pending.write_text(json.dumps({'completed':completed,'status':'complete'}));pending.replace(progress)
progress.with_suffix('.audit').write_text(json.dumps({'gpu':gpu,'ids':ids,'start':started,'end':time.time(),'no_compose':a.no_compose,'force':a.force}))
'''

class SchedulerTests(unittest.TestCase):
    def test_components_keep_branches_together_and_balance(self):
        plan={'shots':[dict(id=i,continue_from={2:1,3:1,5:4}.get(i)) for i in range(1,7)]}
        jobs=assignments(plan,['0','1','2'],{i:124 for i in range(1,7)})
        owner={i:job['gpu'] for job in jobs for i in job['shots']}
        self.assertEqual(owner[1],owner[2]);self.assertEqual(owner[1],owner[3])
        self.assertEqual(owner[4],owner[5]);self.assertEqual(set(owner),set(range(1,7)))
        self.assertEqual(len(jobs),3)

    def test_selected_dependencies_do_not_generate_omitted_shots(self):
        jobs=assignments(PLAN,['0','1'],{i:124 for i in range(1,7)},selected={2,4,6})
        self.assertEqual(sorted(i for j in jobs for i in j['shots']),[2,4,6])

    def test_gpu_selection_respects_visibility_and_rejects_duplicates(self):
        with patch.dict(os.environ,{'CUDA_VISIBLE_DEVICES':'2,5'}):
            self.assertEqual(parse_gpus('2,5'),['2','5'])
            for value in ('0,1','2,2','02,2','2,',''):
                with self.assertRaises(ValueError):parse_gpus(value)

    def test_worker_forwards_isolated_generation_options(self):
        args=Namespace(stage='video',only='1,2',force=True,no_compose=True,progress_file='/tmp/gpu.json')
        with patch('longmu.stages.video.main') as main:
            worker(args)
        self.assertEqual(main.call_args.args[0],['--only','1,2','--no-compose','--progress-file','/tmp/gpu.json','--force'])

    def run_stub(self, root, fail=False, only=None, save_progress=False):
        script=root/'stub.py';script.write_text(STUB)
        snap=root/'snapshot.json';atomic_json(snap,dict(output=str(root),shots=PLAN['shots']))
        config=replace(RuntimeConfig(),OUTPUT_PATH=root,H3_PYTHON=sys.executable,SAVE_PROGRESS_AFTER_EACH_CLIP=save_progress)
        real_popen=subprocess.Popen
        processes=[]
        def launch(command,**kwargs):
            process=real_popen([sys.executable,str(script),*command[4:]],**kwargs)
            processes.append(process)
            return process
        with use_context(RunContext(config)),patch('longmu.parallel_video.load_plan',return_value=PLAN),patch('longmu.parallel_video.prepared_audio',return_value=(root/'audio.wav',{},124)),patch('longmu.stages.video.validate_cached'),patch('longmu.stages.compose.compose') as compose,patch('longmu.parallel_video.subprocess.Popen',side_effect=launch),patch.dict(os.environ,{'STUB_FAILURE':'yes'} if fail else {},clear=False):
            if fail:
                started=time.monotonic()
                with self.assertRaises(RuntimeError):run_parallel(snap,['0','1'],only,True)
                self.assertLess(time.monotonic()-started,3)
                self.assertFalse(compose.called)
            else:
                run_parallel(snap,['0','1'],only,True)
                ids=[s['shot']['id'] for s in compose.call_args.args[0]]
                self.assertEqual(ids,sorted(map(int,only.split(','))) if only else list(range(1,7)))
                self.assertEqual(compose.call_args.kwargs,{} if only else {'final':True})
                if save_progress:
                    for call in compose.call_args_list[:-1]:
                        prefix=[x['shot']['id'] for x in call.args[0]]
                        self.assertEqual(prefix,list(range(1,len(prefix)+1)))
                    self.assertGreater(len(compose.call_args_list),1)
        self.assertTrue(all(p.poll() is not None for p in processes))
        return json.loads((root/'parallel/manifest.json').read_text())

    def test_real_workers_overlap_keep_dependencies_and_compose_by_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=self.run_stub(root)
            audits=[json.loads(p.read_text()) for p in (root/'parallel').glob('*.audit')]
            self.assertEqual(len(audits),2)
            self.assertLess(max(x['start'] for x in audits),min(x['end'] for x in audits))
            self.assertTrue(all(x['force'] and x['no_compose'] for x in audits))
            owners={i:x['gpu'] for x in audits for i in x['ids']}
            self.assertEqual(owners[1],owners[2]);self.assertEqual(owners[3],owners[4])
            self.assertEqual(manifest['shot_order'],[1,2,3,4,5,6])
            self.assertEqual(manifest['status'],'complete')
            self.assertTrue(all(x['status']=='complete' for x in manifest['shots']))

    def test_failed_worker_cancels_peers_preserves_completed_and_never_composes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);manifest=self.run_stub(root,fail=True)
            self.assertEqual(manifest['status'],'failed')
            self.assertTrue(any(x['status']=='complete' for x in manifest['shots']))
            self.assertTrue(any(x['status']=='cancelled' for x in manifest['shots']))
            self.assertTrue(list((root/'aligned').glob('*.json')))

    def test_subset_only_makes_preview(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest=self.run_stub(Path(tmp),only='5,6')
            self.assertEqual(manifest['shot_order'],[5,6])

    def test_progress_only_contains_contiguous_completed_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_stub(Path(tmp),save_progress=True)

    def test_actual_cached_video_worker_records_completion_without_composing(self):
        from longmu.stages import video as V
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'aligned').mkdir()
            (root/'aligned/clip_01.mp4').write_bytes(b'cached')
            atomic_json(root/'aligned/clip_01.json',{'frames':124})
            modules={name:types.ModuleType(name) for name in ('torch','numpy','soundfile','PIL','diffsynth.utils.data.audio_video')}
            modules['PIL'].Image=object();modules['PIL'].ImageOps=object()
            modules['diffsynth.utils.data.audio_video'].write_video_audio=object()
            config=replace(RuntimeConfig(),OUTPUT_PATH=root,SAVE_PROGRESS_AFTER_EACH_CLIP=True)
            progress=root/'worker.json'
            with use_context(RunContext(config)),patch.dict(sys.modules,modules),patch.object(V,'load_plan',return_value=PLAN),patch.object(V,'prepared_audio',return_value=(root/'audio.wav',{'speech_seconds':4},124)),patch.object(V,'check_interface'),patch.object(V,'source_images',return_value=(root/'first.png',None)),patch.object(V,'make_prompt',return_value='prompt'),patch.object(V,'request_fingerprint',return_value={}),patch.object(V,'validate_cached') as validate,patch.object(V,'compose') as compose,patch('longmu.backends.minimax_h3.load_pipeline') as load:
                V.main(['--only','1','--no-compose','--progress-file',str(progress)])
                compose.assert_not_called();load.assert_not_called();validate.assert_called_once()
            self.assertEqual(json.loads(progress.read_text())['completed'],[1])
            self.assertEqual(json.loads(progress.read_text())['status'],'complete')

    def test_workflow_dispatches_parallel_and_records_gpu_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'model/FL2VA').mkdir(parents=True)
            context=RunContext(replace(RuntimeConfig(),OUTPUT_PATH=root/'run',H3_MODEL_PATH=root/'model',BURN_SUBTITLES=False))
            args=Namespace(stage='video',force=False,only=None,source=None,gpus=['0','1'])
            with patch('longmu.workflow.prepare_video_audio'),patch('longmu.workflow.subprocess.run') as check,patch('longmu.parallel_video.run_parallel') as parallel:
                execute(context,args)
            self.assertEqual(check.call_count,1)
            self.assertIn('check',check.call_args.args[0])
            self.assertEqual(parallel.call_args.args[1:],(['0','1'],None,False))
            state=json.loads((root/'run/state.json').read_text())
            self.assertEqual(state['gpus'],['0','1']);self.assertEqual(state['status'],'complete')

    def test_bad_audio_stops_before_any_worker(self):
        with tempfile.TemporaryDirectory() as tmp,use_context(RunContext(replace(RuntimeConfig(),OUTPUT_PATH=Path(tmp)))),patch('longmu.parallel_video.load_plan',return_value=PLAN),patch('longmu.parallel_video.prepared_audio',side_effect=RuntimeError('stale audio')),patch('longmu.parallel_video.subprocess.Popen') as launch:
            with self.assertRaises(RuntimeError):run_parallel(Path(tmp)/'snapshot.json',['0','1'])
            launch.assert_not_called()

class ComposeOrderTests(unittest.TestCase):
    def test_out_of_order_completion_is_sorted_before_media_and_captions(self):
        ready=[dict(shot=dict(id=i),meta=dict(frames=124)) for i in [3,1,2]]
        with tempfile.TemporaryDirectory() as tmp,use_context(RunContext(replace(RuntimeConfig(),OUTPUT_PATH=Path(tmp),BURN_SUBTITLES=False))),patch.object(C,'captions') as captions,patch.object(C,'validate_video'),patch.object(C,'run',side_effect=lambda command,**kw:Path(command[-1]).write_bytes(b'video')):
            C.compose(ready)
            self.assertEqual([x['shot']['id'] for x in captions.call_args.args[0]],[1,2,3])
            self.assertEqual(json.loads((Path(tmp)/'stitched/progress.json').read_text())['shots'],[1,2,3])

    def test_duplicate_ids_are_rejected(self):
        item=dict(shot=dict(id=1),meta=dict(frames=124))
        with self.assertRaises(ValueError):C.compose([item,item])
