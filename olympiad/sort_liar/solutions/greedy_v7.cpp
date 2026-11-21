// Interactive comparison sort with at most k lies and adaptive verification.
// No guarantees for all N=1000,k=30,Q=11000 (information-theoretically impossible).
#include <bits/stdc++.h>
using namespace std;

struct Solver {
    int n, k, q, used = 0, lowerBound = 0;
    vector<vector<short>> yes, no;
    mt19937_64 rng;


    Solver(int n_, int k_, int q_)
        : n(n_), k(k_), q(q_),
          yes(n_ + 1, vector<short>(n_ + 1, 0)),
          no(n_ + 1, vector<short>(n_ + 1, 0)),
          rng(([] { const char *env = std::getenv("SORT_LIAR_SEED"); return env ? std::strtoull(env, nullptr, 10) : (unsigned long long)chrono::steady_clock::now().time_since_epoch().count(); }())) {
    }

    int margin(int x, int y) const {
        return int(yes[x][y]) - int(no[x][y]);
    }

    bool ask(int x, int y) {
        // A too-small Q cannot provide enough information to reconstruct
        // an arbitrary permutation. Never violate the interactive protocol.
        if (used >= q) {
            if (margin(x, y) != 0) return margin(x, y) > 0;
            return x < y;
        }
        ++used;
        cout << "? " << x << ' ' << y << endl;
        string s;
        if (!(cin >> s) || s == "-1") exit(0);
        bool ans = s == "YES";
        int prevMin = min(yes[x][y], no[x][y]);
        if (ans) {
            ++yes[x][y];
            ++no[y][x];
        } else {
            ++no[x][y];
            ++yes[y][x];
        }
        lowerBound += min(yes[x][y],no[x][y]) - prevMin;
        return ans;
    }

    vector<int> merge_sort(const vector<int>& v, int l, int r) {
        if (l == r) return {v[l]};
        int m = (l + r) / 2;
        vector<int> a = merge_sort(v, l, m);
        vector<int> b = merge_sort(v, m + 1, r);
        vector<int> res;
        res.reserve(r - l + 1);
        int i = 0, j = 0;
        while (i < (int)a.size() && j < (int)b.size()) {
            if (ask(a[i], b[j])) res.push_back(a[i++]);
            else res.push_back(b[j++]);
        }
        while (i < (int)a.size()) res.push_back(a[i++]);
        while (j < (int)b.size()) res.push_back(b[j++]);
        return res;
    }

    bool verify(int x, int y) {
        ask(x, y);
        if (margin(x, y) == 0 && used < q) ask(x, y);
        return margin(x, y) >= 0;
    }

    // A wrong comparison during merging typically displaces one element.
    // Repair an observed inversion with an exponential-size move (binary search).
    void repair(vector<int>& a, int pos) {
        int m = (int)a.size();
        if (pos < 0 || pos + 1 >= m) return;
        int x = a[pos], y = a[pos + 1];
        bool shift_x = false, shift_y = false;
        if (pos + 2 < m && used < q)
            shift_x = !ask(x, a[pos + 2]);
        if (pos > 0 && used < q)
            shift_y = !ask(a[pos - 1], y);

        if (shift_x && !shift_y) {
            int lo = pos + 1, hi = m;
            while (lo < hi && used < q) {
                int mid = lo + (hi - lo) / 2;
                if (ask(x, a[mid])) hi = mid;
                else lo = mid + 1;
            }
            if (lo > pos + 1)
                rotate(a.begin() + pos, a.begin() + pos + 1,
                       a.begin() + lo);
            else
                swap(a[pos], a[pos + 1]);
        } else if (shift_y && !shift_x) {
            int lo = 0, hi = pos + 1;
            while (lo < hi && used < q) {
                int mid = lo + (hi - lo) / 2;
                if (ask(y, a[mid])) hi = mid;
                else lo = mid + 1;
            }
            rotate(a.begin() + lo, a.begin() + pos + 1,
                   a.begin() + pos + 2);
        } else {
            swap(a[pos], a[pos + 1]);
        }
    }

    bool majority3(int x, int y) {
        int votes=0;
        for (int j=0;j<3 && used<q;++j) votes += ask(x,y)?1:-1;
        return votes>0;
    }

    void audit_gaps(vector<int>& a, int reserve) {
        if (int(a.size()) < 3) return;
        int lg=32-__builtin_clz((unsigned)n);
        int iterations=0;
        // First use unqueried pairs to maximize coverage; then strengthen
        // direct evidence obtained earlier in the merge sort.
        for (int phase=0;phase<4;++phase) {
            vector<int> indices(n-2);
            iota(indices.begin(), indices.end(), 0);
            shuffle(indices.begin(), indices.end(), rng);
            int checks=0;
            for (int i : indices) {
                if (used + reserve >= q) break;
                int x=a[i], y=a[i+1], z=a[i+2];
                int m = margin(x,z);
                if (phase==0 && m >= 0) continue;
                if (phase==1 && m != 0) continue;
                if (phase==2 && m != 1) continue;
                if (phase==3 && m > 1) continue;
                ++checks;
                if (m >= 0 && ask(x,z)) continue;
                if (used + reserve+3*lg+15 >= q) break;
                if (majority3(x,z)) continue;
                // Before changing a candidate permutation, demand a proof
                // that x >= z is true despite up to k adversarial lies.
                bool proof = margin(x,z) < -(k-lowerBound);
                while (!proof && used + reserve + 50 < q) {
                    bool v = ask(x,z);
                    if (v) break; // Any positive vote makes the alarm uncertain.
                    proof = margin(x,z) < -(k-lowerBound);
                }
                if (!proof) continue;
                bool xy = majority3(x,y);
                bool yz = majority3(y,z);
                if (used + reserve+3*lg+15 >= q) break;
                int moving;
                if (!xy) moving=0;
                else if (!yz) moving=2;
                else continue;
                int v=(moving==0? x:z);
                int old=(moving==0?i:i+2);
                a.erase(a.begin()+old);
                int lo=(moving==0?i:0),hi=(moving==0?n-1:i+2);
                while (lo < hi && used+reserve+6 < q) {
                    int mid=lo+(hi-lo)/2;
                    bool below=majority3(v,a[mid]);
                    if (below)hi=mid;
                    else lo=mid+1;
                }
                a.insert(a.begin()+lo,v);
                ++iterations;
                if (iterations >= 4*k+20) return;
            }
            if (used + reserve >= q) break;
        }
    }

    void audit_adjacent(vector<int>& a, int reserve) {
        if(n<2)return;
        vector<int> idx(n-1);
        iota(idx.begin(),idx.end(),0);
        shuffle(idx.begin(),idx.end(),rng);
        int lg=32-__builtin_clz((unsigned)n);
        for(int phase=0;phase<3 && used+reserve<q;++phase) {
            for(int j : idx){
                if(used+reserve+lg+10>=q)break;
                int x=a[j], y=a[j+1];
                int m=margin(x,y);
                if(phase==0 && m!=2)continue;
                if(phase==1 && m!=1)continue;
                if(phase==2 && m<=2)continue;
                bool ans=ask(x,y);
                if(ans)continue;
                int repeat=0;
                while(used+reserve+lg+6<q && margin(x,y)>=0 && repeat<5){
                    ask(x,y);++repeat;
                }
                if(margin(x,y)<0 && used+reserve+lg+5<q){
                    repair(a,j);
                    for(int step=0,loc=max(0,j-3);step<6 && loc+1<n && used+reserve+lg+5<q;++step,++loc){
                        if(margin(a[loc],a[loc+1])<1 && !verify(a[loc],a[loc+1])){
                            repair(a,loc);
                        }
                    }
                }
            }
        }
    }
    bool certify(int x,int y,int reserve) {
        while(yes[x][y] <= k && no[x][y] <= k && used + reserve < q)
            ask(x,y);
        if(yes[x][y]>k)return true;
        if(no[x][y]>k)return false;
        return margin(x,y)>=0;
    }

    bool guarded_lt(int x,int y) {
        int votes=0;
        for(int t=0;t<5 && used<q;++t)votes+=ask(x,y)?1:-1;
        return votes>0;
    }

    void certify_extremes(vector<int>& a) {
        if(n<25 || k<=2 || used + 5*k + 100 >= q) return;
        const int firstWindow = 1, lastWindow = 3;
        for(int side=0;side<2;++side){
            int window = side ? min(lastWindow,n-1) : min(firstWindow,n-1);
            for(int step=0; step<window; ++step){
                int i = side ? (n-2-step) : step;
                for(int repeat=0;repeat<7;++repeat){
                    if (used + 2*k + 90 >= q) return;
                    int x=a[i], y=a[i+1];
                    bool ok=certify(x,y,75);
                    if(ok || used+70>=q)break;
                    int v=side? y : x;
                    int from=side? i+1 : i;
                    a.erase(a.begin()+from);
                    int lo=0,hi=n-1;
                    while(lo<hi && used+35<q) {
                        int mid=lo+(hi-lo)/2;
                        if(guarded_lt(v,a[mid]))hi=mid;
                        else lo=mid+1;
                    }
                    a.insert(a.begin()+lo,v);
                }
            }
        }
    }

    bool mathematically_certified(const vector<int>&a) const {
        int remaining=k-lowerBound;
        if(remaining<0)return false;
        for(int i=0;i+1<n;++i)
            if(margin(a[i],a[i+1])<=remaining)return false;
        return true;
    }
    int global_lb(vector<vector<uint8_t>>* usedEdges=nullptr) const {
        if(usedEdges)usedEdges->assign(n+1,vector<uint8_t>(n+1,0));
        struct E {int u, v, cap;};
        vector<E> e;
        vector<vector<int>> outgoing(n+1);
        // Each minority answer has already been counted in lowerBound.
        // Majority answers produce a weighted directed comparison graph.
        for(int u=1;u<=n;++u) for(int v=u+1;v<=n;++v){
            int diff=margin(u,v);
            if(diff==0) continue;
            if(diff<0){int t=u;u=v;v=t;}
            int idx=(int)e.size();
            e.push_back({u,v,abs(diff)});
            outgoing[u].push_back(idx);
            if(diff<0){int t=u;u=v;v=t;}
        }
        int result=lowerBound;
        vector<int> color(n+1),par(n+1);
        for(int iter=0;iter<=k-lowerBound;++iter) {
            fill(color.begin(),color.end(),0);
            fill(par.begin(),par.end(),-1);
            vector<int> cycle;
            function<bool(int)> dfs=[&](int u){
                color[u]=1;
                for(int idx:outgoing[u]){
                    const auto &edge=e[idx];
                    if(edge.cap<=0)continue;
                    int v=edge.v;
                    if(color[v]==0){
                        par[v]=idx;
                        if(dfs(v))return true;
                    } else if(color[v]==1){
                        cycle.push_back(idx);
                        int z=u;
                        while(z!=v){
                            int px=par[z];
                            if(px<0)break;
                            cycle.push_back(px);
                            z=e[px].u;
                        }
                        return z==v;
                    }
                }
                color[u]=2;
                return false;
            };
            bool found=false;
            for(int u=1;u<=n&&!found;++u)
                if(color[u]==0 && dfs(u))found=true;
            if(!found)break;
            int flow=INT_MAX;
            for(int idx:cycle) flow=min(flow,e[idx].cap);
            if(flow==INT_MAX)break;
            result+=flow;
            if(result>k)break;
            for(int idx:cycle){
                e[idx].cap-=flow;
                if(usedEdges)(*usedEdges)[e[idx].u][e[idx].v]+=flow;
            }
        }
        return result;
    }
    bool graph_certified(const vector<int> &a) const {
        vector<vector<uint8_t>> contributions;
        int bound=global_lb(&contributions);
        if(bound>k)return false;
        for(int i=0;i+1<n;++i){
            int x=a[i],y=a[i+1];
            int m=margin(x,y);
            if(m<=0)return false;
            // Cycles that used x->y cannot be counted AGAIN to prove x<y.
            int independentBound=bound-contributions[x][y];
            if(m <= k-independentBound)return false;
        }
        return true;
    }
    vector<int> solve() {
        vector<int> start(n);
        iota(start.begin(), start.end(), 1);
        shuffle(start.begin(), start.end(), rng);
        vector<int> a = merge_sort(start, 0, n - 1);
        vector<int> initialOrder = a;
        int sortUsed = used;
        if (k == 0 || used == q) return a;

        int lg = 32 - __builtin_clz((unsigned)n);
        int h = 32 - __builtin_clz((unsigned)(n - 1));
        int worst_sort = n * h - (1 << h) + 1;

        // A signed vote margin >= k+1 certifies the pair against ANY
        // sequence of at most k lies (even an adaptive adversary).
        bool can_certify =
            1LL * worst_sort + 1LL * k * (n - 1)
            + 1LL * k * (lg + 12) + n / 5 <= q;
        bool use_skip_audit = !can_certify && k >= 3 && n >= 250 &&
            (q - worst_sort) >= 2 * (n - 1) - 150;
        int target = can_certify ? k + 1 : ((k <= 2) ? k + 1 : (use_skip_audit ? 2 : 2));
        int confidence = 2;
        int fixesTotal=0, firstRepairTime=INT_MAX;

        for (int round = 0;
             round < max(8, 4 * k + 2 * target + 20) && used < q;
             ++round) {
            if(round<=2 && graph_certified(a)) return a;
            int fixes = 0, checked = 0;
            for (int i = 0; i + 1 < n && used < q; ++i) {
                int x = a[i], y = a[i + 1];
                if (can_certify ? (margin(x, y) > k-lowerBound) :
                                 (margin(x, y) >= confidence)) continue;
                ++checked;
                if (!verify(x, y)) {
                    ++fixes;++fixesTotal;
                    firstRepairTime = min(firstRepairTime, used);
                    if (used + lg + 2 >= q) break;
                    repair(a, i);
                    i = max(-1, i - 3);
                    if (fixes >= max(20, 4 * k + 20)) break;
                }
            }
            if(fixes == 0 && graph_certified(a)) return a;
            if (fixes == 0 && checked == 0) {
                if (can_certify || confidence >= target) break;
                if (!can_certify && used + n > q) break;
                ++confidence;
            }
        }

        // A few very late repairs may be an adaptive attempt to drag a
        // previously sorted element hundreds of positions away. In that case
        // prefer the original merge result and validate it independently.
        if (use_skip_audit && n >= 900 && k >= 8 &&
            fixesTotal > 0 && fixesTotal <= k/2 &&
            firstRepairTime - sortUsed > n/4 &&
            lowerBound >= fixesTotal && lowerBound <= fixesTotal + 5) {
            vector<int> oldpos(n+1);
            for (int j=0;j<n;++j) oldpos[initialOrder[j]]=j;
            int displacement=0;
            for (int j=0;j<n;++j)
                displacement=max(displacement, abs(oldpos[a[j]]-j));
            if (displacement >= n/4) a.swap(initialOrder);
        }
        // A compact burst of inversions on already-confirmed adjacent pairs
        // can indicate that the jury spent its lie budget during verification.
        // In that case, the original version-2 rescanning stage is better
        // than the new skip audit.
        if (use_skip_audit && n >= 900 && k >= 8 &&
            fixesTotal >= 5 && fixesTotal <= k &&
            lowerBound >= fixesTotal - 1 &&
            used + n + 20 < q) use_skip_audit = false;
        if (mathematically_certified(a) || graph_certified(a)) return a;
        certify_extremes(a);
        if (mathematically_certified(a)) return a;
        if (use_skip_audit && lowerBound == 0 && fixesTotal == 0)
            return a;
        if (use_skip_audit && used < q) {
            int spare = q-used;
            audit_gaps(a, max(75, spare / 5));
            audit_adjacent(a, max(50, 2*k + 10));
            // One final pass of the ordinary verification/correction on newly
            // created adjacencies.
            for (int i=0; i+1<n && used + 16 < q; ++i) {
                if (margin(a[i], a[i+1]) >= 1) continue;
                if (!verify(a[i],a[i+1])) {
                    repair(a,i);
                    i=max(-1,i-3);
                }
            }
        }
        bool certified = true;
        for (int i = 0; i + 1 < n; ++i) {
            if (margin(a[i], a[i + 1]) < k + 1) {
                certified = false;
                break;
            }
        }
        if (certified || used >= q || use_skip_audit) return a;

        // When there is enough spare budget, prove as many randomly chosen
        // adjacent pairs as possible, rather than checking all pairs weakly.
        if (k >= 3 &&
            100LL * (q - used) > 30LL * (k - 1) * (n - 1)) {
            vector<pair<int, int>> edges;
            for (int i = 0; i + 1 < n; ++i)
                edges.emplace_back(a[i], a[i + 1]);
            shuffle(edges.begin(), edges.end(), rng);

            for (auto [x, y] : edges) {
                if (used + lg + 10 >= q) break;
                int pos = (int)(find(a.begin(), a.end(), x) - a.begin());
                if (pos + 1 >= n || a[pos + 1] != y) continue;

                while (margin(x, y) < k + 1 && used + lg + 10 < q) {
                    bool ans = ask(x, y);
                    if (!ans && margin(x, y) <= 0) {
                        repair(a, pos);
                        int j = max(0, pos - 2);
                        int end = min(n - 1, pos + 4);
                        while (j < end && used + lg + 10 < q) {
                            if (margin(a[j], a[j + 1]) < 2 &&
                                !verify(a[j], a[j + 1])) {
                                repair(a, j);
                                j = max(0, j - 2);
                            }
                            ++j;
                        }
                        break;
                    }
                }
            }
            return a;
        }

        // For large n, one extra probe on many pairs gives better coverage
        // than fully certifying only a few pairs.
        vector<pair<int, int>> edges;
        for (int i = 0; i + 1 < n; ++i)
            if (margin(a[i], a[i + 1]) == 2)
                edges.emplace_back(a[i], a[i + 1]);
        shuffle(edges.begin(), edges.end(), rng);

        for (auto [x, y] : edges) {
            if (used + lg + 5 >= q) break;
            int pos = (int)(find(a.begin(), a.end(), x) - a.begin());
            if (pos + 1 >= n || a[pos + 1] != y) continue;
            if (margin(x, y) > 2) continue;

            bool ans = ask(x, y);
            if (ans) continue;
            while (margin(x, y) > 0 && used + lg + 5 < q)
                ask(x, y);
            if (margin(x, y) == 0 && used + lg + 5 < q)
                ask(x, y);

            if (margin(x, y) < 0) {
                repair(a, pos);
                int j = max(0, pos - 2);
                while (j + 1 < n && used + lg + 5 < q) {
                    if (margin(a[j], a[j + 1]) < 2 &&
                        !verify(a[j], a[j + 1])) {
                        repair(a, j);
                        j = max(0, j - 2);
                    }
                    ++j;
                }
            }
        }
        return a;
    }
};

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    int n, k, q;
    if (!(cin >> n >> k >> q)) return 0;
    Solver solver(n, k, q);
    vector<int> order = solver.solve();
    vector<int> answer(n + 1);
    for (int i = 0; i < n; ++i) answer[order[i]] = i + 1;
    cout << '!';
    for (int i = 1; i <= n; ++i) cout << ' ' << answer[i];
    cout << endl;
}
