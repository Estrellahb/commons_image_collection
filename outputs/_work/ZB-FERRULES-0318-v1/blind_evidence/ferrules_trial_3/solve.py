import itertools
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
y={'A1':519,'A2':1207,'A3':1890,'B1':504,'B2':1387,'B3':2075,'B4':2598,'C2':1025,'C3':2250}
AB=[(a,b) for a in colors if a[0]=='A' for b in colors if b[0]=='B' and abs(y[a]-y[b])<=1000]
BC=[(b,c) for b in colors if b[0]=='B' for c in colors if c[0]=='C' and abs(y[b]-y[c])<=1600]
relays=[]
for a,b in AB:
 for bb,c in BC:
  if bb!=b:continue
  for ca,cb,cc in itertools.product(colors[a],colors[b],colors[c]):
   if len({ca,cb,cc})==3:
    relays.append(((a,b,c),(ca,cb,cc),'/'.join([a+ca,b+cb,c+cc])))
plans=[]
for r,s in itertools.combinations(relays,2):
 if len(set(r[0]+s[0]))!=6:continue
 if sum(colors[z[0][1]]=='W' for z in [r,s])!=1:continue
 code=';'.join(sorted([r[2],s[2]]))
 plans.append((r,s,code))
print('AB',AB,'BC',BC)
print('relays',len(relays),'plans',len(plans))
for costs in [dict(zip('BGKRWY',[3,5,1,4,2,6])),dict(zip('BGKRWY',[7,1,5,2,4,3]))]:
 scored=[]
 for r,s,code in plans:
  cost=sum(int(i[1:]) for i in r[0]+s[0])+sum(costs[c] for c in r[1]+s[1])
  scored.append((cost,code))
 best=min(cost for cost,code in scored)
 opt=sorted(code for cost,code in scored if cost==best)
 print(best,len(opt),opt[0])
