from itertools import product, combinations
attributes = {
 'A': [(1,1),(1,1),(1,1),(1,1),(0,1)],
 'B': [(1,1),(1,1),(1,1),(0,1),(1,1),(1,1)],
 'C': [(1,1),(1,1),(1,1),(0,0),(1,1)],
 'D': [(0,1),(1,1),(1,1),(1,1),(1,1),(0,1)],
}
columns = list(attributes.values())
def edge(k,i,j):
 return abs(i-j)<=2 and columns[k][i-1][0]+columns[k+1][j-1][0]>=1
print('Counts', [(len(col),sum(f for f,h in col),sum(h for f,h in col)) for col in columns])
print('Edges', [sum(edge(k,i,j) for i in range(1,len(columns[k])+1) for j in range(1,len(columns[k+1])+1)) for k in range(3)])
routes=[]
for r in product(*[range(1,len(col)+1) for col in columns]):
 attrs=[columns[k][v-1] for k,v in enumerate(r)]
 if sum(f==0 for f,h in attrs)!=1 or sum(h for f,h in attrs)<3: continue
 if all(edge(k,r[k],r[k+1]) for k in range(3)):
  routes.append(r)
def hsum(r):return sum(columns[k][v-1][1] for k,v in enumerate(r))
def cost(r,mode):
 a,b,c,d=r
 g0=(a-b)**2+(b-c)**2+(c-d)**2
 if mode==0:return g0
 return g0+(4*b if hsum(r)==3 else 3*(6-d))
plans=[(p,q) for p,q in combinations(routes,2) if all(i<j for i,j in zip(p,q)) and hsum(p)+hsum(q)==7]
print('Routes',len(routes),'by H', {h:sum(hsum(r)==h for r in routes) for h in (3,4)})
print('Plans',len(plans))
for mode in (0,1):
 obj=lambda p:(max(cost(p[0],mode),cost(p[1],mode)),cost(p[0],mode)+cost(p[1],mode))
 best=min(map(obj,plans))
 opts=[p for p in plans if obj(p)==best]
 rep=min(opts,key=lambda p:p[0]+p[1])
 print('Mode',mode,'best',best,'ties',len(opts),'representative',rep[0]+rep[1])
 for p in opts: print('optimal',p,'H',list(map(hsum,p)),'costs',[cost(r,mode) for r in p])
