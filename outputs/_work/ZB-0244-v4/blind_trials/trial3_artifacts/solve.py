from itertools import product, combinations
import json
columns = {
    'A': [(1,1),(1,1),(1,1),(1,1),(0,1)],
    'B': [(1,1),(1,1),(1,1),(0,1),(1,1),(1,1)],
    'C': [(1,1),(1,1),(1,1),(0,0),(1,1)],
    'D': [(0,1),(1,1),(1,1),(1,1),(1,1),(0,1)],
}
values = list(columns.values())
edges = []
for left, right in zip(values, values[1:]):
    edges.append([(i,j) for i,x in enumerate(left,1) for j,y in enumerate(right,1) if abs(i-j)<=2 and x[0]+y[0]>=1])
routes = []
for route in product(*[range(1,len(column)+1) for column in values]):
    attributes = [column[index-1] for column,index in zip(values,route)]
    if sum(f for f,h in attributes)!=3 or sum(h for f,h in attributes)<3:
        continue
    if not all((a,b) in edge for (a,b),edge in zip(zip(route,route[1:]),edges)):
        continue
    g0 = sum((a-b)**2 for a,b in zip(route,route[1:]))
    h_sum = sum(h for f,h in attributes)
    g1 = g0 + (4*route[1] if h_sum==3 else 3*(6-route[3]))
    routes.append((route,h_sum,g0,g1))
schemes=[]
for first,second in combinations(routes,2):
    p,q=sorted((first,second), key=lambda r:r[0][0])
    if all(a<b for a,b in zip(p[0],q[0])) and p[1]+q[1]==7:
        schemes.append((p,q))
output = {'columns':{name:(len(column),sum(f for f,h in column),sum(h for f,h in column)) for name,column in columns.items()}, 'edges':list(map(len,edges)), 'routes':len(routes),'schemes':len(schemes)}
for mode in (0,1):
    index=2+mode
    best=min((max(p[index],q[index]),p[index]+q[index]) for p,q in schemes)
    winners=[(p,q) for p,q in schemes if (max(p[index],q[index]),p[index]+q[index])==best]
    representative=min(winners,key=lambda s:s[0][0]+s[1][0])
    output['mode'+str(mode)]=[best[0],best[1],len(winners),representative[0][0]+representative[1][0]]
    output['winners'+str(mode)]=winners
print(json.dumps(output,indent=2))
