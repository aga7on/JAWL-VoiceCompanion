"""Isolated real-browser VRM loading/motion smoke; no models, mic or live profile."""
import argparse
import hashlib
import json
import os
import struct
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
from jawl_voicecompanion.web import create_server
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.support.ui import WebDriverWait


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', default='JawlieReference')
    args = parser.parse_args()
    assert args.model.replace('_', '').replace('-', '').isalnum()
    model = ROOT / 'runtime/vrm-models' / (args.model + '.vrm')
    out = ROOT / 'runtime/character-reference' / args.model
    out.mkdir(parents=True, exist_ok=True)
    blob = model.read_bytes()
    magic, version, length = struct.unpack_from('<4sII', blob)
    assert magic == b'glTF' and version == 2 and length == len(blob)
    size, kind = struct.unpack_from('<II', blob, 12)
    gltf = json.loads(blob[20:20+size])
    vrm = gltf['extensions'].get('VRMC_vrm') or gltf['extensions']['VRM']
    bones = vrm['humanoid']['humanBones']
    if isinstance(bones, list):
        bones = {b['bone']: b for b in bones}
    assert all(k in bones for k in ['hips','spine','head','leftHand','rightHand','leftFoot','rightFoot'])
    expressions = vrm.get('expressions', {}).get('preset', {})
    if not expressions:
        expressions = {
            (e.get('presetName') if e.get('presetName') not in (None, '', 'unknown') else e['name']): e
            for e in vrm.get('blendShapeMaster', {}).get('blendShapeGroups', [])
        }
    bound_expressions = [name for name, e in expressions.items()
                         if e.get('morphTargetBinds') or e.get('binds')]
    if args.model == 'JawlieReference':
        for key in ['blink','aa','happy','sad']:
            assert expressions[key].get('morphTargetBinds'), key
    artifact_sha = hashlib.sha256(blob).hexdigest()
    report = {'schema_version': 1, 'run_id': uuid4().hex,
              'started_utc': datetime.now(timezone.utc).isoformat(),
              'profile': 'vrm_actual_browser_solver_smoke',
              'model': args.model, 'sha256': artifact_sha,
              'bytes': len(blob), 'humanoid_bones': len(bones),
              'expressions': list(expressions), 'mode':'isolated_mock_no_capture', 'status':'failed'}
    report['bound_expressions'] = bound_expressions
    helper_names = {node.get('name') for node in gltf.get('nodes', [])
                    if str(node.get('name', '')).startswith('jawlie_')}
    report['secondary_physics_helpers'] = sorted(helper_names)
    native_hair_names={node.get('name') for node in gltf.get('nodes', [])
                       if str(node.get('name','')).startswith('HairRef_')}
    if native_hair_names:
        secondary=vrm['secondaryAnimation']
        spring=next(g for g in secondary['boneGroups'] if g.get('comment')=='Reference layered hair')
        assert len(native_hair_names)==39 and len(spring['bones'])==13
        assert len(spring['colliderGroups'])==2
        assert all(len(secondary['colliderGroups'][i]['colliders'])==3 for i in spring['colliderGroups'])
        assert not any('Glove' in m.get('name','') for m in gltf['meshes'])
    server = create_server('127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    driver = None
    try:
        options = Options()
        options.add_argument('--headless=new')
        options.add_argument('--window-size=1200,850')
        options.add_argument('--use-gl=angle')
        options.add_argument('--use-angle=swiftshader')
        options.add_argument('--enable-unsafe-swiftshader')
        driver = webdriver.Edge(options=options)
        driver.get(f'http://127.0.0.1:{server.server_port}/app')
        wait = WebDriverWait(driver, 40)
        wait.until(lambda d:d.execute_script('return !!window.__jawlScene && !!window.__jcsrf'))
        driver.set_script_timeout(40)
        result = driver.execute_async_script("""
            const done=arguments[arguments.length-1];
            window.__jawlScene.wear(arguments[0]).then(vrm=>{window.__validatedVrm=vrm;done(vrm ? {
                expressions: vrm.expressionManager.expressions.map(e=>e.expressionName),
                meshes: (()=>{let n=0;vrm.scene.traverse(o=>{if(o.isMesh)n++});return n})(),
                modelRoots: vrm.scene.parent.children.filter(o => o.type === 'Group').length,
                weightedHelpers: (()=>{const found=new Set();vrm.scene.traverse(o=>{
                    if(!o.isSkinnedMesh)return;
                    const indices=o.geometry.getAttribute('skinIndex'),weights=o.geometry.getAttribute('skinWeight');
                    if(!indices || !weights)return;
                    for(let i=0;i<indices.count;i++)for(let j=0;j<4;j++){
                        if(weights.getComponent(i,j)>0){
                            const name=o.skeleton.bones[indices.getComponent(i,j)]?.name;
                            if(name?.startsWith('jawlie_'))found.add(name);
                        }
                    }
                });return [...found].sort();})(),
                rest: window.__jawlRestPose,
            }:null)}).catch(e=>done({error:String(e)}));
        """, args.model)
        assert result and not result.get('error'), result
        assert 'aa' in result['expressions'] and result['meshes'] > 0
        assert result['modelRoots'] == 1, result
        assert set(result['weightedHelpers']) == helper_names, result
        wait.until(lambda d:d.execute_script('return window.__jawlScene.wornModel===arguments[0]', args.model))
        if native_hair_names:
            # Use the actual three-vrm solver and app RAF/rendering loop. An
            # isolated test-only humanoid wrapper supplies controlled head yaw
            # after idle; no live profile, production hook or mock springs.
            native_hair=driver.execute_async_script("""
                const done=arguments[arguments.length-1], vrm=window.__validatedVrm;
                const scene=window.__jawlScene, manager=vrm.springBoneManager;
                const joints=[...manager.joints].filter(j=>j.bone.name.startsWith('HairRef_'));
                const weighted=new Set();
                vrm.scene.traverse(o=>{
                    if(!o.isSkinnedMesh)return;
                    const indices=o.geometry.getAttribute('skinIndex'),weights=o.geometry.getAttribute('skinWeight');
                    if(!indices || !weights)return;
                    for(let i=0;i<indices.count;i++)for(let j=0;j<4;j++)if(weights.getComponent(i,j)>0){
                        const name=o.skeleton.bones[indices.getComponent(i,j)]?.name;
                        if(name?.startsWith('HairRef_'))weighted.add(name);
                    }
                });
                const humanoid=vrm.humanoid, original=humanoid.update;
                const originalSpringUpdate=manager.update;
                let seconds=0, frames=0, yaw=0, peak=0, lateDrift=0, rest=null, late=null;
                const initial=joints.map(j=>j.bone.quaternion.clone());
                const started=performance.now();
                function restore(){humanoid.update=original;manager.update=originalSpringUpdate;}
                scene.setEmotion('neutral');scene.setReducedMotion(false);
                manager.reset();
                humanoid.update=function(){
                    ['hips','spine','chest','upperChest','neck','head'].forEach(name=>{
                        const node=this.getNormalizedBoneNode(name);if(node)node.rotation.set(0,0,0);
                    });
                    this.getNormalizedBoneNode('head').rotation.y=yaw;
                    original.call(this);
                };
                manager.update=function(dt){seconds+=dt;originalSpringUpdate.call(this,dt);};
                function sample(){
                    try{
                        yaw=seconds<2.5?0:seconds<3.5?.32:seconds<4.5?-.32:0;
                        joints.forEach((j,i)=>{
                            if(!j.bone.quaternion.toArray().every(Number.isFinite))throw new Error('Non-finite native hair');
                            peak=Math.max(peak,j.bone.quaternion.angleTo(initial[i]));
                        });
                        if(seconds>=2.4 && !rest)rest=joints.map(j=>j.bone.quaternion.clone());
                        if(seconds>=6 && !late)late=joints.map(j=>j.bone.quaternion.clone());
                        if(late)joints.forEach((j,i)=>lateDrift=Math.max(lateDrift,j.bone.quaternion.angleTo(late[i])));
                        if(seconds<7 && ++frames<1200 && performance.now()-started<30000){requestAnimationFrame(sample);return;}
                        const finalRestDelta=Math.max(...joints.map((j,i)=>j.bone.quaternion.angleTo(rest?.[i]||initial[i])));
                        const report={seconds,frames,joints:joints.length,peak,lateDrift,finalRestDelta,
                            colliderGroups:manager.colliderGroups.length,colliders:manager.colliders.length,
                            attached:joints.every(j=>j.colliderGroups.length===2),
                            weighted:[...weighted].sort(),
                            center:joints[0]?.center?.name,controlled_head_yaw:[0,.32,-.32,0]};
                        restore();done(report);
                    }catch(e){restore();done({error:String(e)});}
                }
                requestAnimationFrame(sample);
            """)
            report['native_hair']=native_hair
            assert not native_hair.get('error'), native_hair
            assert native_hair['seconds']>=7 and native_hair['joints']==39, native_hair
            assert native_hair['attached'] and native_hair['colliders']==6, native_hair
            assert set(native_hair['weighted'])==native_hair_names, native_hair
            assert 1e-5<native_hair['peak']<1.0, native_hair
            assert native_hair['lateDrift']<0.005 and native_hair['finalRestDelta']<0.01, native_hair
            driver.save_screenshot(str(out/'browser-hair-settled.png'))
        # Exercise actual labeled controls, not an isolated physics mock.
        driver.find_element('css selector', '[data-tab="avatar"]').click()
        toggle = driver.find_element('id', 'avatar-physics-enabled')
        if not toggle.is_selected(): toggle.click()
        stats = driver.execute_script('return window.__jawlScene.physicsStats')
        assert stats['supported'] == bool(helper_names), stats
        assert stats['boundNodes'] == len(helper_names), stats
        if stats['supported']:
            physics = driver.execute_async_script("""
                const done=arguments[arguments.length-1], scene=window.__jawlScene;
                const names=scene.physicsStats.boundNodeNames;
                const nodes=names.map(n=>window.__validatedVrm.scene.getObjectByName(n));
                const toggle=document.getElementById('avatar-physics-enabled');
                // Compare to an actual restored baseline, not the preceding
                // frame's nonzero physics offset (a timing-dependent assertion).
                if(toggle.checked)toggle.click();
                const base=nodes.map(n=>({r:n.rotation.toArray().slice(0,3),p:n.position.toArray()}));
                toggle.click();
                let frames=0, rotationPeak=0, positionPeak=0;
                scene.setMotionState('speaking');
                function sample(){
                    scene.setLipLevel((Math.sin(frames*.2)+1)/2);
                    nodes.forEach((n,i)=>['x','y','z'].forEach((a,j)=>{
                        rotationPeak=Math.max(rotationPeak,Math.abs(n.rotation[a]-base[i].r[j]));
                        positionPeak=Math.max(positionPeak,Math.abs(n.position[a]-base[i].p[j]));
                    }));
                    if(++frames<120){requestAnimationFrame(sample);return;}
                    document.getElementById('avatar-physics-enabled').click();
                    const restored=nodes.every((n,i)=>['x','y','z'].every((a,j)=>
                        Math.abs(n.rotation[a]-base[i].r[j])<1e-8 && Math.abs(n.position[a]-base[i].p[j])<1e-8));
                    scene.setLipLevel(0);scene.setMotionState('idle');
                    done({rotationPeak,positionPeak,restored,disabled:!scene.physicsStats.enabled});
                }
                requestAnimationFrame(sample);
            """)
            assert 1e-7 < physics['rotationPeak'] <= 0.02, physics
            assert physics['positionPeak'] <= 0.003, physics
            assert physics['restored'] and physics['disabled'], physics
            toggle.click()
            slider = driver.find_element('id', 'avatar-physics-intensity')
            from selenium.webdriver.common.keys import Keys
            slider.send_keys(Keys.HOME, Keys.ARROW_RIGHT)
            assert driver.execute_script('return window.__jawlScene.physicsStats.intensity') == 0.05
            assert driver.find_element('id','avatar-physics-value').text == '5%'
            slider.send_keys(Keys.END, *([Keys.ARROW_LEFT] * 10))
            report['physics'] = physics
        # VRM0 custom "Surprised" casing must not silently lose face emotion.
        face = driver.execute_async_script("""
            const done=arguments[arguments.length-1], manager=window.__validatedVrm.expressionManager;
            const name=manager.expressions.find(e=>e.expressionName.toLowerCase()==='surprised')?.expressionName;
            window.__jawlScene.setReducedMotion(true);
            window.__jawlScene.setEmotion('surprised');
            requestAnimationFrame(()=>requestAnimationFrame(()=>done({name,value:name?manager.getValue(name):null})));
        """)
        if any(name.lower() == 'surprised' for name in bound_expressions):
            assert face['value'] == 1, face
        report['surprised_face'] = face
        driver.execute_script("window.__jawlScene.setEmotion('neutral');window.__jawlScene.setReducedMotion(false)")
        pose = driver.execute_async_script("""
            const done=arguments[arguments.length-1], vrm=window.__validatedVrm;
            const arm=vrm.humanoid.getNormalizedBoneNode('leftUpperArm');
            const baseline=arm.rotation.z; let peak=0, frames=0;
            window.__jawlScene.setEmotion('happy');
            function sample(){
                peak=Math.max(peak,Math.abs(arm.rotation.z-baseline));
                if(++frames<90){requestAnimationFrame(sample);return;}
                window.__jawlScene.setEmotion('neutral');
                window.__jawlScene.setReducedMotion(true);
                let rest=0,last=null,drift=0;
                function reduced(){
                    if(rest>30 && last!==null) drift=Math.max(drift,Math.abs(arm.rotation.z-last));
                    last=arm.rotation.z;
                    if(++rest<60){requestAnimationFrame(reduced);return;}
                    done({emotion_arm_peak:peak,reduced_motion_late_drift:drift});
                }
                requestAnimationFrame(reduced);
            }
            requestAnimationFrame(sample);
        """)
        assert 0.05 < pose['emotion_arm_peak'] <= 0.3, pose
        assert pose['reduced_motion_late_drift'] < 0.003, pose
        driver.save_screenshot(str(out/'browser.png'))
        driver.execute_async_script("""
            const done=arguments[arguments.length-1];
            window.__validatedVrm.scene.rotation.y+=Math.PI/3;
            requestAnimationFrame(()=>requestAnimationFrame(done));
        """)
        driver.save_screenshot(str(out/'browser-three-quarter.png'))
        driver.execute_script('window.__validatedVrm.scene.rotation.y-=Math.PI/3')
        driver.execute_script('window.__jawlScene.setReducedMotion(false)')
        greeting = driver.execute_async_script("""
            const done=arguments[arguments.length-1];
            const arm=window.__validatedVrm.humanoid.getNormalizedBoneNode('rightLowerArm');
            const baseline=arm.rotation.z; let frames=0,peak=0;
            const triggered=window.__jawlScene.triggerMotion('greeting');
            function sample(){
                peak=Math.max(peak,Math.abs(arm.rotation.z-baseline));
                if(++frames<75){requestAnimationFrame(sample);return;}
                done({triggered,forearm_peak:peak});
            }
            requestAnimationFrame(sample);
        """)
        assert greeting['triggered'] is True and 0.3 < greeting['forearm_peak'] <= 0.73, greeting
        assert hashlib.sha256(model.read_bytes()).hexdigest() == artifact_sha, 'Model changed during validation'
        report.update(status='passed', browser=result, motion=pose, greeting=greeting)
        print(json.dumps(report, ensure_ascii=False))
    except Exception as exc:
        report['failure'] = f'{type(exc).__name__}: {exc}'[:1000]
        raise
    finally:
        if driver: driver.quit()
        server.shutdown(); thread.join(timeout=5); server.server_close()
        (out/'validation.json').write_text(json.dumps(report,indent=2),encoding='utf8')


if __name__ == '__main__':
    main()
