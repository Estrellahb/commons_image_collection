#!/usr/bin/env python3
"""Offline image/annotation QA. No model calls, downloads or fabricated GT.
Requires existing Pillow and numpy. See references/metrics-and-schema.md.
"""
import argparse
import csv
import html
import json
import math
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


def lab(rgb):
    rgb = np.asarray(rgb, dtype=float) / 255
    lin = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    xyz = np.array([[.4124564, .3575761, .1804375], [.2126729, .7151522, .0721750],
                    [.0193339, .1191920, .9503041]]) @ lin / [ .95047, 1, 1.08883 ]
    f = np.where(xyz > (6/29)**3, np.cbrt(xyz), xyz / (3*(6/29)**2) + 4/29)
    return np.array([116*f[1]-16, 500*(f[0]-f[1]), 200*(f[1]-f[2])])


def valid_rect(box, width, height):
    return (isinstance(box, list) and len(box) == 4 and
            all(isinstance(v, (float, int)) and math.isfinite(v) for v in box) and
            box[0] >= 0 and box[1] >= 0 and min(box[2:]) > 0 and
            box[0]+box[2] <= width and box[1]+box[3] <= height)


def union_area(rects):
    """Exact union of axis-aligned XYWH rectangles; not sum of overlaps."""
    xs = sorted({a for x,y,w,h in rects for a in (x,x+w)})
    total = 0
    for left, right in zip(xs, xs[1:]):
        spans = sorted((y,y+h) for x,y,w,h in rects if x < right and x+w > left)
        end, covered = -math.inf, 0
        for start, stop in spans:
            covered += max(0, stop-max(start,end))
            end = max(end, stop)
        total += (right-left)*covered
    return total


def pixel_stats(im):
    a = np.asarray(im.convert('L'), dtype=float)
    bins = np.bincount(a.astype(np.uint8).ravel(), minlength=256).astype(float)
    p = bins[bins > 0] / a.size
    gx = np.abs(np.diff(a, axis=1)); gy = np.abs(np.diff(a, axis=0))
    return dict(contrast_p90_p10=float(np.percentile(a,90)-np.percentile(a,10)),
                gray_entropy_bits=float(-(p*np.log2(p)).sum()),
                edge_fraction_16=float(((gx >= 16).sum()+(gy >= 16).sum()) /
                                       max(1,gx.size+gy.size)))


def reasoning_metrics(graph):
    """Structural metrics of an AUTHOR-SUPPLIED unrolled DAG, not prompt inference."""
    nodes=graph.get('nodes',[]); byid={n['id']:n for n in nodes}
    if len(nodes)!=len(byid): raise ValueError('duplicate reasoning node id')
    parents={k:set() for k in byid}; children={k:set() for k in byid}
    for u,v in graph.get('edges',[]):
        if u not in byid or v not in byid: raise ValueError('reasoning edge references missing node')
        parents[v].add(u);children[u].add(v)
    todo=set(byid);depth={};evidence={}
    while todo:
        ready=[k for k in todo if parents[k].issubset(depth)]
        if not ready: raise ValueError('reasoning graph cycle: unroll state rounds')
        for k in ready:
            depth[k]=1+max([depth[p] for p in parents[k]],default=0)
            evidence[k]=set().union(*(evidence[p] for p in parents[k]))
            if byid[k].get('kind')=='visual': evidence[k].add(byid[k].get('roi_id',k))
            todo.remove(k)
    outputs=[k for k,n in byid.items() if n.get('kind')=='output']
    return dict(node_count=len(nodes),max_depth=max(depth.values(),default=0),
                branch_nodes=sum(len(v)>1 for v in children.values()),
                join_nodes=sum(len(v)>1 for v in parents.values()),
                multi_visual_join_nodes=sum(len(parents[k])>1 and len(evidence[k])>1 for k in byid),
                output_count=len(outputs),outputs_with_visual_ancestry=sum(bool(evidence[k]) for k in outputs),
                output_visual_coverage=sum(bool(evidence[k]) for k in outputs)/len(outputs) if outputs else None,
                state_nodes=sum(n.get('kind')=='state' for n in nodes),
                parameter_nodes=sum(n.get('kind')=='parameter' for n in nodes),
                output_evidence_regions={k:sorted(evidence[k]) for k in outputs})


def inspect(item, root, out, index):
    def resolve(p):
        p = Path(p)
        return p if p.is_absolute() else root/p
    r = dict(id=item['id'], blockers=[], review=[], advisory=[], metrics={},
             source=item.get('source', {}), difficulty_status='not_evaluated',
             annotation_provenance=item.get('annotation_provenance','unknown'))
    p = resolve(item['image'])
    with Image.open(p) as raw:
        r['metrics'].update(width=raw.width,height=raw.height,mode=raw.mode,
                            exif_orientation=raw.getexif().get(274,1),frame_count=getattr(raw,'n_frames',1))
        if raw.getexif().get(274,1) != 1:
            r['blockers'].append('orientation_not_normalized: 原图与坐标须一起归一化')
        if raw.mode.startswith('I') or raw.mode == 'F':
            r['review'].append('scientific_intensity: 请提交显式显示窗和显示图；本次像素指标不适用')
        im = raw.convert('RGBA')
        bg = Image.new('RGBA',im.size,'white'); bg.alpha_composite(im); im=bg.convert('RGB')
    W,H = im.size
    preview = im.copy(); preview.thumbnail((640,640))
    preview.save(out/f'{index:03d}.jpg',quality=90)
    r['preview'] = f'{index:03d}.jpg'
    if not any('scientific_intensity' in x for x in r['review']):
        r['metrics']['global_640_proxy'] = pixel_stats(preview)
    if min(W,H) < item.get('min_native_short_px',1080):
        r['advisory'].append('native_resolution_below_profile: 以关键特征原生像素复审，不用放大补像素')
    src = item.get('source',{})
    if src.get('authorization') == 'denied': r['blockers'].append('source_permission_denied')
    elif src.get('authorization') != 'verified' or not src.get('url') or not src.get('license_url'):
        r['review'].append('source_permission_evidence_missing')
    if src.get('kind') not in ('real_photo','real_observation','data_rendering','synthetic_schematic','simulated_observation','mixed_composite'):
        r['review'].append('source_kind_unknown')
    if src.get('kind')=='mixed_composite':
        r['review'].append('mixed_panels_require_separate_provenance_and_sample_consistency_review')
    if item.get('require_real',True) and src.get('kind') in ('synthetic_schematic','simulated_observation'):
        r['blockers'].append('real_image_requirement_not_met')
    if item.get('require_real',True) and src.get('kind') == 'data_rendering' and not item.get('allow_data_rendering',False):
        r['review'].append('data_rendering_not_explicitly_allowed')

    objects = item.get('objects')
    if 'coco' in item:
        data = json.loads(resolve(item['coco']).read_text())
        infos = [x for x in data['images'] if x['id']==item.get('image_id')]
        if len(infos)!=1: raise ValueError('COCO must identify exactly one image_id')
        if (infos[0]['width'],infos[0]['height']) != (W,H):
            r['blockers'].append('annotation_image_size_mismatch')
        cats={x['id']:x for x in data.get('categories',[])}
        objects=[]
        for a in data['annotations']:
            if a['image_id'] != item['image_id']: continue
            cat=cats.get(a['category_id'],{})
            known=bool(cat) and cat.get('supercategory')!='N/A' and cat.get('name','').lower() not in ('unknown','n/a','')
            objects.append(dict(id=str(a['id']),bbox=a['bbox'],category=str(a['category_id']) if known else None))
    good=[]
    if objects is None: r['review'].append('objects_missing: 不把边缘数当目标数')
    else:
        ids=[str(o.get('id')) for o in objects]
        if len(ids)!=len(set(ids)): r['blockers'].append('duplicate_object_ids')
        for o in objects:
            b=o.get('bbox')
            if item.get('bbox_policy')=='clip_visible' and isinstance(b,list) and len(b)==4 and all(isinstance(v,(int,float)) and math.isfinite(v) for v in b) and min(b[2:])>0:
                x,y,w,h=b
                clipped=[max(0,x),max(0,y),min(W,x+w)-max(0,x),min(H,y+h)-max(0,y)]
                if clipped!=b and valid_rect(clipped,W,H):
                    r.setdefault('bbox_adjustments',[]).append(dict(id=o.get('id'),original=b,visible=clipped))
                    o={**o,'bbox':clipped}
            if valid_rect(o.get('bbox'),W,H): good.append(o)
            else: r['blockers'].append('invalid_bbox:'+str(o.get('id')))
        if r.get('bbox_adjustments'):
            r['review'].append('visible_bbox_clipping_applied: 核查边缘目标口径；原标注文件未改')
        known=[o for o in good if o.get('category') is not None]
        counts=Counter(o['category'] for o in known)
        grid=Counter((min(3,int((o['bbox'][0]+o['bbox'][2]/2)/W*4)),
                      min(3,int((o['bbox'][1]+o['bbox'][3]/2)/H*4))) for o in good)
        probs=np.array(list(grid.values()),dtype=float)/max(1,len(good))
        r['metrics'].update(object_count=len(good),objects_per_MP=len(good)*1e6/(W*H),
            class_count=len(counts),known_fraction=len(known)/len(good) if good else None,
            repeated_classes=sum(v>1 for v in counts.values()),
            spatial_entropy_4x4=float(-(probs*np.log2(probs)).sum()/4) if len(probs) else None,
            median_bbox_short_px=float(np.median([min(o['bbox'][2:]) for o in good])) if good else None,
            p10_bbox_short_px=float(np.percentile([min(o['bbox'][2:]) for o in good],10)) if good else None,
            edge_touching_count=sum(x<=1 or y<=1 or x+w>=W-1 or y+h>=H-1 for x,y,w,h in [o['bbox'] for o in good]))
        colors=[]
        for o in good:
            x,y,w,h=o['bbox']; rect=(x+.2*w,y+.2*h,x+.8*w,y+.8*h)
            cr=(math.floor(rect[0]),math.floor(rect[1]),math.ceil(rect[2]),math.ceil(rect[3]))
            colors.append(lab(np.median(np.asarray(im.crop(cr).resize((24,24))),axis=(0,1))))
        near, overlap, neighbors=[],[],0
        for i,a in enumerate(good):
            x,y,w,h=a['bbox']
            for j,b in enumerate(good[:i]):
                u,v,pw,ph=b['bbox']
                inter=max(0,min(x+w,u+pw)-max(x,u))*max(0,min(y+h,v+ph)-max(y,v))
                iom=inter/min(w*h,pw*ph)
                if iom>=.15: overlap.append(dict(a=a['id'],b=b['id'],iom=iom))
                if a.get('category') is None or b.get('category') is None or a['category']==b['category']: continue
                dist=math.hypot((x+w/2-u-pw/2)/((w+pw)/2),(y+h/2-v-ph/2)/((h+ph)/2))
                if dist>1.8: continue
                neighbors+=1; de=float(np.linalg.norm(colors[i]-colors[j]))
                if de<=12: near.append(dict(a=a['id'],b=b['id'],deltaE76=de))
        r['nearcolor_pairs']=near; r['overlap_candidates']=overlap
        r['metrics'].update(nearcolor_pair_count=len(near),different_class_neighbor_pairs=neighbors,
            nearcolor_neighbor_fraction=len(near)/neighbors if neighbors else None,
            bbox_overlap_pair_count=len(overlap))
        if not good: r['review'].append('empty_objects')
        if good and len(known)/len(good)<.85: r['advisory'].append('class_coverage_below_0.85')

    roi_metrics=[]
    rois=item.get('critical_rois',[])
    if not rois: r['review'].append('critical_rois_missing')
    for roi in rois:
        if not valid_rect(roi.get('bbox'),W,H):
            r['blockers'].append('invalid_critical_roi:'+str(roi.get('id'))); continue
        x,y,w,h=roi['bbox']; crop=im.crop((int(x),int(y),math.ceil(x+w),math.ceil(y+h)))
        name=f'{index:03d}_roi{len(roi_metrics)+1}.png'; crop.save(out/name)
        stats=dict(id=roi.get('id'),file=name,**pixel_stats(crop))
        roi_metrics.append(stats)
        if roi.get('human_readable') is False: r['blockers'].append('critical_feature_unreadable:'+str(roi.get('id')))
        elif roi.get('human_readable') is not True: r['review'].append('critical_readability_pending:'+str(roi.get('id')))
    r['roi_metrics']=roi_metrics
    ocr=item.get('ocr')
    if ocr is None: r['review'].append('chinese_text_coverage_unknown')
    else:
        rects=ocr.get('han_bboxes',[])
        if any(not valid_rect(b,W,H) for b in rects): r['blockers'].append('invalid_ocr_bbox')
        else:
            cov=union_area(rects)/(W*H); r['metrics']['han_text_coverage']=cov
            if cov>.05: r['advisory'].append('han_text_over_5pct: 这是可配置复核线，不是平台官方阈值')
        if ocr.get('reviewed') is not True: r['review'].append('ocr_human_review_pending')
    checks=item.get('human_checks',{})
    for key in ('source_fidelity','annotation_correct','critical_evidence_visible','no_answer_leakage','counting_rules_clear'):
        if checks.get(key) is False: r['blockers'].append('human_check_failed:'+key)
        elif checks.get(key) is not True: r['review'].append('human_check_pending:'+key)
    task=item.get('task',{})
    graph=task.get('reasoning_graph')
    if graph:
        try:
            r['reasoning_metrics']=reasoning_metrics(graph)
            for n in graph.get('nodes',[]):
                if n.get('kind')=='visual' and n.get('roi_id') not in {v.get('id') for v in rois}:
                    r['blockers'].append('reasoning_visual_node_missing_roi')
            if not r['reasoning_metrics']['output_count']: r['review'].append('reasoning_graph_has_no_outputs')
            elif r['reasoning_metrics']['output_visual_coverage']<1: r['review'].append('some_outputs_have_no_visual_ancestry')
        except (ValueError,KeyError,TypeError) as e:
            r['blockers'].append('invalid_reasoning_graph:'+str(e))
    elif task: r['review'].append('reasoning_graph_missing')
    deps=task.get('dependencies',[])
    roi_ids={r.get('id') for r in rois}
    if len(deps)<2: r['review'].append('multi_region_dependencies_unproven')
    for d in deps:
        if d.get('roi_id') not in roi_ids or not d.get('parameter') or not d.get('output'):
            r['blockers'].append('broken_visual_dependency')
    r['metrics']['distinct_dependency_regions']=len({d.get('roi_id') for d in deps})
    cf=task.get('counterfactuals',[])
    effective=[c for c in cf if c.get('verified') is True and c.get('evidence') and
               c.get('field') and 'baseline' in c and 'alternative' in c and c['baseline']!=c['alternative']]
    r['metrics']['effective_counterfactuals']=len(effective)
    if not effective: r['review'].append('wrong_pair_to_answer_effect_unproven')
    for m in task.get('measurements',[]):
        if not all(k in m for k in ('margin','error_bound','unit','error_method','evidence')) or m.get('error_bound',0)<=0 or m.get('margin',-1)<0:
            r['review'].append('measurement_uncertainty_missing'); continue
        ratio=m['margin']/m['error_bound']
        r.setdefault('measurement_margins',[]).append(dict(id=m.get('id'),ratio=ratio,unit=m['unit']))
        if ratio<=1: r['blockers'].append('measurement_threshold_not_robust:'+str(m.get('id')))
    if task.get('uses_distance') and not task.get('measurements'): r['review'].append('distance_margin_missing')
    if task.get('bypass_review')!='passed': r['review'].append('bypass_review_pending_or_failed')
    points=item.get('platform_points',[])
    if not 1<=len(points)<=3: r['review'].append('platform_points_expected_1_to_3')
    for pt in points:
        xy=pt.get('xy',[])
        if len(xy)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in xy) or not(0<=xy[0]<W and 0<=xy[1]<H) or not pt.get('label'):
            r['blockers'].append('invalid_platform_point')
    r['platform_points']=points
    if points and len({tuple(p.get('xy',[])) for p in points})!=len(points): r['blockers'].append('duplicate_platform_points')
    ev=item.get('evaluation',{})
    if ev:
        r['evaluation_counts']=ev.get('counts',{})
        if ev.get('tools_enabled') is not True: r['difficulty_status']='nonconforming_or_unknown_tools'
        elif ev.get('counts',{}).get('incorrect',0)>0:
            r['difficulty_status']='reported_failure_pending_review'
            if all(ev.get(k) for k in ('frozen_version','trajectory','gt_review','failure_attribution')):
                r['difficulty_status']='documented_failure_evidence_requires_human_acceptance'
        else: r['difficulty_status']='no_complete_failure_recorded'
    r['decision']='blocked' if r['blockers'] else 'needs_review' if r['review'] else 'authoring_candidate'
    return r


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('manifest',type=Path); ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    doc=json.loads(a.manifest.read_text()); items=doc['items'] if isinstance(doc,dict) else doc
    rows=[]; seen=set()
    for i,item in enumerate(items,1):
        try:
            row=inspect(item,a.manifest.parent,a.out,i)
        except Exception as e:
            row=dict(id=item.get('id',str(i)),decision='input_error',error=f'{type(e).__name__}: {e}',metrics={},review=[],blockers=[],advisory=[])
        if item.get('id') in seen:
            row['blockers'].append('duplicate_manifest_id');row['decision']='blocked'
        seen.add(item.get('id')); rows.append(row)
    groups={}
    for item in items:
        key=item.get('source',{}).get('scene_id')
        if key: groups.setdefault(key,[]).append(item['id'])
    duplicate_scenes={k:v for k,v in groups.items() if len(v)>1}
    result=dict(schema_version=1,summary=dict(Counter(r['decision'] for r in rows)),
                duplicate_scene_groups=duplicate_scenes,items=rows,
                limitations=['没有模型调用；指标不是难度证明','同场景分组只依赖显式scene_id，不是视觉去重','人工复核字段是声明，需审查其证据'])
    (a.out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    keys=['id','decision','difficulty_status','width','height','object_count','class_count','known_fraction','median_bbox_short_px','nearcolor_pair_count','bbox_overlap_pair_count','distinct_dependency_regions','effective_counterfactuals','blockers','review','advisory']
    with (a.out/'metrics.csv').open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.DictWriter(f,fieldnames=keys);writer.writeheader()
        for r in rows:
            flat={**r,**r['metrics']};writer.writerow({k:json.dumps(flat[k],ensure_ascii=False) if isinstance(flat.get(k),(dict,list)) else flat.get(k) for k in keys})
    cards=[]
    for r in rows:
        esc=lambda v:html.escape(str(v))
        img=f'<img src="{esc(r["preview"])}" loading="lazy">' if r.get('preview') else ''
        cards.append(f'<article><h2>{esc(r["id"])} · {esc(r["decision"])}</h2>{img}<pre>{esc(json.dumps(r,ensure_ascii=False,indent=2))}</pre></article>')
    (a.out/'index.html').write_text('<!doctype html><html lang="zh"><meta charset="utf-8"><title>ZeroBench 图片质检</title><style>body{font:16px system-ui;margin:30px;background:#f4f4f1;color:#202020}article{background:white;margin:22px 0;padding:24px;border:1px solid #ddd;overflow:auto}img{max-width:48%;float:left;margin:0 24px 16px 0}pre{white-space:pre-wrap;font-size:13px}h1{font-size:28px}</style><h1>图片与题目证据质检</h1><p>代理指标用于筛选，不证明难度。缺失值不会自动通过；判定与试答证据分开。</p>'+''.join(cards)+'</html>')
    print(json.dumps(result['summary'],ensure_ascii=False))
    print(a.out/'index.html')
    return 2 if any(r['decision']=='input_error' for r in rows) else 0


if __name__=='__main__':
    raise SystemExit(main())
