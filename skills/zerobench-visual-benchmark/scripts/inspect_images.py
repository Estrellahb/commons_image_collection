#!/usr/bin/env python3
"""Offline image/annotation QA. No model calls, downloads or fabricated GT.
Requires existing Pillow and numpy. See references/image-metrics.md.
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


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def nonuniform_scale(sx, sy, source_width, source_height):
    # A normal thumbnail rounds output width/height to integer pixels.
    # Do not report this bounded rounding as an aspect-ratio deformation.
    return abs(sx-sy) > .5/source_width + .5/source_height + 1e-9


def geometry_metrics(item, size, resolve, report):
    """Native means source samples, not a large exported file or a montage canvas."""
    width, height = size
    geo = item.get('image_geometry') or {}
    kind = geo.get('kind', 'unknown')
    result = dict(kind=kind, submitted_size_px=[width,height], native_size_px=None,
                  native_size_evidence='unknown', panels=[])

    def native_size(spec):
        if spec.get('native_image'):
            with Image.open(resolve(spec['native_image'])) as image:
                return list(image.size), 'source_file'
        declared = spec.get('native_size_px')
        if isinstance(declared,list) and len(declared)==2 and all(number(v) and v>0 for v in declared):
            return declared, 'author_declaration'
        return None, 'unknown'

    if kind == 'native':
        result.update(native_size_px=[width,height], native_size_evidence='author_native_declaration')
        other, _ = native_size(geo)
        if other is not None and other != [width,height]:
            report['blockers'].append('declared_native_size_mismatch')
    elif kind in ('crop','resized'):
        native, evidence = native_size(geo)
        result.update(native_size_px=native, native_size_evidence=evidence)
        crop = geo.get('source_crop_xywh')
        if crop is None and kind=='resized' and native: crop=[0,0,*native]
        if native and valid_rect(crop,*native):
            sx,sy=width/crop[2],height/crop[3]
            result.update(sampled_source_size_px=crop[2:],scale_xy=[sx,sy])
            if max(sx,sy)>1.001: report['advisory'].append('upsampled_pixels_do_not_add_native_evidence')
            if nonuniform_scale(sx,sy,crop[2],crop[3]): report['review'].append('nonuniform_resize_requires_distance_review')
        else: report['review'].append('source_crop_or_native_size_missing')
    elif kind == 'montage':
        if not geo.get('panels'): report['review'].append('montage_panel_geometry_missing')
        for panel in geo.get('panels',[]):
            native,evidence=native_size(panel)
            row=dict(id=panel.get('id'),native_size_px=native,native_size_evidence=evidence,
                     source_crop_xywh=panel.get('source_crop_xywh'),output_xywh=panel.get('output_xywh'))
            if not valid_rect(panel.get('output_xywh'),width,height):
                report['blockers'].append('invalid_montage_output_box:'+str(panel.get('id')))
            elif native and valid_rect(panel.get('source_crop_xywh'),*native):
                scales=[panel['output_xywh'][2]/panel['source_crop_xywh'][2],
                        panel['output_xywh'][3]/panel['source_crop_xywh'][3]]
                row['scale_xy']=scales
                if max(scales)>1.001: report['advisory'].append('upsampled_panel:'+str(panel.get('id')))
                if nonuniform_scale(*scales,*panel['source_crop_xywh'][2:]): report['review'].append('nonuniform_panel_resize:'+str(panel.get('id')))
            else: report['review'].append('panel_native_geometry_missing:'+str(panel.get('id')))
            result['panels'].append(row)
        report['advisory'].append('montage_canvas_is_not_native_resolution_or_independent_scenes')
    else:
        report['review'].append('native_geometry_unknown: 文件大小不能证明未放大')
    return result


def lab(rgb):
    rgb = np.asarray(rgb, dtype=float) / 255
    lin = np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)
    xyz = np.array([[.4124564, .3575761, .1804375], [.2126729, .7151522, .0721750],
                    [.0193339, .1191920, .9503041]]) @ lin / [ .95047, 1, 1.08883 ]
    f = np.where(xyz > (6/29)**3, np.cbrt(xyz), xyz / (3*(6/29)**2) + 4/29)
    return np.array([116*f[1]-16, 500*(f[0]-f[1]), 200*(f[1]-f[2])])


def valid_rect(box, width, height):
    return (isinstance(box, list) and len(box) == 4 and
            all(number(v) for v in box) and
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
    unknown_metrics = dict.fromkeys(('object_count','objects_per_MP','class_count','known_fraction',
        'median_bbox_short_px','nearcolor_pair_count','nearcolor_neighbor_fraction','bbox_overlap_pair_count',
        'active_object_count','active_objects_per_submitted_MP','active_entity_count',
        'active_fraction_of_annotated_objects','inactive_annotated_count','background_object_count',
        'active_objects_per_region_MP','han_text_coverage','annotated_occlusion_fraction',
        'distinct_dependency_regions','effective_counterfactuals'))
    r = dict(id=item['id'], blockers=[], review=[], advisory=[], metrics=unknown_metrics,
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
    r['geometry']=geometry_metrics(item,(W,H),resolve,r)
    r['metrics'].update(submitted_width=W,submitted_height=H,
        native_width=r['geometry']['native_size_px'][0] if r['geometry']['native_size_px'] else None,
        native_height=r['geometry']['native_size_px'][1] if r['geometry']['native_size_px'] else None)
    preview = im.copy(); preview.thumbnail((640,640))
    preview.save(out/f'{index:03d}.jpg',quality=90)
    r['preview'] = f'{index:03d}.jpg'
    if not any('scientific_intensity' in x for x in r['review']):
        r['metrics']['global_640_proxy'] = pixel_stats(preview)
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
            objects.append(dict(id=str(a['id']),bbox=a['bbox'],category=str(a['category_id']) if known else None,
                category_name=cat.get('name'),is_group=bool(a['iscrowd']) if 'iscrowd' in a else None))
    good=[]
    if objects is None: r['review'].append('objects_missing: 不把边缘数当目标数')
    else:
        objects=[{**o,'id':str(o['id'])} if o.get('id') is not None else o for o in objects]
        ids=[str(o.get('id')) for o in objects]
        if any(o.get('id') is None for o in objects): r['blockers'].append('missing_object_id')
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
        known=[o for o in good if o.get('category') not in (None,'','unknown','n/a')]
        known_ids={o['id'] for o in known}
        counts=Counter(o['category'] for o in known)
        grid=Counter((min(3,int((o['bbox'][0]+o['bbox'][2]/2)/W*4)),
                      min(3,int((o['bbox'][1]+o['bbox'][3]/2)/H*4))) for o in good)
        probs=np.array(list(grid.values()),dtype=float)/max(1,len(good))
        r['metrics'].update(object_count=len(good),objects_per_MP=len(good)*1e6/(W*H),
            class_count=len(counts) if known else None,known_class_count=len(counts),known_fraction=len(known)/len(good) if good else None,
            repeated_classes=sum(v>1 for v in counts.values()),
            spatial_entropy_4x4=float(-(probs*np.log2(probs)).sum()/4) if len(probs) else None,
            median_bbox_short_px=float(np.median([min(o['bbox'][2:]) for o in good])) if good else None,
            p10_bbox_short_px=float(np.percentile([min(o['bbox'][2:]) for o in good],10)) if good else None,
            edge_touching_count=sum(x<=1 or y<=1 or x+w>=W-1 or y+h>=H-1 for x,y,w,h in [o['bbox'] for o in good]))
        r['metrics']['annotation_complete']=item.get('annotation_complete') if isinstance(item.get('annotation_complete'),bool) else None
        r['advisory'].append('object_count_is_annotation_box_count_not_proven_physical_instances')
        if item.get('category_level') not in ('verified_task_classes','verified_sku'):
            r['review'].append('task_category_granularity_pending: 品牌/大类标签不能默认等于SKU')
        active_ids=item.get('task',{}).get('active_object_ids')
        if active_ids is None:
            r['review'].append('active_objects_unknown: 不默认背景和全部标注都参与求解')
        elif not isinstance(active_ids,list):
            r['blockers'].append('active_object_ids_must_be_list')
        else:
            active_ids=[str(v) for v in active_ids]; selected=set(active_ids)
            available={o['id'] for o in good}
            if len(selected)!=len(active_ids): r['blockers'].append('duplicate_active_object_ids')
            if selected-available: r['blockers'].append('active_object_ids_not_in_valid_annotations')
            else:
                active=[o for o in good if o['id'] in selected]
                count=len(active)
                r['metrics'].update(active_object_count=count,active_objects_per_submitted_MP=count*1e6/(W*H),
                    active_fraction_of_annotated_objects=count/len(good) if good else None,
                    inactive_annotated_count=len(good)-count,
                    median_active_bbox_short_px=float(np.median([min(o['bbox'][2:]) for o in active])) if active else None,
                    active_known_class_count=len({o['category'] for o in active if o['id'] in known_ids}))
                if any(o.get('is_group') for o in active): r['review'].append('active_group_boxes_are_not_individual_counts')
                if all(o.get('entity_id') is not None for o in active):
                    r['metrics']['active_entity_count']=len({str(o['entity_id']) for o in active})
                elif item.get('object_unit')=='physical_instance' and r['geometry']['kind']!='montage':
                    r['metrics']['active_entity_count']=count
                else: r['review'].append('active_entity_count_unknown: 多视图/镜像重复呈现需entity_id')
                if item.get('annotation_complete') is True and item.get('object_unit')=='physical_instance' and r['geometry']['kind']!='montage':
                    r['metrics']['background_object_count']=len(good)-count
                regions=item.get('task',{}).get('active_region_bboxes')
                if regions:
                    if not all(valid_rect(b,W,H) for b in regions): r['blockers'].append('invalid_active_region_bbox')
                    elif all(any(x<=o['bbox'][0]+o['bbox'][2]/2<x+w and y<=o['bbox'][1]+o['bbox'][3]/2<y+h for x,y,w,h in regions) for o in active):
                        r['metrics']['active_objects_per_region_MP']=count*1e6/union_area(regions)
                    else: r['blockers'].append('active_centers_outside_declared_region')
        occluded=[o for o in good if isinstance(o.get('occluded'),bool)]
        r['metrics']['occlusion_annotation_count']=len(occluded)
        if good and len(occluded)==len(good):
            r['metrics']['annotated_occlusion_fraction']=sum(o['occluded'] for o in occluded)/len(good)
        colors=[]
        for o in good:
            x,y,w,h=o['bbox']; rect=(x+.2*w,y+.2*h,x+.8*w,y+.8*h)
            if o.get('color_roi') is not None:
                if valid_rect(o['color_roi'],W,H):
                    cx,cy,cw,ch=o['color_roi'];rect=(cx,cy,cx+cw,cy+ch)
                else: r['blockers'].append('invalid_color_roi:'+str(o['id']))
            cr=(math.floor(rect[0]),math.floor(rect[1]),math.ceil(rect[2]),math.ceil(rect[3]))
            colors.append(lab(np.median(np.asarray(im.crop(cr).resize((24,24))),axis=(0,1))))
        near, overlap, duplicates, neighbors=[],[],[],0
        for i,a in enumerate(good):
            x,y,w,h=a['bbox']
            for j,b in enumerate(good[:i]):
                u,v,pw,ph=b['bbox']
                inter=max(0,min(x+w,u+pw)-max(x,u))*max(0,min(y+h,v+ph)-max(y,v))
                iom=inter/min(w*h,pw*ph)
                iou=inter/(w*h+pw*ph-inter)
                if iom>=.15: overlap.append(dict(a=a['id'],b=b['id'],iom=iom,iou=iou))
                if iou>=.85: duplicates.append(dict(a=a['id'],b=b['id'],iou=iou))
                if a['id'] not in known_ids or b['id'] not in known_ids or a['category']==b['category']: continue
                dist=math.hypot((x+w/2-u-pw/2)/((w+pw)/2),(y+h/2-v-ph/2)/((h+ph)/2))
                if dist>1.8: continue
                neighbors+=1; de=float(np.linalg.norm(colors[i]-colors[j]))
                if de<=12: near.append(dict(a=a['id'],b=b['id'],deltaE76=de))
        r['nearcolor_pairs']=near; r['overlap_candidates']=overlap; r['duplicate_bbox_candidates']=duplicates
        r['metrics'].update(nearcolor_pair_count=len(near) if len(known)>=2 else None,different_class_neighbor_pairs=neighbors if len(known)>=2 else None,
            nearcolor_neighbor_fraction=len(near)/neighbors if neighbors else None,
            bbox_overlap_pair_count=len(overlap),duplicate_bbox_candidate_count=len(duplicates))
        if duplicates: r['review'].append('near_duplicate_boxes_require_entity_review: 不自动合并或算成遮挡')
        r['metrics']['active_nearcolor_pair_count']=(sum(p['a'] in set(active_ids) and p['b'] in set(active_ids) for p in near)
            if isinstance(active_ids,list) and not (set(active_ids)-{o['id'] for o in good}) and len(known)>=2 else None)
        r['advisory'].append('local_color_pairs_and_box_overlaps_are_candidates_not_difficulty_or_occlusion_proof')
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
        stats=dict(id=roi.get('id'),file=name,submitted_crop_size_px=list(crop.size),
            feature_width_native_px=roi.get('feature_width_native_px'),
            native_readability_reviewed=roi.get('native_readability_reviewed'),
            pixel_metric_basis='submitted_pixels',
            **(pixel_stats(crop) if not any('scientific_intensity' in v for v in r['review']) else {}))
        roi_metrics.append(stats)
        if roi.get('feature_width_native_px') is not None and (not number(roi['feature_width_native_px']) or roi['feature_width_native_px']<=0):
            r['blockers'].append('invalid_native_feature_width:'+str(roi.get('id')))
        if r['geometry']['kind']!='native' and roi.get('native_readability_reviewed') is not True:
            r['review'].append('native_roi_readability_pending:'+str(roi.get('id')))
        if roi.get('human_readable') is False: r['blockers'].append('critical_feature_unreadable:'+str(roi.get('id')))
        elif roi.get('human_readable') is not True: r['review'].append('critical_readability_pending:'+str(roi.get('id')))
    r['roi_metrics']=roi_metrics
    ocr=item.get('ocr')
    if ocr is None: r['review'].append('chinese_text_coverage_unknown')
    else:
        rects=ocr.get('han_bboxes')
        if rects is None: r['review'].append('han_bboxes_unknown: 不将缺失OCR框当成空列表')
        elif any(not valid_rect(b,W,H) for b in rects): r['blockers'].append('invalid_ocr_bbox')
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
    r['metrics']['distinct_dependency_regions']=len({d.get('roi_id') for d in deps}) if 'dependencies' in task else None
    cf=task.get('counterfactuals',[])
    effective=[c for c in cf if c.get('verified') is True and c.get('evidence') and
               c.get('field') and 'baseline' in c and 'alternative' in c and c['baseline']!=c['alternative']]
    r['metrics']['effective_counterfactuals']=len(effective) if 'counterfactuals' in task else None
    if not effective: r['review'].append('wrong_pair_to_answer_effect_unproven')
    for m in task.get('measurements',[]):
        if not all(k in m for k in ('margin','error_bound','unit','error_method','evidence')) or not number(m.get('error_bound')) or not number(m.get('margin')) or m['error_bound']<=0 or m['margin']<0:
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
        counts=ev.get('counts') or {}
        r['evaluation_counts']={key:counts.get(key) for key in ('correct','incorrect','timeout','infra_error','partial','content_invalid')}
        invalid_counts=[key for key,value in counts.items() if not isinstance(value,int) or isinstance(value,bool) or value<0]
        if invalid_counts: r['review'].append('invalid_evaluation_counts:'+','.join(invalid_counts))
        if ev.get('tools_enabled') is not True: r['difficulty_status']='nonconforming_or_unknown_tools'
        elif invalid_counts or not isinstance(counts.get('incorrect'),int) or not isinstance(counts.get('correct'),int):
            r['difficulty_status']='evaluation_counts_unknown'
        elif counts['incorrect']>0:
            r['difficulty_status']='reported_failure_pending_review'
            if all(ev.get(k) for k in ('frozen_version','trajectory','gt_review','failure_attribution')):
                r['difficulty_status']='documented_failure_evidence_requires_human_acceptance'
        elif counts['correct']==0: r['difficulty_status']='no_completed_valid_trials'
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
    groups={}; source_groups={}; video_groups={}
    for item in items:
        source=item.get('source',{});key=source.get('scene_id')
        if key: groups.setdefault(key,[]).append(item['id'])
        if source.get('source_asset_id'): source_groups.setdefault(source['source_asset_id'],[]).append(item['id'])
        if source.get('video_id'): video_groups.setdefault(source['video_id'],[]).append(dict(id=item['id'],pts_seconds=source.get('pts_seconds'),scene_id=key))
    duplicate_scenes={k:v for k,v in groups.items() if len(v)>1}
    result=dict(schema_version=2,summary=dict(Counter(r['decision'] for r in rows)),
                duplicate_scene_groups=duplicate_scenes,
                shared_source_asset_groups={k:v for k,v in source_groups.items() if len(v)>1},
                video_source_groups=video_groups,items=rows,
                limitations=['没有模型调用、下载或依赖安装；没有单一难度总分','未知字段为null，不是0或自动通过',
                    '框数是标注量，参与数是作者登记子集；都需实体和分类审核',
                    '框重叠不是遮挡，近色只作局部候选；没有实际遮挡标注时遮挡率未知',
                    '同源和视频分组只依赖显式元数据，不是视觉去重或相邻帧检测',
                    'native声明与人工复核字段不是程序独立证明，需审查引用证据'])
    (a.out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    keys=['id','decision','difficulty_status','submitted_width','submitted_height','native_width','native_height',
          'object_count','active_object_count','active_entity_count','active_objects_per_submitted_MP',
          'active_objects_per_region_MP','background_object_count','class_count','known_fraction',
          'median_bbox_short_px','nearcolor_pair_count','bbox_overlap_pair_count','annotated_occlusion_fraction',
          'distinct_dependency_regions','effective_counterfactuals','blockers','review','advisory']
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
