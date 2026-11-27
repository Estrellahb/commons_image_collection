from itertools import product,combinations
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
y={'A1':521.5,'A2':1211.5,'A3':1888.5,'B1':506,'B2':1384,'B3':2075,'B4':2598,'C2':1021,'C3':2243}
AB=[(a,b) for a in ['A1','A2','A3'] for b in ['B1','B2','B3','B4'] if abs(y[a]-y[b])<=1000]
BC=[(b,c) for b in ['B1','B2','B3','B4'] for c in ['C2','C3'] if abs(y[b]-y[c])<=1600]
relays=[]
for a,b,c in product(['A1','A2','A3'],['B1','B2','B3','B4'],['C2','C3']):
 if (a,b) not in AB or (b,c) not in BC: continue
 for cols in product(colors[a],colors[b],colors[c]):
  if len(set(cols))==3:relays.append((a,b,c,*cols))
plans=[]
for r,s in combinations(relays,2):
 if len(set(r[:3]+s[:3]))<6:continue
 if sum(colors[t[1]]=='W' for t in [r,s])!=1:continue
 plans.append((r,s))
def encode(plan):return ';'.join(sorted('/'.join(i+c for i,c in zip(t[:3],t[3:])) for t in plan))
print('AB',AB,'BC',BC)
print('relays',len(relays),'plans',len(plans))
for fees in [dict(zip('BGKRWY',[3,5,1,4,2,6])),dict(zip('BGKRWY',[7,1,5,2,4,3]))]:
 costs=[sum(int(i[1:]) for t in p for i in t[:3])+sum(fees[c] for t in p for c in t[3:]) for p in plans]
 m=min(costs); opts=[encode(p) for p,c in zip(plans,costs) if c==m]
 print(m,len(opts),min(opts))
 print(sorted(opts))
