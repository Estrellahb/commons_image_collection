from itertools import product,combinations
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
y={'A1':520,'A2':1208,'A3':1882,'B1':510,'B2':1398,'B3':2078,'B4':2590,'C2':1034,'C3':2245}
A=['A1','A2','A3']; B=['B1','B2','B3','B4']; C=['C2','C3']
ab=[(a,b) for a,b in product(A,B) if abs(y[a]-y[b])<=1000]
bc=[(b,c) for b,c in product(B,C) if abs(y[b]-y[c])<=1650]
relays=[]
for a,b,c in product(A,B,C):
 if (a,b) not in ab or (b,c) not in bc:continue
 for ca,cb,cc in product(colors[a],colors[b],colors[c]):
  if len({ca,cb,cc})!=3:continue
  ids=(a,b,c);cs=(ca,cb,cc)
  relays.append((ids,cs,'/'.join(i+col for i,col in zip(ids,cs))))
plans=[]
for r,s in combinations(relays,2):
 if len(set(r[0]+s[0]))!=6:continue
 if sum(colors[t[0][1]]=='W' for t in (r,s))!=1:continue
 plans.append((r,s))
print('ab',ab,'bc',bc)
print('relays',len(relays),'plans',len(plans))
for fees in ({'B':3,'G':5,'K':1,'R':4,'W':2,'Y':6},{'B':7,'G':1,'K':5,'R':2,'W':4,'Y':3}):
 vals=[]
 for r,s in plans:
  cost=sum(int(i[1:]) for i in r[0]+s[0])+sum(fees[c] for c in r[1]+s[1])
  code=';'.join(sorted([r[2],s[2]]))
  vals.append((cost,code))
 minimum=min(x[0] for x in vals)
 best=sorted(code for cost,code in vals if cost==minimum)
 print(minimum,len(best),best[0])
