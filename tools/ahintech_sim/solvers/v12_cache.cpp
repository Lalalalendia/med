#include <bits/stdc++.h>
using namespace std;

struct FastInput {
    static constexpr size_t B = 1 << 16;
    char buf[B]; size_t pos = 0, len = 0;
    inline char get() {
        if (pos == len) { len = fread(buf, 1, B, stdin); pos = 0; if (!len) return 0; }
        return buf[pos++];
    }
    int read() {
        int c; do { c = get(); } while (c && c <= ' ');
        int v = 0;
        while (c >= '0' && c <= '9') { v = v * 10 + c - '0'; c = get(); }
        return v;
    }
};

struct Action {
    int from, to, when, next;
};

struct Problem {
    int n, p, k, x, m;
    int edge2 = 0;
    vector<int> a, b, t;
    vector<vector<int>> adj;
    vector<unsigned> legal;
    vector<int> deg;

    bool can(int v, int phase) const {
        return (legal[v] >> phase) & 1u;
    }
};

// Exact dynamic programming for k=1. The active copies form one path.
// Processing candidate receivers in descending DP value allows us to
// propagate their values to all as-yet-uncovered sources at once.
vector<int> chain_dp(const Problem &g) {
    const int n = g.n, m = g.m;
    vector<unsigned char> minDelay(24 * n, 24);
    for (int u = 0; u < n; ++u) {
        for (int v : g.adj[u]) {
            unsigned mask = g.legal[v];
            while (mask) {
                int h = __builtin_ctz(mask);
                unsigned char &c = minDelay[h * n + u];
                if (g.t[v] < c) c = (unsigned char)g.t[v];
                mask &= mask - 1;
            }
        }
    }

    vector<int> dp((size_t)n * m, 1);
    vector<int> seen(n, 0);
    vector<pair<int,int>> cand;
    cand.reserve(n);
    for (int T = m - 1; T >= 0; --T) {
        int r = m - T, h = (g.x + T) % 24;
        int row = T * n;
        int remaining = 0;
        long long remainingDegrees = 0;
        for (int u = 0; u < n; ++u) {
            if (minDelay[h * n + u] != 24 && minDelay[h * n + u] < r) {
                ++remaining;
                remainingDegrees += g.deg[u];
            }
        }
        if (!remaining) continue;

        cand.clear();
        for (int v = 0; v < n; ++v) {
            if (g.t[v] < r && g.can(v, h)) {
                cand.emplace_back(dp[(T + g.t[v]) * n + v], v);
            }
        }
        sort(cand.begin(), cand.end(), [&](const auto &l, const auto &rr) {
            if (l.first != rr.first) return l.first > rr.first;
            if (g.deg[l.second] != g.deg[rr.second])
                return g.deg[l.second] > g.deg[rr.second];
            return l.second < rr.second;
        });

        const int stamp = T + 1;
        long long scanned = 0;
        for (auto [value, v] : cand) {
            for (int u : g.adj[v]) {
                if (seen[u] != stamp) {
                    seen[u] = stamp;
                    dp[row + u] = value + 1;
                    --remaining;
                    remainingDegrees -= g.deg[u];
                }
            }
            scanned += g.deg[v];
            if (!remaining) break;
            // Finish the remaining source vertices by scanning their own
            // adjacency lists when this is estimated to be cheaper.
            if (remainingDegrees * 5 <= scanned * 4) break;
        }
        if (remaining) {
            for (int u = 0; u < n; ++u) {
                if (seen[u] == stamp || minDelay[h * n + u] == 24 || minDelay[h * n + u] >= r) continue;
                int best = 1;
                for (int v : g.adj[u]) {
                    if (g.t[v] < r && g.can(v, h))
                        best = max(best, dp[(T + g.t[v]) * n + v] + 1);
                }
                dp[row + u] = best;
            }
        }
    }

    return dp;
}

vector<Action> recover_chain(const Problem &g, const vector<int> &dp) {
    const int n = g.n, m = g.m;
    vector<Action> ans;
    ans.reserve(dp[g.p]);
    ans.push_back({-1, g.p, -1, -1});
    int u = g.p, T = 0;
    while (T < m && dp[T * n + u] > 1) {
        int h = (g.x + T) % 24, target = -1;
        for (int v : g.adj[u]) {
            if (T + g.t[v] < m && g.can(v, h) &&
                dp[(T + g.t[v]) * n + v] + 1 == dp[T * n + u]) {
                target = v;
                break;
            }
        }
        if (target < 0) break; // Cannot occur for correctly computed DP.
        ans.push_back({u, target, g.x + T, -1});
        T += g.t[target];
        u = target;
    }
    return ans;
}

vector<Action> solve_one(const Problem &g) {
    return recover_chain(g, chain_dp(g));
}

static inline unsigned scramble(unsigned z) {
    z ^= z >> 16; z *= 0x7feb352du;
    z ^= z >> 15; z *= 0x846ca68bu;
    z ^= z >> 16;
    return z;
}

struct Scores {
    const Problem &g;
    int n, L, cap;
    vector<int> phaseOptions;
    vector<float> periodic;  // R[hour][vertex]
    vector<float> tail;      // R[hours remaining][vertex]
    vector<int> spine;       // longest possible single-copy chain
    vector<float> cachedF, cachedS, cachedSpeed, cachedDegree;
    float delay[24]{};

    Scores(const Problem &p) : g(p), n(p.n) {
        spine = chain_dp(g);
        cap = min(p.k, 12);
        L = min(p.m, p.edge2 > 500000 ? 10 : (p.edge2 > 200000 ? 20 : 30));
        for (int t = 0; t < 24; ++t) delay[t] = pow(0.925f, (float)t);

        phaseOptions.assign(24 * n, 0);
        for (int u = 0; u < n; ++u) {
            for (int v : g.adj[u]) {
                unsigned mask = g.legal[v];
                while (mask) {
                    int h = __builtin_ctz(mask);
                    ++phaseOptions[h * n + u];
                    mask &= mask - 1;
                }
            }
        }

        if (g.m > L) {
            periodic.assign(24 * n, 1.0f);
            vector<float> nxt(24 * n, 1.0f);
            vector<float> buf;
            buf.reserve(*max_element(g.deg.begin(), g.deg.end()));
            int rounds = g.edge2 > 500000 ? 1 : (g.edge2 > 200000 ? 2 : 3);
            for (int d = 0; d < rounds; ++d) {
                for (int h = 0; h < 24; ++h) {
                    int hrow = h * n;
                    for (int u = 0; u < n; ++u) {
                        buf.clear();
                        for (int v : g.adj[u]) {
                            if (g.can(v, h)) {
                                int nh = (h + g.t[v]) % 24;
                                buf.push_back(delay[g.t[v]] * periodic[nh * n + v]);
                            }
                        }
                        nxt[hrow + u] = 1.0f + sumBest(buf);
                    }
                }
                periodic.swap(nxt);
            }
        }

        tail.assign((size_t)(L + 1) * n, 1.0f);
        vector<float> buf;
        buf.reserve(*max_element(g.deg.begin(), g.deg.end()));
        for (int r = 1; r <= L; ++r) {
            int h = (g.x + g.m - r) % 24;
            for (int u = 0; u < n; ++u) {
                buf.clear();
                for (int v : g.adj[u]) {
                    if (g.t[v] < r && g.can(v, h))
                        buf.push_back(delay[g.t[v]] * tail[(size_t)(r - g.t[v]) * n + v]);
                }
                tail[(size_t)r * n + u] = 1.0f + sumBest(buf);
            }
        }
        const size_t cells=(size_t)g.m*n;
        cachedF.assign(cells, 0.f);
        cachedS.assign(cells, 0.f);
        cachedSpeed.resize(n);
        cachedDegree.resize(n);
        for (int v=0;v<n;++v) {
            cachedSpeed[v]=1.0f / sqrt((float)g.t[v]);
            cachedDegree[v]=log1pf((float)g.deg[v]);
        }
        for (int T=0;T<g.m;++T) {
            int r=g.m-T, h=(g.x+T)%24;
            for (int v=0;v<n;++v) {
                if (g.t[v]>=r || !g.can(v,h)) continue;
                int q=r-g.t[v];
                float future=(r<=L) ? tail[(size_t)q*n+v]-1.f
                         : periodic[((g.x+T+g.t[v])%24)*n+v]-1.f;
                if (future<0.f) future=0.f;
                cachedF[(size_t)T*n+v]=log1pf(future)*delay[g.t[v]];
                cachedS[(size_t)T*n+v]=log1pf((float)spine[(size_t)(T+g.t[v])*n+v]-1.0f);
            }
        }
    }

    float sumBest(vector<float> &buf) const {
        int cnt = (int)buf.size();
        if (!cnt) return 0.0f;
        int take = min(cnt, cap);
        if (cnt > take) {
            nth_element(buf.begin(), buf.begin() + take, buf.end(), greater<float>());
        }
        float val = 0;
        for (int j = 0; j < take; ++j) val += buf[j];
        if (cnt > take) val *= sqrt((float)cnt / take);
        return val;
    }

    float receiverScore(int v, int T, int mode, unsigned seed) const {
        const size_t key=(size_t)T*n+v;
        float f = cachedF[key];
        float survival = cachedS[key];
        float speed = cachedSpeed[v];
        float degree = cachedDegree[v];
        unsigned rnd = scramble((unsigned)v * 0x9e3779b9u ^ (unsigned)T * 0x85ebca6bu ^ seed);
        float noise = (float)(rnd & 65535) * (1.0f / 65535.0f) - 0.5f;
        if (mode == 0) return 2.6f * f + 1.1f * survival + 0.30f * speed + 0.0001f * noise;
        if (mode == 1) return 1.6f * f + 0.35f * survival + 2.2f * speed + 0.12f * degree + 0.01f * noise;
        if (mode == 2) return 1.7f * f + 1.8f * survival + 0.4f * speed + 0.35f * degree + 0.25f * noise;
        if (mode == 3) return 1.5f * f + 0.85f * speed + 0.18f * degree + 1.0f * noise;
        if (mode == 4) return 0.45f * f + 5.5f * survival + 0.35f * speed + 0.1f * noise;
        if (mode == 5) return 0.70f * f + 3.8f * speed + 0.8f * degree + 0.3f * noise;
        if (mode == 6) return 4.5f * f + 0.5f * survival + 0.3f * speed + 0.4f * noise;
        return 1.1f * f + 0.55f * survival + 0.3f * speed + 3.0f * noise;
    }
};

struct Sim {
    const Problem &g;
    const Scores &scores;
    int mode;
    unsigned seed;
    vector<int> head, freeAt, activeAt, remaining, options, incomingStamp, owner;
    vector<uint32_t> futureShadow;
    vector<int> futureStamp;
    vector<int> visitedSource, visitedTarget;
    int visitSerial = 0;
    vector<vector<int>> incoming, assigned;
    vector<Action> acts;
    vector<int> senders, targets, chosen;
    vector<pair<float,int>> ranking;
    int T = 0;
    bool sourceMode = false;
    int activeDensityQ16 = 0;
    const vector<Action> *backbone = nullptr;
    vector<vector<int>> reserved;
    vector<int> reservedIndex;
    size_t forcedIndex = 1;
    int startHour = 0;

    Sim(const Problem &g_, const Scores &scores_, int mode_, unsigned seed_,
        const vector<Action> *forced = nullptr,
        const vector<Action> *prefix = nullptr, int pivot = 0)
        : g(g_), scores(scores_), mode(mode_), seed(seed_),
          head(g.m, -1), freeAt(g.n, 0), activeAt(g.n, -1),
          remaining(g.n, 0), options(g.n, 0), incomingStamp(g.n, -1),
          owner(g.n, -1), futureShadow(g.n, 0), futureStamp(g.n, -1),
          visitedSource(g.n, 0), visitedTarget(g.n, 0),
          incoming(g.n), assigned(g.n), backbone(forced) {
        acts.push_back({-1, g.p, -1, -1});
        head[0] = 0;
        if (prefix != nullptr && pivot > 0) {
            startHour = min(pivot, g.m);
            for (size_t j = 1; j < prefix->size(); ++j) {
                const Action &q = (*prefix)[j];
                if (q.when - g.x >= startHour) break;
                const int finish = q.when - g.x + g.t[q.to];
                freeAt[q.to] = max(freeAt[q.to], finish);
                const int id = (int)acts.size();
                acts.push_back({q.from, q.to, q.when, head[finish]});
                head[finish] = id;
            }
        }
        if (backbone) {
            while (forcedIndex < backbone->size() &&
                   (*backbone)[forcedIndex].when - g.x < startHour)
                ++forcedIndex;
            reserved.resize(g.n);
            reservedIndex.assign(g.n, 0);
            for (size_t j = 1; j < backbone->size(); ++j) {
                const Action &q = (*backbone)[j];
                reserved[q.to].push_back(q.when - g.x);
            }
        }
    }

    template<class Callback>
    void forParents(int v, Callback cb) const {
        const vector<int> &lst = sourceMode ? incoming[v] : g.adj[v];
        for (int u : lst) {
            if (sourceMode || activeAt[u] == T) {
                if (!cb(u)) return;
            }
        }
    }

    int pickParent(int v) const {
        int pick = -1;
        float best = 1e30f;
        if (sourceMode) {
            for (int u : incoming[v]) {
                int r = remaining[u];
                if (r <= 0) continue;
                float metric = (float)options[u] / (r + 0.4f);
                unsigned rnd = scramble((unsigned)v * 0x27d4eb2du ^ (unsigned)u * 0x165667b1u ^ (unsigned)T ^ seed);
                metric += (rnd & 255) * 0.000005f;
                if (metric < best) { best = metric; pick = u; }
            }
        } else {
            const auto &nb = g.adj[v];
            int d = (int)nb.size();
            if (!d) return -1;
            unsigned hash = scramble((unsigned)(v + 1) * 0x9e3779b9u ^ (unsigned)(T + 1) * 0x85ebca6bu ^ seed);
            int j = (int)(hash % d);
            // When active sources are sparse, the calling code uses sourceMode.
            // Here random cyclic probes spread assignments over *all* active
            // parents rather than only the first five adjacency entries.
            int probes = min(d, max(20, (int)(6 * 65536LL / max(1, activeDensityQ16))));
            probes = min(probes, 96);
            int hits = 0;
            for (int z = 0; z < probes; ++z) {
                int u = nb[j];
                if (++j == d) j = 0;
                if (activeAt[u] != T || remaining[u] == 0) continue;
                float metric = (float)options[u] / (remaining[u] + 0.4f);
                unsigned rnd = scramble((unsigned)v * 0x27d4eb2du ^ (unsigned)u * 0x165667b1u ^ (unsigned)T ^ seed);
                metric += (rnd & 255) * 0.000005f;
                if (metric < best) { best = metric; pick = u; }
                if (++hits == 4) break;
            }
        }
        return pick;
    }

    // TRIZ feedback: the static future potential assumes that all recipients
    // are free. Estimate the fraction that will actually be free when this
    // receiver activates, using at most 20 evenly-spaced neighbors.
    float congestionCorrection(int v, int at) const {
        int q = at + g.t[v], d = g.deg[v];
        if (d == 0 || q >= g.m - 1) return 0.0f;
        int h = (g.x + q) % 24;
        int totalOptions = scores.phaseOptions[h * g.n + v];
        if (!totalOptions) return 0.0f;
        int checked = min(d, 20);
        unsigned hash = scramble((unsigned)(v+1)*0x8da6b343u ^ (unsigned)(at+1)*0xd8163841u ^ seed);
        int offset = hash % d;
        int stride = max(1, d / checked);
        int possible = 0, free = 0;
        for (int j=0; j<checked; ++j) {
            int w = g.adj[v][(offset + j*stride) % d];
            if (!g.can(w,h) || q + g.t[w] >= g.m) continue;
            ++possible;
            if (freeAt[w] <= q) ++free;
        }
        if (!possible) return 0.0f;
        float busyRatio = float(possible-free) / possible;
        return -busyRatio * log1pf((float)totalOptions);
    }

    bool blocksBackbone(int v, int at) {
        if (!backbone) return false;
        auto &lst = reserved[v];
        int &idx = reservedIndex[v];
        while (idx < (int)lst.size() && lst[idx] < at) ++idx;
        return idx < (int)lst.size() && lst[idx] < at + g.t[v];
    }

    // Exact augmenting path within a bounded number of alternating edges.
    // This is only used by selected local-search modes, never on the costly
    // default pass. The visit/budget limits guarantee predictable work.
    bool deepAugmentDFS(int v, int depth, int &budget) {
        if (budget <= 0) return false;
        for (int u : incoming[v]) {
            if (--budget < 0) return false;
            if (visitedSource[u] == visitSerial) continue;
            visitedSource[u] = visitSerial;
            if (remaining[u] > 0) {
                --remaining[u];
                owner[v] = u;
                assigned[u].push_back(v);
                return true;
            }
            if (!depth) continue;
            for (int j = 0; j < (int)assigned[u].size(); ++j) {
                if (--budget < 0) return false;
                int w = assigned[u][j];
                if (visitedTarget[w] == visitSerial) continue;
                visitedTarget[w] = visitSerial;
                if (deepAugmentDFS(w, depth - 1, budget)) {
                    assigned[u][j] = v;
                    owner[v] = u;
                    return true;
                }
            }
        }
        return false;
    }

    // One-step augmenting path: u->w is replaced by z->w, then u->v.
    // This repairs collisions without solving a costly global flow problem.
    int augment(int v) {
        int budget = 192;
        int picked = -1;
        forParents(v, [&](int u) {
            if (remaining[u] > 0 || assigned[u].empty()) return true;
            int lim = min((int)assigned[u].size(), 12);
            for (int j = 0; j < lim; ++j) {
                int w = assigned[u][j];
                int z = -1;
                forParents(w, [&](int uu) {
                    if (--budget < 0) return false;
                    if (uu != u && remaining[uu] > 0) { z = uu; return false; }
                    return true;
                });
                if (z != -1) {
                    assigned[u][j] = assigned[u].back();
                    assigned[u].pop_back();
                    assigned[z].push_back(w);
                    owner[w] = z;
                    --remaining[z];
                    picked = u;
                    return false;
                }
                if (budget < 0) return false;
            }
            return budget >= 0;
        });
        return picked;
    }

    vector<Action> run() {
        for (T = startHour; T < g.m; ++T) {
            if (head[T] == -1) continue;
            senders.clear();
            long long sumDeg = 0;
            for (int id = head[T]; id != -1; id = acts[id].next) {
                int u = acts[id].to;
                senders.push_back(u);
                activeAt[u] = T;
                remaining[u] = g.k;
                assigned[u].clear();
                sumDeg += g.deg[u];
            }
            int h = (g.x + T) % 24;
            int r = g.m - T;
            if (r <= 1 || sumDeg == 0) continue;
            int forcedCount = 0;
            if (backbone && forcedIndex < backbone->size() &&
                (*backbone)[forcedIndex].when == g.x + T) {
                const Action &q = (*backbone)[forcedIndex++];
                if (activeAt[q.from] == T && freeAt[q.to] <= T &&
                    g.can(q.to, h) && T + g.t[q.to] < g.m && remaining[q.from] > 0) {
                    int finish = T + g.t[q.to];
                    freeAt[q.to] = finish;
                    int id = (int)acts.size();
                    acts.push_back({q.from, q.to, g.x + T, head[finish]});
                    head[finish] = id;
                    --remaining[q.from];
                    forcedCount = 1;
                }
            }
            // Use source-centric enumeration when few edges leave the active set.
            int S = (int)senders.size();
            sourceMode = (sumDeg <= max(2000LL, 12LL * g.n) ||
                          sumDeg * 8 <= g.edge2);
            activeDensityQ16 = (int)(sumDeg * 65536LL / max(1, g.edge2));

            if (sourceMode) {
                for (int u : senders) {
                    int cnt = 0;
                    for (int v : g.adj[u]) {
                        if (freeAt[v] > T || g.t[v] >= r || !g.can(v, h) || blocksBackbone(v, T)) continue;
                        if (incomingStamp[v] != T) {
                            incomingStamp[v] = T;
                            incoming[v].clear();
                        }
                        incoming[v].push_back(u);
                        ++cnt;
                    }
                    options[u] = cnt;
                }
            } else {
                for (int u : senders) options[u] = scores.phaseOptions[h * g.n + u];
            }

            ranking.clear();
            for (int v = 0; v < g.n; ++v) {
                if (freeAt[v] > T || g.t[v] >= r || !g.can(v, h) || blocksBackbone(v, T)) continue;
                if (sourceMode && incomingStamp[v] != T) continue;
                int baseMode = (mode >= 20) ? (mode - 20) % 8 : (mode >= 16) ? (mode - 16) % 8 : (mode >= 12) ? (mode - 12) % 8 : mode % 8;
                float val = scores.receiverScore(v, T, baseMode, seed);
                if (mode >= 8 && mode < 12) {
                    float weight = mode == 8 ? 1.2f : mode == 9 ? 2.5f : mode == 10 ? 4.5f : 0.6f;
                    val += weight * congestionCorrection(v, T);
                }
                // Scarcity matching: targets reachable by only one sender
                // deserve priority over targets accessible to many sources.
                // Each variant is an optional independent trial.
                if (mode >= 20 && mode <= 22 && sourceMode) {
                    int demand=(int)incoming[v].size();
                    float factor=mode==20?0.12f:(mode==21?0.32f:0.72f);
                    val *= (1.f + factor / sqrt((float)max(1,demand)));
                }
                ranking.emplace_back(val, v);
            }
            if (ranking.empty()) continue;
            sort(ranking.begin(), ranking.end(), [&](const auto &a, const auto &b) {
                if (a.first != b.first) return a.first > b.first;
                if (g.t[a.second] != g.t[b.second]) return g.t[a.second] < g.t[b.second];
                return a.second < b.second;
            });

            chosen.clear();
            long long globalLimit = min((long long)ranking.size(), (long long)S * g.k - forcedCount);
            auto tryAssign = [&](int v) -> bool {
                if ((long long)chosen.size() >= globalLimit) return false;
                int u = pickParent(v);
                if (u == -1 && sourceMode && mode >= 16 && mode < 20) {
                    ++visitSerial;
                    int budget = 384;
                    if (deepAugmentDFS(v, 4, budget)) {
                        chosen.push_back(v);
                        return true;
                    }
                }
                if (u == -1 && sourceMode && (mode < 16 || mode >= 20)) {
                    u = augment(v);
                    if (u >= 0) ++remaining[u];
                }
                if (u < 0) return false;
                owner[v] = u;
                --remaining[u];
                assigned[u].push_back(v);
                chosen.push_back(v);
                return true;
            };
            if (mode >= 12 && mode < 16) {
                // TRIZ separation in time: when all short-degree receivers
                // could only reactivate the same computer, spread their
                // activation times instead of creating a burst of colliding
                // copies. The deferred candidates still get a second pass.
                vector<int> deferred;
                deferred.reserve(min((int)ranking.size(), S * min(g.k, 12)));
                auto onlyNext = [&](int v) -> int {
                    if (g.deg[v] > 4 || g.deg[v] == 0) return -1;
                    int q = T + g.t[v];
                    if (q >= g.m - 1) return -1;
                    int hh = (g.x + q) % 24;
                    int only = -1;
                    for (int w : g.adj[v]) {
                        if (!g.can(w,hh) || q + g.t[w] >= g.m || freeAt[w] > q) continue;
                        if (only != -1) return -1;
                        only = w;
                    }
                    return only;
                };
                for (auto [value,v] : ranking) {
                    (void)value;
                    if ((long long)chosen.size() >= globalLimit) break;
                    int w = onlyNext(v), qoffset = g.t[v];
                    if (w != -1 && futureStamp[w] == T && ((futureShadow[w] >> qoffset) & 1u)) {
                        deferred.push_back(v);
                        continue;
                    }
                    if (!tryAssign(v)) continue;
                    if (w != -1) {
                        if (futureStamp[w] != T) {
                            futureStamp[w] = T;
                            futureShadow[w] = 0u;
                        }
                        int left = max(1, qoffset - g.t[w] + 1);
                        int right = min(23, qoffset + g.t[w] - 1);
                        for (int j = left; j <= right; ++j) futureShadow[w] |= 1u << j;
                    }
                }
                for (int v : deferred) {
                    if ((long long)chosen.size() >= globalLimit) break;
                    tryAssign(v);
                }
            } else {
                for (auto [value,v] : ranking) {
                    (void)value;
                    if ((long long)chosen.size() >= globalLimit) break;
                    tryAssign(v);
                }
            }

            for (int v : chosen) {
                int finish = T + g.t[v];
                freeAt[v] = finish;
                int id = (int)acts.size();
                acts.push_back({owner[v], v, g.x + T, head[finish]});
                head[finish] = id;
            }
        }
        return move(acts);
    }
};

// Exact finite-horizon solver for small connected components.
// At hour T, remaining[v]==1 means a copy activates and may send now;
// remaining[v]>1 means busy, and 0 means idle.  The transition is a
// capacitated bipartite matching from active senders to idle/just-freed targets.
struct ExactSmall {
    const Problem &g;
    int n, m, k;
    vector<unsigned> neighborMask;
    vector<unsigned> legalAt;
    vector<unsigned long long> maskCode;
    struct Answer { int value; unsigned short chosen; };
    unordered_map<unsigned long long, Answer> memo;
    unsigned long long transitions = 0;
    unsigned long long nodes = 0;
    chrono::steady_clock::time_point started;
    bool timedOut = false;

    ExactSmall(const Problem &p) : g(p), n(p.n), m(p.m), k(p.k) {
        neighborMask.assign(n, 0);
        for (int u = 0; u < n; ++u)
            for (int v : g.adj[u]) neighborMask[u] |= 1u << v;
        legalAt.assign(m, 0);
        for (int T = 0; T < m; ++T) {
            int phase = (g.x+T)%24;
            for (int v = 0; v < n; ++v)
                if (g.can(v, phase) && T + g.t[v] < m) legalAt[T] |= 1u << v;
        }
        maskCode.assign(1u<<n, 0);
        for (unsigned s = 1; s < (1u<<n); ++s) {
            unsigned bit = __builtin_ctz(s);
            maskCode[s] = maskCode[s^(1u<<bit)] | ((unsigned long long)g.t[bit] << (5*bit));
        }
        memo.reserve(200000);
        started = chrono::steady_clock::now();
    }

    // All feasible sets of targets for the current instant. Earlier
    // target sets remain feasible: skipping an infection may be optimal.
    int dfs(int T, unsigned long long state) {
        if (T >= m) return 0;
        unsigned long long key = ((unsigned long long)T << 48) | state;
        auto it = memo.find(key);
        if (it != memo.end()) return it->second.value;
        ++nodes;
        if (nodes > 120000 || transitions > 2000000 ||
            ((nodes & 1023) == 0 && chrono::duration<double>(chrono::steady_clock::now()-started).count() > 0.23)) {
            timedOut = true;
            throw 1;
        }
        unsigned send = 0, freeMask = 0;
        unsigned long long shifted = 0;
        for (int v = 0; v < n; ++v) {
            unsigned rem = (unsigned)((state >> (5*v)) & 31u);
            if (rem == 1) send |= 1u << v;
            if (rem <= 1) freeMask |= 1u << v;
            else shifted |= (unsigned long long)(rem-1) << (5*v);
        }
        if (!send && !shifted) {
            memo.emplace(key, Answer{0,0});
            return 0;
        }
        if (!send || !(legalAt[T] & freeMask)) {
            int result = dfs(T+1, shifted);
            memo.emplace(key, Answer{result,0});
            return result;
        }
        int feasibleLimit = 1u<<n;
        // Each feasible union of recipient subsets is represented by one bit.
        // f is capped by n<=9; worst-case 2^9=512 entries.
        array<unsigned char,512> f{}, next{};
        f[0] = 1;
        unsigned available = freeMask & legalAt[T];
        for (int u = 0; u < n; ++u) {
            if (!(send & (1u<<u))) continue;
            unsigned option = neighborMask[u] & available;
            if (!option) continue;
            next = f; // sender may choose zero targets
            for (int used = 0; used < feasibleLimit; ++used) {
                if (!f[used]) continue;
                unsigned canTake = option & ~unsigned(used);
                for (unsigned take = canTake; take; take = (take-1)&canTake) {
                    ++transitions;
                    if (__builtin_popcount(take) <= k) next[used|take] = 1;
                }
            }
            f = next;
        }
        int best = -1;
        unsigned chosen = 0;
        for (unsigned take = 0; take < (unsigned)feasibleLimit; ++take) {
            if (!f[take]) continue;
            ++transitions;
            int result = __builtin_popcount(take) + dfs(T+1, shifted | maskCode[take]);
            if (result > best) { best = result; chosen = take; }
        }
        memo.emplace(key, Answer{best, (unsigned short)chosen});
        return best;
    }

    // Recover a concrete matching for a selected target set.
    bool assign(unsigned chosen, unsigned send, vector<int> &parent) const {
        vector<int> targets;
        for (int v = 0; v < n; ++v) if (chosen & (1u<<v)) targets.push_back(v);
        stable_sort(targets.begin(),targets.end(),[&](int v,int w){
            return __builtin_popcount(neighborMask[v] & send) < __builtin_popcount(neighborMask[w] & send);
        });
        vector<int> quota(n, k);
        function<bool(int)> solve = [&](int i) -> bool {
            if (i == (int)targets.size()) return true;
            int v = targets[i];
            for (int u = 0; u < n; ++u) {
                if (!(send & (1u<<u)) || !(neighborMask[u] & (1u<<v)) || !quota[u]) continue;
                --quota[u]; parent[v] = u;
                if (solve(i+1)) return true;
                ++quota[u];
            }
            return false;
        };
        return solve(0);
    }
    optional<vector<Action>> solve() {
        try { dfs(0, 1ULL << (5*g.p)); }
        catch (int) { return nullopt; }
        vector<Action> ans;
        ans.push_back({-1,g.p,-1,-1});
        unsigned long long state = 1ULL << (5*g.p);
        for (int T = 0; T < m; ++T) {
            unsigned long long key = ((unsigned long long)T << 48) | state;
            unsigned chosen = memo.at(key).chosen;
            unsigned send=0;
            unsigned long long shifted=0;
            for (int v=0; v<n; ++v) {
                unsigned rem = (unsigned)((state >> (5*v))&31u);
                if (rem==1) send |= 1u<<v;
                if (rem>1) shifted |= (unsigned long long)(rem-1) << (5*v);
            }
            if (chosen) {
                vector<int> parent(n,-1);
                if (!assign(chosen,send,parent)) return nullopt;
                for (int v=0;v<n;++v) if(chosen&(1u<<v))
                    ans.push_back({parent[v],v,g.x+T,-1});
            }
            state = shifted | maskCode[chosen];
            if (!state) break;
        }
        return ans;
    }
};

static optional<vector<Action>> exactSmallComponent(const Problem &g) {
    if (g.m > 1800 || g.k <= 1) return nullopt;
    vector<int> component; component.reserve(10);
    vector<unsigned char> seen(g.n);
    component.push_back(g.p); seen[g.p] = true;
    for (size_t i=0;i<component.size();++i) {
        for (int v:g.adj[component[i]]) if (!seen[v]) {
            if (component.size() >= 9) return nullopt;
            seen[v] = true; component.push_back(v);
        }
    }
    if (component.size() <= 1) return vector<Action>{{-1,g.p,-1,-1}};
    const int c=(int)component.size();
    const int maxHorizon=c<=4?1800:(c<=6?600:(c<=7?300:180));
    if(g.m>maxHorizon) return nullopt;
    Problem h;
    h.n = (int)component.size(); h.k = g.k; h.p = 0;
    h.x = g.x; h.m = g.m;
    h.a.resize(h.n); h.b.resize(h.n); h.t.resize(h.n);
    h.adj.resize(h.n); h.legal.resize(h.n); h.deg.resize(h.n);
    vector<int> idx(g.n,-1);
    for (int i=0;i<h.n;++i) idx[component[i]] = i;
    for (int i=0;i<h.n;++i) {
        int u=component[i];
        h.a[i]=g.a[u];h.b[i]=g.b[u];h.t[i]=g.t[u];h.legal[i]=g.legal[u];
        for (int v:g.adj[u]) h.adj[i].push_back(idx[v]);
        h.deg[i]=(int)h.adj[i].size();
        h.edge2+=h.deg[i];
    }
    ExactSmall ex(h);
    auto ans=ex.solve();
    if (!ans) return nullopt;
    for (auto &act : *ans) {
        if (act.from >= 0) act.from=component[act.from];
        act.to=component[act.to];
    }
    return ans;
}

// Safely add transmissions to *existing* activations and recursively exploit
// new ones, while never disturbing any original successful transmission.
// The occupancy grid is affordable because n*m <= 1,000,000.
static vector<Action> fillUnused(const Problem &g, const Scores &scores,
                                vector<Action> ev,
                                chrono::steady_clock::time_point start,
                                int edgeLimit=1500000) {
    const int n=g.n,m=g.m;
    if (g.k<=1 || ev.size()>350000 || ev.size()<1) return ev;
    vector<unsigned char> busy((size_t)n*m,0);
    vector<int> used((size_t)n*m,0), head(m,-1), link;
    link.resize(ev.size());
    for (int i=0;i<(int)ev.size();++i) {
        const Action &e=ev[i];
        int when=(i==0 ? 0 : e.when-g.x+g.t[e.to]);
        link[i]=head[when];head[when]=i;
        if (i) {
            int send=e.when-g.x;
            ++used[(size_t)send*n+e.from];
            for (int j=send; j<when; ++j) busy[(size_t)j*n+e.to]=1;
        }
    }
    vector<pair<float,int>> choices;
    choices.reserve(min(n,1024));
    int probes=0, added=0;
    for (int s=0;s<m-1;++s) {
        if (head[s]==-1) continue;
        if ((s&31)==0 && chrono::duration<double>(chrono::steady_clock::now()-start).count()>1.53) break;
        int h=(g.x+s)%24;
        for (int id=head[s];id!=-1;id=link[id]) {
            int u=ev[id].to;
            int room=min(g.k,g.deg[u])-used[(size_t)s*n+u];
            if (room<=0)continue;
            if (probes+g.deg[u]>edgeLimit) return ev;
            probes+=g.deg[u];
            choices.clear();
            for (int v:g.adj[u]) {
                if(!g.can(v,h) || s+g.t[v]>=m)continue;
                int finish=s+g.t[v];
                bool free=true;
                for (int j=s;j<finish;++j) if(busy[(size_t)j*n+v]) {free=false;break;}
                if(free)choices.emplace_back(scores.receiverScore(v,s,0,0x9e3779b9u),v);
            }
            if(choices.empty())continue;
            if((int)choices.size()>room) {
                nth_element(choices.begin(),choices.begin()+room,choices.end(),
                    [](auto a,auto b){return a.first>b.first || (a.first==b.first && a.second<b.second);});
                choices.resize(room);
            }
            // Append new events after reservations of all original events have
            // already been marked in busy[]. New events finish later than s.
            for (auto [score,v]:choices) {
                int end=s+g.t[v];
                bool free=true;
                for (int j=s;j<end;++j) if(busy[(size_t)j*n+v]) {free=false;break;}
                if(!free)continue;
                for (int j=s;j<end;++j) busy[(size_t)j*n+v]=1;
                ++used[(size_t)s*n+u];
                int j=(int)ev.size();
                ev.push_back({u,v,g.x+s,-1});
                link.push_back(head[end]);head[end]=j;
                ++added;
            }
        }
    }
    return ev;
}


int main() {
    FastInput in;
    Problem g;
    g.n = in.read(); g.p = in.read() - 1; g.k = in.read();
    g.x = in.read(); g.m = in.read();
    int n = g.n;
    g.a.resize(n); g.b.resize(n); g.t.resize(n);
    for (int i = 0; i < n; ++i) { g.a[i] = in.read(); g.b[i] = in.read(); }
    for (int i = 0; i < n; ++i) g.t[i] = in.read();
    g.adj.resize(n);
    for (int u = 0; u < n; ++u) {
        while (true) {
            int v = in.read();
            if (v == 0) break;
            g.adj[u].push_back(v - 1);
            ++g.edge2;
        }
    }
    g.deg.resize(n);
    g.legal.resize(n, 0);
    for (int v = 0; v < n; ++v) {
        g.deg[v] = (int)g.adj[v].size();
        for (int h = 0; h < 24; ++h) {
            int offset = (h - g.a[v] + 24) % 24;
            if (offset + g.t[v] <= g.b[v]) g.legal[v] |= 1u << h;
        }
    }

    auto programStart = chrono::steady_clock::now();
    vector<Action> best;
    if (g.k == 1) {
        best = solve_one(g);
    } else if (auto exact = exactSmallComponent(g)) {
        best = move(*exact);
    } else if (g.m == 1 || g.edge2 == 0) {
        best.push_back({-1, g.p, -1, -1});
    } else {
        Scores scores(g);
        vector<Action> backbone = recover_chain(g, scores.spine);
        best = backbone;
        double lastDuration = 0.0;
        const int schedule[][2] = {
            {0,1},{1,0},{2,0},{3,1},{4,0},{5,0},{6,1},{7,0},
            {0,0},{1,1},{2,0},{3,0},  // Original v2 trials, same seeds
            {12,1},{13,1},{14,1},{15,0},{12,0},{13,0},{14,0},{15,1},
            {8,1},{9,1},{8,0},{9,0},{7,1},{4,1},{6,0},{10,0},
            {16,1},{16,0},{17,0},{18,0}
        };
        const int presets = (int)(sizeof(schedule)/sizeof(schedule[0]));
        int bestMode = 0, bestBackbone = 1;
        for (int trial = 0; trial < 200; ++trial) {
            auto now = chrono::steady_clock::now();
            double elapsed = chrono::duration<double>(now - programStart).count();
            double printReserve = 0.12 + 0.23 * min(1.0, (double)best.size() / 1000000.0);
            if (trial && elapsed + 1.35 * lastDuration + printReserve > 1.27) break;
            int mode, useBackbone;
            // Large-neighborhood search: retain the best prefix and re-optimize its suffix.
            bool isLNS = false;
            int pivot = 0;
            if (trial < presets) {
                mode = schedule[trial][0];
                useBackbone = schedule[trial][1];
            } else {
                int phase = (trial-presets) % 16;
                if (phase < 9) {
                    mode = bestMode;
                    useBackbone = bestBackbone;
                    isLNS = (phase >= 2);
                } else if (phase < 13) {
                    mode = (phase == 9 || phase == 10) ? 12 : 7;
                    useBackbone = (phase % 2 == 0);
                } else {
                    int j = ((trial - presets) / 16 + phase * 3) % presets;
                    mode = schedule[j][0];
                    useBackbone = schedule[j][1];
                }
                if (isLNS) {
                    static constexpr int fractions[] = {15,30,45,60,75,90,40};
                    int fraction = fractions[(phase - 2) % 7];
                    pivot = max(1, min(g.m-1, g.m * fraction / 100));
                    // For LNS, avoid forcing a different backbone.
                    useBackbone = 0;
                }
            }
            const vector<Action> *fixed = useBackbone ? &backbone : nullptr;
            const vector<Action> *prefix = isLNS ? &best : nullptr;
            Sim sim(g, scores, mode, 0xabc123u + (unsigned)trial * 0x9e3779b9u,
                    fixed, prefix, pivot);
            auto runStart = chrono::steady_clock::now();
            vector<Action> cur = sim.run();
            lastDuration = chrono::duration<double>(chrono::steady_clock::now() - runStart).count();
            if (cur.size() > best.size()) {
                best = move(cur);
                bestMode = mode;
                bestBackbone = useBackbone;
            }
        }
        // Spend remaining computational budget on scarcity-aware schedules.
        // These runs cannot worsen the incumbent solution.
        for (int mode: {20,21,22}) {
            double now=chrono::duration<double>(chrono::steady_clock::now()-programStart).count();
            double reserve=0.12 + 0.23*min(1.0,(double)best.size()/1000000.0);
            if (now+1.5*max(lastDuration,0.005)+reserve > 1.58) break;
            Sim sim(g,scores,mode,0xacc001u+(unsigned)mode*0x9e3779b9u);
            auto t0=chrono::steady_clock::now();
            vector<Action> trial=sim.run();
            lastDuration=chrono::duration<double>(chrono::steady_clock::now()-t0).count();
            if (trial.size()>best.size()) best=std::move(trial);
        }
        // A one-way, bounded augmentation pass never removes original events.
        // Its occupancy grid uses at most N*m <= 1e6 byte cells.
        double now=chrono::duration<double>(chrono::steady_clock::now()-programStart).count();
        if (best.size()<350000 && now<1.34) {
            best=fillUnused(g,scores,std::move(best),programStart,1800000);
        }
    }
    printf("%zu\n",best.size());
    string output;
    output.reserve(1<<20);
    for (size_t i=1;i<best.size();++i) {
        output+=to_string(best[i].from+1);
        output+=' ';
        output+=to_string(best[i].to+1);
        output+=' ';
        output+=to_string(best[i].when);
        output+='\n';
        if(output.size()>=(1u<<20)) {
            fwrite(output.data(),1,output.size(),stdout);
            output.clear();
        }
    }
    if(!output.empty()) fwrite(output.data(),1,output.size(),stdout);
    return 0;
}
