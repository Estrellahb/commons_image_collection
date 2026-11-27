from itertools import product, combinations
attrs={
'A':[(1,1),(1,1),(1,1),(1,1),(0,1)],
'B':[(1,1),(1,1),(1,1),(0,1),(1,1),(1,1)],
'C':[(1,1),(1,1),(1,1),(0,0),(1,1)],
'D':[(0,1),(1,1),(1,1),(1,1),(1,1),(0,1)]}
cols=list(attrs)
def fh(j,i): return attrs[cols[j]][i-1]
def edge(j,i,k): return abs(i-k)<=2 and fh(j,i)[0]+fh(j+1,k)[0]>=1
for c in cols: print(c, (len(attrs[c]),sum(x[0] for x in attrs[c]),sum(x[1] for x in attrs[c])))
print('edges', [sum(edge(j,i,k) for i in range(1,len(attrs[cols[j]])+1) for k in range(1,len(attrs[cols[j+1]])+1)) for j in range(3)])
routes=[]
for r in product(*[range(1,len(attrs[c])+1) for c in cols]):
 if sum(fh(j,i)[0] for j,i in enumerate(r))!=3: continue
 if sum(fh(j,i)[1] for j,i in enumerate(r))<3: continue
 if not all(edge(j,r[j],r[j+1]) for j in range(3)): continue
 routes.append(r)
def hs(r): return sum(fh(j,i)[1] for j,i in enumerate(r))
plans=[]
for p,q in combinations(routes,2):
 if not all(x<y for x,y in zip(p,q)): continue
 if hs(p)+hs(q)!=7: continue
 plans.append((p,q))
print('routes',len(routes),'by H', {h:sum(hs(r)==h for r in routes) for h in (3,4)})
print('plans',len(plans))
def g(r, mode):
 a,b,c,d=r
 g0=(a-b)**2+(b-c)**2+(c-d)**2
 if mode==0: return g0
 return g0+ (4*b if hs(r)==3 else 3*(6-d))
for mode in (0,1):
 costs=[(max(g(p,mode),g(q,mode)),g(p,mode)+g(q,mode)) for p,q in plans]
 best=min(costs)
 opts=[p+q for (p,q),cost in zip(plans,costs) if cost==best]
 representative=min(opts)
 print('mode',mode, (*best,len(opts),representative))
 print('all_optima',opts)
 print('representative route costs',g(representative[:4],mode),g(representative[4:],mode))
