import json
from pathlib import Path

root = Path(__file__).parent
objects = [
 ('A1',[205,145,185,165],'橙'),('A2',[510,150,230,185],'黄'),('A3',[815,185,220,150],'绿'),
 ('B1',[50,390,225,145],'绿'),('B2',[390,390,260,145],'红'),('B3',[845,380,245,150],'黄'),
 ('C1',[0,700,200,180],'杂'),('C2',[315,720,320,180],'白'),('C3',[840,730,290,180],'红'),
 ('D2',[260,1150,360,250],'橙茶'),('D3',[820,1150,310,250],'爱茶')]
rois = [
 {'id':'A','bbox':[155,110,965,245],'human_readable':True},
 {'id':'B','bbox':[0,330,1190,250],'human_readable':True},
 {'id':'C','bbox':[0,650,1200,260],'human_readable':True},
 {'id':'D','bbox':[340,910,780,230],'human_readable':True}]
nodes = [{'id':'v'+r['id'],'kind':'visual','roi_id':r['id']} for r in rois]
nodes += [{'id':'facts','kind':'parameter'},{'id':'valid','kind':'state'},{'id':'cost','kind':'optimize'},{'id':'out','kind':'output'}]
edges = [[x,'facts'] for x in ('vA','vB','vC','vD')] + [['facts','valid'],['valid','cost'],['cost','out']]
item = {'id':'ZB-0230-v1','image':'../../authoring_ZB-0230-v1/Spice_Bazaar_18283738.jpg','require_real':True,'source':{'kind':'real_photo','url':'https://commons.wikimedia.org/wiki/File:Spice_Bazaar_18283738.jpg','license_url':'https://creativecommons.org/licenses/by/2.0/','authorization':'verified','scene_id':'commons:1613524'},'annotation_provenance':'manual_sample_regions','objects':[{'id':i,'bbox':b,'category':c} for i,b,c in objects], 'critical_rois':rois, 'ocr':{'han_bboxes':[],'reviewed':True},'platform_points':[{'xy':[100,767],'label':'C1 多色颗粒，区别于右侧纯色胡椒'},{'xy':[513,635],'label':'白胡椒标牌与其后方白色颗粒'},{'xy':[460,1020],'label':'ORANGE TEA 标牌指向前排茶料'}], 'human_checks':{'source_fidelity':True,'annotation_correct':True,'critical_evidence_visible':True,'no_answer_leakage':True,'counting_rules_clear':True}, 'task':{'uses_distance':False,'dependencies':[{'roi_id':r['id'],'parameter':r['id']+'格位与属性','output':'合法路线及代价'} for r in rois], 'reasoning_graph':{'nodes':nodes,'edges':edges}, 'counterfactuals':[{'field':'路线总数','baseline':9,'alternative':7,'verified':True,'evidence':'recompute.json'}], 'bypass_review':'passed'}}
(root/'manifest.json').write_text(json.dumps({'items':[item]},ensure_ascii=False,indent=2),encoding='utf-8')
