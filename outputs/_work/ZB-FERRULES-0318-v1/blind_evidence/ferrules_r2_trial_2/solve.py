from itertools import product,combinations
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
boundaries={'A':[148,891,1528,2237,2541,2948],'B':[133,875,1895,2240,2949],'C':[124,507,1555,2949]}
y={f'{col}{i+1}':(v[i]+v[i+1])/2 for col,v in boundaries.items() for i in range(len(v)-1)}
A=['A1','A2','A3'];B=['B1','B2','B3','B4'];C=['C2','C3']
ab=[(a,b) for a,b in product(A,B) if abs(y[a]-y[b])<=1000]
bc=[(b,c) for b,c in product(B,C) if abs(y[b]-y[c])<=1650]
relays=[]
for a,b,c in product(A,B,C):
 if (a,b) not in ab or (b,c) not in bc:continue
 for ca,cb,cc in product(colors[a],colors[b],colors[c]):
  if len({ca,cb,cc})==3:
   relays.append(((a,b,c),(ca,cb,cc),'/'.join([a+ca,b+cb,c+cc])))
plans=[]
for p,q in combinations(relays,2):
 if len(set(p[0]+q[0]))!=6:continue
 if sum(colors[t[0][1]]=='W' for t in (p,q))!=1:continue
 plans.append((p,q))
print('y',y)
print('distances',[abs(y['A2']-y['B3']),abs(y['B4']-y['C2'])])
print('AB',ab)
print('BC',bc)
print('edges',len(ab),len(bc),'relays',len(relays),'plans',len(plans))
for mode,fees in enumerate([dict(zip('BGKRWY',[3,5,1,4,2,6])),dict(zip('BGKRWY',[7,1,5,2,4,3]))]):
 scores=[]
 for p,q in plans:
  score=sum(int(n[1:]) for t in (p,q) for n in t[0])+sum(fees[c] for t in (p,q) for c in t[1])
  code=';'.join(sorted([p[2],q[2]]))
  scores.append((score,code))
 best=min(s[0] for s in scores)
 optimal=sorted(code for score,code in scores if score==best)
 print('mode',mode,[best,len(optimal),optimal[0]])
 print('all optimal',optimal)
