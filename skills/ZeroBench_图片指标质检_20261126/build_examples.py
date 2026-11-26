"""Prepare local evidence examples; never alter upstream tasks or call a model."""
import json
import shutil
from pathlib import Path
from PIL import Image

OUT=Path(__file__).resolve().parent
ROOT=OUT.parent.parent
SHELF=ROOT/'outputs/ZeroBench_难题300指标与选图_20261126/shelves'
for part in ('images','annotations','evidence'):
    (OUT/part).mkdir(exist_ok=True)
items=[]
for p in sorted((SHELF/'annotations').glob('*.json')):
    d=json.loads(p.read_text()); info=d['images'][0]
    shutil.copy2(SHELF/'images'/info['file_name'],OUT/'images'/info['file_name'])
    shutil.copy2(p,OUT/'annotations'/p.name)
    item=dict(id='shelf-'+p.stem,image='images/'+info['file_name'],coco='annotations/'+p.name,
              image_id=info['id'],require_real=True,annotation_provenance='publisher_coco_unmodified',
              source=dict(kind='real_photo',url='https://huggingface.co/datasets/shelfwise-by-form/SKUs_on_shelves_PL',
                          license_url='https://creativecommons.org/licenses/by/4.0/',authorization='verified',
                          attribution='ShelfWise by FORM, SKUs_on_shelves_PL, v1.0 (2024)',scene_id='ShelfWise:'+p.stem))
    # Candidate ROI from a real annotation; readability has NOT been declared passed.
    a=max(d['annotations'],key=lambda a:a['bbox'][2]*a['bbox'][3])
    item['critical_rois']=[dict(id='candidate-object',bbox=a['bbox'],human_readable=None)]
    if p.stem=='22835':
        ann={a['id']:a for a in d['annotations']}
        item['critical_rois']=[dict(id=str(i),bbox=ann[i]['bbox'],human_readable=None) for i in [213696,213796,213763]]
        item['critical_rois'].append(dict(id='price-tag',bbox=[827,388,61,40],human_readable=None))
        item['platform_points']=[dict(xy=[770.5,332],label='起点身份，作者关键点'),dict(xy=[629,490],label='黑胡椒目标，作者关键点'),dict(xy=[856,408],label='空托下黄价签，作者关键点')]
        # Centers of point locations derive from the publisher box for actual products.
        for pt, aid in zip(item['platform_points'][:2],[213696,213796]):
            x,y,w,h=ann[aid]['bbox'];pt['xy']=[x+w/2,y+h/2]
        item['task']=dict(uses_distance=True,bypass_review='pending',
            dependencies=[dict(roi_id='213696',parameter='origin',output='distance_bin'),
                          dict(roi_id='213796',parameter='target_A',output='distance_bin'),
                          dict(roi_id='price-tag',parameter='penalty',output='reversal')],
            measurements=[dict(id='correct-origin',margin=29,error_bound=10,unit='px',error_method='两个横坐标误差各≤5px',evidence='evidence/22835_recompute.json'),
                          dict(id='wrong-origin-control',margin=30,error_bound=10,unit='px',error_method='两个横坐标误差各≤5px',evidence='evidence/22835_recompute.json')],
            counterfactuals=[dict(field='reversal',baseline=True,alternative=False,verified=True,evidence='evidence/22835_recompute.json',change='wrong_origin'),
                             dict(field='reversal',baseline=True,alternative=False,verified=True,evidence='evidence/22835_recompute.json',change='wrong_tag_color')])
        def calc(origin,penalty):
            centers={i:ann[i]['bbox'][0]+ann[i]['bbox'][2]/2 for i in ann}
            distances=[abs(centers[origin]-centers[j]) for j in [213796,213763]]
            costs=[base+(penalty if distance>80 else 0) for base,distance in zip([3,6],distances)]
            return dict(distances=distances,costs=costs,reversal=costs[0]>costs[1])
        proof=dict(baseline=calc(213696,5),wrong_origin=calc(213713,5),wrong_tag_color=calc(213696,2),
                   note='作者反事实复算，不是模型实测；价签颜色依据已有目视记录，仍列本轮人工复核')
        (OUT/'evidence/22835_recompute.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2))
    items.append(item)
pack=ROOT/'outputs/ZeroBench_ZB10三题独立包_20261126'
qmap={q['local_id']:q for q in json.loads((pack/'platform_submission.json').read_text())['questions']}
for name in ['ZB10-06','ZB10-09','ZB10-10','ZBN-05','ZBN-07','ZBN-08']:
    parent=ROOT/('outputs/ZeroBench_batch10_20261126/iteration_v2/cases' if name.startswith('ZB10') else 'outputs/ZeroBench_niche_domains_20261126/cases')/name
    author=json.loads((parent/'author.json').read_text());image=parent/author['image_path']
    target=OUT/'images'/f'{name}.png';shutil.copy2(image,target)
    w,h=Image.open(target).size
    points=qmap.get(name,{}).get('platform_points',author.get('platform_points',[]))
    pp=[dict(xy=[p['x'],p['y']],label=p['label']) for p in points[:3]]
    kind='synthetic_schematic' if name.startswith('ZB10') else 'simulated_observation'
    item=dict(id=name,image='images/'+target.name,require_real=True,
              source=dict(kind=kind,authorization='pending',author_record=str(parent/'author.json')),
              platform_points=pp,critical_rois=[])
    if name=='ZBN-08':
        # Mixed source: real micrograph does not make its calculated spectrum an observed spectrum.
        item['source']['kind']='mixed_composite'
        item['source']['panel_note']='真实金相+计算谱图；须按面板核同一样品假设及许可'
    for i,p in enumerate(pp):
        x,y=p['xy'];left=max(0,x-65);top=max(0,y-65)
        item['critical_rois'].append(dict(id=f'key-{i+1}',bbox=[left,top,min(130,w-left),min(130,h-top)],human_readable=None))
    if name.startswith('ZB10'):
        item['evaluation']=dict(tools_enabled=False,frozen_version='v2',
                               counts={'incorrect':{'ZB10-06':1,'ZB10-10':2,'ZB10-09':0}[name]},
                               note='旧工具关闭条件；不作为工具开放难度验收')
    # Preserve only task provenance and annotation metadata, no API credentials or large trajectories.
    meta={k:author[k] for k in ('id','version','title','source','image_provenance','attribution') if k in author}
    (OUT/'evidence'/f'{name}_provenance.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
    items.append(item)
(OUT/'manifest.json').write_text(json.dumps(dict(items=items),ensure_ascii=False,indent=2))
shutil.copy2(SHELF/'README.md',OUT/'evidence/货架原有筛选记录.md')
print('Prepared',len(items),'local images')
