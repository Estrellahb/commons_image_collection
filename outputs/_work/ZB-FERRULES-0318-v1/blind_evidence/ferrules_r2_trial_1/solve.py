import itertools
colors={'A1':'B','A2':'R','A3':'RY','B1':'Y','B2':'K','B3':'W','B4':'W','C2':'R','C3':'BG'}
y={'A1':(145+894)/2,'A2':(894+1530)/2,'A3':(1530+2224)/2,'B1':(130+876)/2,'B2':(876+1894)/2,'B3':(1894+2228)/2,'B4':(2228+2944)/2,'C2':(494+1555)/2,'C3':(1555+2944)/2}
AB=[(a,b) for a in colors if a[0]=='A' for b in colors if b[0]=='B' if abs(y[a]-y[b])<=1000]
BC=[(b,c) for b in colors if b[0]=='B' for c in colors if c[0]=='C' if abs(y[b]-y[c])<=1650]
relays=[]
for a,b in AB:
 for b2,c in BC:
  if b!=b2:continue
  for cs in itertools.product(colors[a],colors[b],colors[c]):
   if len(set(cs))==3:
    code='/'.join(i+co for i,co in zip([a,b,c],cs))
    relays.append((code,(a,b,c),cs))
plans=[]
for p,q in itertools.combinations(relays,2):
 if set(p[1])&set(q[1]):continue
 if sum(colors[r[1][1]]=='W' for r in [p,q])!=1:continue
 plans.append((p,q))
print('y',y)
print('distances',abs(y['A2']-y['B3']),abs(y['B4']-y['C2']))
print('AB',AB,'BC',BC)
print('relays',len(relays),'plans',len(plans))
for costs in [dict(zip('BGKRWY',[3,5,1,4,2,6])),dict(zip('BGKRWY',[7,1,5,2,4,3]))]:
 vals=[]
 for p,q in plans:
  cost=sum(int(i[1:]) for i in p[1]+q[1])+sum(costs[c] for c in p[2]+q[2])
  vals.append((cost,';'.join(sorted([p[0],q[0]]))))
 m=min(v[0] for v in vals);opt=sorted(v[1] for v in vals if v[0]==m)
 print(m,len(opt),opt[0])
