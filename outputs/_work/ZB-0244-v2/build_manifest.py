import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
facts = json.loads((HERE / 'facts.json').read_text())
source = json.loads((HERE / 'source.json').read_text())
recompute = json.loads((HERE / 'recompute.json').read_text())
reviewed = (HERE / 'qa_manual_completed.json').exists()
rois = [
    ('column_A', [430, 180, 410, 960]),
    ('column_B', [850, 130, 340, 1040]),
    ('column_C', [1210, 140, 375, 950]),
    ('column_D', [1570, 120, 325, 970]),
    ('lower_boundary', [1580, 1090, 300, 160]),
    ('A5_small_spots', [500, 950, 300, 180]),
]
nodes = [{'id': rid, 'kind': 'visual', 'roi_id': rid} for rid, box in rois]
nodes += [
    {'id': 'membership', 'kind': 'parameter'},
    {'id': 'attributes', 'kind': 'parameter'},
    {'id': 'edges', 'kind': 'parameter'},
    {'id': 'routes', 'kind': 'aggregate'},
    {'id': 'plans', 'kind': 'aggregate'},
    {'id': 'cost0', 'kind': 'optimize'},
    {'id': 'cost1', 'kind': 'optimize'},
] + [{'id': f'Q{i}', 'kind': 'output'} for i in range(1, 7)]
edges = [[rid, 'membership'] for rid, box in rois[:5]]
edges += [[rid, 'attributes'] for rid, box in rois if rid != 'lower_boundary']
edges += [['membership', 'attributes'], ['membership', 'edges'], ['attributes', 'edges'],
          ['attributes', 'Q1'], ['edges', 'Q2'], ['edges', 'routes'], ['attributes', 'routes'],
          ['routes', 'Q3'], ['routes', 'plans'], ['attributes', 'plans'], ['plans', 'Q4'],
          ['plans', 'cost0'], ['plans', 'cost1'], ['attributes', 'cost1'],
          ['cost0', 'Q5'], ['cost1', 'Q6']]
counterfactuals = []
for alt in recompute['alternatives']:
    counterfactuals.append({
        'field': 'Q4_double_route_count', 'baseline': recompute['baseline']['answer'][3],
        'alternative': alt['result']['answer'][3], 'verified': True,
        'change': alt['change'], 'evidence': 'recompute.json; independent_verification.json',
    })
trial_path = HERE / 'blind_trials.json'
evaluation = {'tools_enabled': True, 'frozen_version': HERE.name,
              'counts': {'correct': 0, 'incorrect': 0, 'timeout': 0, 'infra_error': 0, 'partial': 0},
              'trajectory': '', 'gt_review': '', 'failure_attribution': ''}
if trial_path.exists():
    evaluation.update(json.loads(trial_path.read_text())['evaluation'])
item = {
    'id': HERE.name,
    'image': '../../authoring_ZB-0244-v2/' + facts['image'],
    'require_real': True, 'allow_data_rendering': False, 'min_native_short_px': 1080,
    'source': {'kind': 'real_photo', 'url': source['source_page'],
               'license_url': 'https://creativecommons.org/licenses/by-sa/4.0/',
               'authorization': 'verified', 'scene_id': source['scene_id'],
               'author': source['author'], 'evidence': 'source.json; source_page.html'},
    'annotation_provenance': 'author_manual_on_native_original',
    'objects': facts['objects'],
    'critical_rois': [{'id': rid, 'bbox': box, 'human_readable': True if reviewed else None}
                      for rid, box in rois],
    'ocr': {'han_bboxes': [], 'reviewed': reviewed,
            'review_method': '逐列原生裁图两次人工检查；只用位置和斑纹，标签拉丁字母不参与求解'},
    'platform_points': facts['platform_points'],
    'human_checks': {k: True if reviewed else None for k in [
        'source_fidelity', 'annotation_correct', 'critical_evidence_visible',
        'no_answer_leakage', 'counting_rules_clear']},
    'task': {
        'uses_distance': False,
        'dependencies': [
            {'roi_id': 'column_A', 'parameter': 'A列成员与F/H', 'output': 'Q1,Q2,Q3,Q4,Q5,Q6'},
            {'roi_id': 'column_B', 'parameter': 'B列F=0成员B4', 'output': 'Q1,Q2,Q3,Q4,Q5,Q6'},
            {'roi_id': 'column_C', 'parameter': 'C4冷色后翅，约束八件H和等于7', 'output': 'Q1,Q4,Q5,Q6'},
            {'roi_id': 'column_D', 'parameter': '白斑D1和D6的F=0', 'output': 'Q1,Q2,Q3,Q4,Q5,Q6'},
            {'roi_id': 'lower_boundary', 'parameter': '排除D7，确定列内编号', 'output': 'Q1,Q2,Q3,Q4,Q5,Q6'},
            {'roi_id': 'A5_small_spots', 'parameter': 'A5零星小点不构成主斑', 'output': 'Q1,Q2,Q3,Q4,Q6'},
        ],
        'measurements': [{'id': 'membership_y_window', 'margin': 20, 'error_bound': 5,
                          'unit': 'px', 'error_method': '胸部中心原生坐标人工定位欧氏误差≤5px，纵向分量≤5px。保守余量20px。',
                          'evidence': 'measurement.md; facts.json'}],
        'counterfactuals': counterfactuals,
        'bypass_review': 'passed' if reviewed else 'pending',
        'reasoning_graph': {'nodes': nodes, 'edges': edges},
    },
    'evaluation': evaluation,
}
(HERE / 'manifest.json').write_text(json.dumps({'items': [item]}, ensure_ascii=False, indent=2))
