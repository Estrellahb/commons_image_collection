from itertools import product, combinations
columns = {
 'A': [(1,1),(1,1),(1,1),(1,1),(0,1)],
 'B': [(1,1),(1,1),(1,1),(0,1),(1,1),(1,1)],
 'C': [(1,1),(1,1),(1,1),(1,0),(1,1)],
 'D': [(0,1),(1,1),(1,1),(1,1),(1,1),(0,1)],
}
for label, rows in columns.items():
 print(label, 'table', list(enumerate(rows,1)), 'counts', (len(rows), sum(x[0] for x in rows), sum(x[1] for x in rows)))
cols=list(columns.values())
edge_counts=[]
for left,right in zip(cols,cols[1:]):
 edges=[(i,j) for i,p in enumerate(left,1) for j,q in enumerate(right,1) if abs(i-j)<=2 and p[0]+q[0]>=1]
 edge_counts.append(len(edges))
print('edges',edge_counts)
routes=[]
for route in product(*(range(1,len(col)+1) for col in cols)):
 attrs=[col[i-1] for col,i in zip(cols,route)]
 if sum(x[0] for x in attrs)!=3 or sum(x[1] for x in attrs)<3:
  continue
 if any(abs(i-j)>2 or p[0]+q[0]<1 for i,j,p,q in zip(route,route[1:],attrs,attrs[1:])):
  continue
 h=sum(x[1] for x in attrs)
 g0=sum((i-j)**2 for i,j in zip(route,route[1:]))
 g1=g0+(4*route[1] if h==3 else 3*(6-route[3]))
 routes.append((route,h,g0,g1))
print('single',len(routes))
pairs=[]
for p,q in combinations(routes,2):
 if not all(a<b for a,b in zip(p[0],q[0])):
  continue
 if p[1]+q[1]!=7:
  continue
 pairs.append((p,q))
print('double',len(pairs))
for mode in [0,1]:
 scored=[((max(p[2+mode],q[2+mode]),p[2+mode]+q[2+mode]),p[0]+q[0],p,q) for p,q in pairs]
 best=min(x[0] for x in scored)
 tied=sorted([x for x in scored if x[0]==best])
 print('mode',mode, best, 'ties',len(tied),'representative',tied[0][1])
 for x in tied:
  print(' optimum',x)
