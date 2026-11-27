from itertools import product, combinations
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
y={'A1':520.5,'A2':1210,'A3':1882,'B1':506.5,'B2':1380,'B3':2063,'B4':2584.5,'C2':1026.5,'C3':2243}
As=['A1','A2','A3'];Bs=['B1','B2','B3','B4'];Cs=['C2','C3']
ab={(a,b) for a,b in product(As,Bs) if abs(y[a]-y[b])<=1000}
bc={(b,c) for b,c in product(Bs,Cs) if abs(y[b]-y[c])<=1600}
relays=[]
for a,b,c in product(As,Bs,Cs):
 if (a,b) not in ab or (b,c) not in bc:continue
 for ca,cb,cc in product(colors[a],colors[b],colors[c]):
  if len({ca,cb,cc})==3:
   relays.append(((a,b,c),(ca,cb,cc),'/'.join((a+ca,b+cb,c+cc))))
plans=[]
for r1,r2 in combinations(relays,2):
 ids=r1[0]+r2[0]
 if len(set(ids))!=6:continue
 if sum(colors[b]=='W' for b in (r1[0][1],r2[0][1]))!=1:continue
 code=';'.join(sorted((r1[2],r2[2])))
 plans.append((ids,r1[1]+r2[1],code))
print('AB',sorted(ab),'BC',sorted(bc))
print('edges',[len(ab),len(bc)],'relays',len(relays),'plans',len(plans))
for costs in ({'B':3,'G':5,'K':1,'R':4,'W':2,'Y':6},{'B':7,'G':1,'K':5,'R':2,'W':4,'Y':3}):
 scored=[(sum(int(x[1:]) for x in ids)+sum(costs[c] for c in cs),code) for ids,cs,code in plans]
 best=min(x[0] for x in scored)
 winners=sorted(code for score,code in scored if score==best)
 print(best,len(winners),winners[0])
 print('all winners',winners)
print('distances',abs(y['A2']-y['B3']),abs(y['B4']-y['C2']))
