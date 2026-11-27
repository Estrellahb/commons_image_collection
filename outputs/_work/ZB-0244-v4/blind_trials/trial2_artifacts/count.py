from itertools import product, combinations

# Each row is (F, H), ordered by thorax height in the original photo.
attrs = {
    'A': [(1,1), (1,1), (1,1), (1,1), (0,1)],
    'B': [(1,1), (1,1), (1,1), (0,1), (1,1), (1,1)],
    'C': [(1,1), (1,1), (1,1), (0,0), (1,1)],
    'D': [(0,1), (1,1), (1,1), (1,1), (1,1), (0,1)],
}
cols = list(attrs)

def edge(left_col, left, right_col, right):
    return abs(left-right) <= 2 and attrs[left_col][left-1][0] + attrs[right_col][right-1][0] >= 1

edges = []
for lc, rc in zip(cols, cols[1:]):
    pairs = [(l,r) for l in range(1,len(attrs[lc])+1) for r in range(1,len(attrs[rc])+1) if edge(lc,l,rc,r)]
    edges.append(pairs)
    print('Edges',lc+rc,len(pairs),pairs)

routes = []
for route in product(*(range(1,len(attrs[c])+1) for c in cols)):
    values = [attrs[c][n-1] for c,n in zip(cols,route)]
    if sum(f for f,h in values) != 3 or sum(h for f,h in values) < 3:
        continue
    if not all(edge(cols[i],route[i],cols[i+1],route[i+1]) for i in range(3)):
        continue
    hsum = sum(h for f,h in values)
    g0 = sum((route[i]-route[i+1])**2 for i in range(3))
    g1 = g0 + (4*route[1] if hsum == 3 else 3*(6-route[3]))
    routes.append((route, hsum, g0, g1))

plans = []
for p,q in combinations(routes,2):
    if all(x<y for x,y in zip(p[0],q[0])) and p[1]+q[1] == 7:
        plans.append((p,q))

print('Summaries',[(len(v),sum(f for f,h in v),sum(h for f,h in v)) for v in attrs.values()])
print('Routes',len(routes),'H3',sum(r[1]==3 for r in routes),'H4',sum(r[1]==4 for r in routes))
print('Plans',len(plans))
for cost_index in (2,3):
    objective = lambda plan: (max(r[cost_index] for r in plan),sum(r[cost_index] for r in plan))
    best = min(map(objective,plans))
    winners = [plan for plan in plans if objective(plan)==best]
    vectors = sorted(p[0]+q[0] for p,q in winners)
    print('Optimum',cost_index-2,best,len(winners),vectors[0])
    print('Winning plans',winners)
