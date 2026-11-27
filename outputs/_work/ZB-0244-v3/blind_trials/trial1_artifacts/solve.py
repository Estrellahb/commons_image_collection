from itertools import product, combinations
attrs={
'A':[(1,1),(1,1),(1,1),(1,1),(0,1)],
'B':[(1,1),(1,1),(1,1),(1,1),(1,1),(1,1)],
'C':[(1,1),(1,1),(1,1),(0,0),(1,1)],
'D':[(0,1),(1,1),(1,1),(1,1),(1,1),(0,1)],
}
cols=list(attrs)
def edge(col1,i,col2,j):
 return abs(i-j)<=2 and attrs[col1][i-1][0]+attrs[col2][j-1][0]>=1
edges=[]
for first,second in zip(cols,cols[1:]):
 pairs=[(i,j) for i in range(1,len(attrs[first])+1) for j in range(1,len(attrs[second])+1) if edge(first,i,second,j)]
 edges.append(pairs)
routes=[]
for route in product(*(range(1,len(attrs[col])+1) for col in cols)):
 states=[attrs[col][i-1] for col,i in zip(cols,route)]
 if sum(f for f,h in states)!=3 or sum(h for f,h in states)<3:
  continue
 if all((i,j) in segment for (i,j),segment in zip(zip(route,route[1:]),edges)):
  routes.append((route,sum(h for f,h in states)))
plans=[]
for (p,hp),(q,hq) in combinations(routes,2):
 if all(i<j for i,j in zip(p,q)) and hp+hq==7:
  plans.append(((p,hp),(q,hq)))
def cost(route,h,mode):
 a,b,c,d=route
 base=(a-b)**2+(b-c)**2+(c-d)**2
 if mode==0:
  return base
 return base+(4*b if h==3 else 3*(6-d))
print('Column summaries',[(col,len(v),sum(f for f,h in v),sum(h for f,h in v)) for col,v in attrs.items()])
print('Edges',[len(e) for e in edges])
print('Single routes',len(routes))
print('Double plans',len(plans))
for mode in (0,1):
 scored=[]
 for (p,hp),(q,hq) in plans:
  cp,cq=cost(p,hp,mode),cost(q,hq,mode)
  scored.append(((max(cp,cq),cp+cq),p+q,(cp,cq),(hp,hq)))
 best=min(s[0] for s in scored)
 winners=sorted(s for s in scored if s[0]==best)
 print('Mode',mode,'best',best,'ties',len(winners),'representative',winners[0])
 print('All winning plans',winners)
