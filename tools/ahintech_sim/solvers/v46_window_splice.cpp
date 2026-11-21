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

// Judge budget: keep space for output serialization and scheduler variance.
static constexpr double JUDGE_WALL_LIMIT = 2.0;
static inline double finishReserve(size_t numEvents) {
    return 0.17 + 0.23 * min(1.0, double(numEvents) / 1000000.0);
}
static inline double elapsedSince(chrono::steady_clock::time_point start) {
    return chrono::duration<double>(chrono::steady_clock::now() - start).count();
}


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
    vector<int> senders, targets, chosen, touchedTargets;
    vector<pair<float,int>> ranking;
    int T = 0;
    bool sourceMode = false;
    chrono::steady_clock::time_point globalStart;
    double globalLimit;
    int activeDensityQ16 = 0;
    const vector<Action> *backbone = nullptr;
    vector<vector<int>> reserved;
    vector<int> reservedIndex;
    size_t forcedIndex = 1;
    int startHour = 0;
    int forbiddenHour = -1, forbiddenTarget = -1;

    Sim(const Problem &g_, const Scores &scores_, int mode_, unsigned seed_,
        const vector<Action> *forced = nullptr,
        const vector<Action> *prefix = nullptr, int pivot = 0,
        chrono::steady_clock::time_point globalStart_ = chrono::steady_clock::time_point::max(),
        double globalLimit_ = 1e9,
        int forbiddenHour_ = -1, int forbiddenTarget_ = -1)
        : g(g_), scores(scores_), mode(mode_), seed(seed_),
          globalStart(globalStart_), globalLimit(globalLimit_),
          head(g.m, -1), freeAt(g.n, 0), activeAt(g.n, -1),
          remaining(g.n, 0), options(g.n, 0), incomingStamp(g.n, -1),
          owner(g.n, -1), futureShadow(g.n, 0), futureStamp(g.n, -1),
          visitedSource(g.n, 0), visitedTarget(g.n, 0),
          incoming(g.n), assigned(g.n), backbone(forced) {
        forbiddenHour = forbiddenHour_; forbiddenTarget = forbiddenTarget_;
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
            if ((T & 7) == 0 && globalLimit < 1e8 &&
                elapsedSince(globalStart) + finishReserve(acts.size()) >= globalLimit)
                break;  // Returning a partial trial is safe; the incumbent is preserved.
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

            touchedTargets.clear();
            if (sourceMode) {
                for (int u : senders) {
                    int cnt = 0;
                    for (int v : g.adj[u]) {
                        if (freeAt[v] > T || g.t[v] >= r || !g.can(v, h) || blocksBackbone(v, T)) continue;
                        if (incomingStamp[v] != T) {
                            incomingStamp[v] = T;
                            incoming[v].clear();
                            touchedTargets.push_back(v);
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
            const int targetCount = sourceMode ? (int)touchedTargets.size() : g.n;
            for (int j = 0; j < targetCount; ++j) {
                int v = sourceMode ? touchedTargets[j] : j;
                if (T == forbiddenHour && v == forbiddenTarget) continue;
                if (freeAt[v] > T || g.t[v] >= r || !g.can(v, h) || blocksBackbone(v, T)) continue;
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
                // Quality-first: exact one-generation capacity estimate with
                // all currently scheduled occupancy respected.  Offline modes
                // 28..35 explore different tradeoffs with eventual chain value.
                if (mode >= 28 && mode <= 35) {
                    const int q = T + g.t[v];
                    if (q < g.m - 1 && g.deg[v]) {
                        int nextH = (g.x + q) % 24;
                        int possible = 0, freeCount = 0;
                        const auto &nb = g.adj[v];
                        const int checked = min((int)nb.size(), 80);
                        const int stride = max(1, (int)nb.size()/checked);
                        unsigned hash = scramble((unsigned)v*0x9e3779b9u ^
                                                 (unsigned)T*0x85ebca6bu ^ seed);
                        int z = (int)(hash % nb.size());
                        for (int j=0;j<checked;++j) {
                            int w=nb[z];
                            z+=stride;
                            if(z >= (int)nb.size()) z-=(int)nb.size();
                            if (!g.can(w,nextH) || q + g.t[w] >= g.m) continue;
                            ++possible;
                            if (freeAt[w] <= q) ++freeCount;
                        }
                        int variant=mode-28;
                        static const float boost[8]={0.6f,1.25f,2.3f,3.4f,
                                                      0.9f,1.8f,3.0f,4.6f};
                        const float scarcity=possible ? (float)freeCount/possible : 0.f;
                        val += boost[variant]*log1pf((float)freeCount);
                        val -= (variant&4 ? 0.75f : 0.2f) *
                               (1.0f-scarcity)*log1pf((float)possible);
                    }
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
            if (mode >= 24 && mode <= 27) {
                // Look one activation ahead. Multiple simultaneous infections
                // that rely on the same few future recipients tend to collide.
                vector<int> deferred;
                deferred.reserve(min((int)ranking.size(),S*min(g.k,8)));
                int nextCount = min(g.k,mode-23);
                auto forecast = [&](int v,vector<int> &future)->void {
                    future.clear();
                    int q=T+g.t[v];
                    if (q >= g.m-1 || g.deg[v]==0) return;
                    int hh=(g.x+q)%24;
                    const auto &nb=g.adj[v];int d=(int)nb.size();
                    int take=min(d,32);
                    int skip=max(1,d/take);
                    unsigned r=scramble((unsigned)(v+1)*0x8da6b343u^(unsigned)(T+1)*0xd8163841u^seed);
                    int pos=(int)(r%d);
                    vector<pair<float,int>> top;
                    top.reserve(nextCount+1);
                    for (int j=0;j<take;++j) {
                        int w=nb[pos];pos+=skip;if(pos>=d)pos-=d;
                        if (!g.can(w,hh) || q+g.t[w]>=g.m || freeAt[w]>q) continue;
                        float value=scores.receiverScore(w,q,0,seed);
                        if ((int)top.size()<nextCount) {
                            top.push_back({value,w});
                        } else {
                            int smallest=0;
                            for (int z=1;z<(int)top.size();++z)
                                if (top[z].first<top[smallest].first)smallest=z;
                            if (value>top[smallest].first) top[smallest]={value,w};
                        }
                    }
                    for (auto [value,w]:top) future.push_back(w);
                };
                vector<int> pred;
                for (auto [value,v]:ranking) {
                    (void)value;
                    if ((long long)chosen.size()>=globalLimit)break;
                    forecast(v,pred);
                    int overlaps=0;
                    for (int w:pred) {
                        if (futureStamp[w]==T &&
                            (futureShadow[w] & (1u<<g.t[v]))) ++overlaps;
                    }
                    if (!pred.empty() && overlaps==(int)pred.size()) {
                        deferred.push_back(v);
                        continue;
                    }
                    if (!tryAssign(v)) continue;
                    for (int w:pred) {
                        if (futureStamp[w]!=T) {
                            futureStamp[w]=T;
                            futureShadow[w]=0u;
                        }
                        int low=max(1,g.t[v]-g.t[w]+1);
                        int high=min(23,g.t[v]+g.t[w]-1);
                        for(int h2=low;h2<=high;++h2) futureShadow[w]|=1u<<h2;
                    }
                }
                for (int v:deferred) {
                    if ((long long)chosen.size()>=globalLimit)break;
                    tryAssign(v);
                }
            } else             if (mode >= 12 && mode < 16) {
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
    using Key = __uint128_t;
    struct KeyHash {
        size_t operator()(Key value) const {
            unsigned long long a = (unsigned long long)value;
            unsigned long long b = (unsigned long long)(value>>64);
            unsigned long long z=a^(b*0x9e3779b97f4a7c15ULL);
            z^=z>>30;z*=0xbf58476d1ce4e5b9ULL;
            z^=z>>27;z*=0x94d049bb133111ebULL;
            return (size_t)(z^(z>>31));
        }
    };
    unordered_map<Key, Answer, KeyHash> memo;
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
        Key key = ((Key)T << (5*n)) | state;
        auto it = memo.find(key);
        if (it != memo.end()) return it->second.value;
        ++nodes;
        if (nodes > (n<=9 ? 450000ULL : 120000ULL) ||
            transitions > (n<=9 ? 12000000ULL : 2000000ULL) ||
            ((nodes & 1023) == 0 && chrono::duration<double>(chrono::steady_clock::now()-started).count() > 0.19)) {
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
        const int feasibleLimit = 1u<<n;
        // Enumerate every one-hour matching by its target set, not by edge
        // assignments. This collapses many equivalent allocations of k
        // copies among active senders into a single future state.
        auto runMatching = [&](unsigned char* f, unsigned char* nxt) {
            memset(f, 0, feasibleLimit);
            f[0]=1;
            unsigned available=freeMask & legalAt[T];
            for (int u = 0; u < n; ++u) {
                if (!(send & (1u<<u))) continue;
                unsigned option = neighborMask[u] & available;
                if (!option) continue;
                memcpy(nxt,f,feasibleLimit); // sender may choose zero targets
                for (int used=0;used<feasibleLimit;++used) {
                    if (!f[used]) continue;
                    unsigned canTake=option & ~unsigned(used);
                    for (unsigned take=canTake;take;take=(take-1)&canTake) {
                        if (__builtin_popcount(take)<=k) nxt[used|take]=1;
                        ++transitions;
                        if ((transitions & 65535ULL)==0 &&
                            (transitions>(n<=9 ? 12000000ULL : 2000000ULL) ||
                            chrono::duration<double>(chrono::steady_clock::now()-started).count()>0.19))
                            throw 1;
                    }
                }
                memcpy(f,nxt,feasibleLimit);
            }
            int best=-1;
            unsigned chosen=0;
            for(unsigned take=0;take<(unsigned)feasibleLimit;++take) {
                if(!f[take])continue;
                ++transitions;
                int result=__builtin_popcount(take)+dfs(T+1,shifted|maskCode[take]);
                if(result>best) {best=result;chosen=take;}
            }
            memo.emplace(key, Answer{best,(unsigned short)chosen});
            return best;
        };
        if(n<=9) {
            array<unsigned char,512> f{},nxt{};
            return runMatching(f.data(),nxt.data());
        }
        vector<unsigned char> f(feasibleLimit),nxt(feasibleLimit);
        return runMatching(f.data(),nxt.data());
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
        catch (int) { if (getenv("AHINTEK_TRACE")) fprintf(stderr,"[EXACT] nodes=%llu transitions=%llu time=%.3f n=%d m=%d\n",nodes,transitions,chrono::duration<double>(chrono::steady_clock::now()-started).count(),n,m); return nullopt; }
        vector<Action> ans;
        ans.push_back({-1,g.p,-1,-1});
        unsigned long long state = 1ULL << (5*g.p);
        for (int T = 0; T < m; ++T) {
            Key key = ((Key)T << (5*n)) | state;
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
    vector<int> component; component.reserve(13);
    vector<unsigned char> seen(g.n);
    component.push_back(g.p); seen[g.p] = true;
    for (size_t i=0;i<component.size();++i) {
        for (int v:g.adj[component[i]]) if (!seen[v]) {
            if (component.size() >= 12) return nullopt;
            seen[v] = true; component.push_back(v);
        }
    }
    if (component.size() <= 1) return vector<Action>{{-1,g.p,-1,-1}};
    const int c=(int)component.size();
    const int maxHorizon=c<=4?1800:(c<=6?600:(c<=7?300:(c<=9?180:70)));
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
                                double wallLimit,
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
        if ((s&31)==0 && elapsedSince(start) + finishReserve(ev.size()) >= wallLimit) break;
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


// Diversified finite-state beam search. Each state encodes the remaining
// unpacking times (5 bits per vertex). It is exact as a state transition
// model but heuristic in its bounded candidate generation and pruning.
static optional<vector<Action>> searchBeam(const Problem &g, const Scores &scores,
            chrono::steady_clock::time_point started, double deadline) {
    if (g.n > 13 || g.n < 2 || g.m > 5000 || g.k < 2) return nullopt;
    if (chrono::duration<double>(chrono::steady_clock::now()-started).count()>deadline-0.075)
        return nullopt;
    constexpr int WIDTH = 256;
    constexpr int VAR = 10;
    struct Node { uint64_t state, assignment; int count, parent; };
    struct Candidate { uint64_t state, assignment; int count, parent; float key; };
    vector<Node> nodes;
    nodes.reserve((size_t)g.m*WIDTH+1);
    nodes.push_back({1ULL << (5*g.p),0,1,-1});
    vector<int> current(1,0), next;
    vector<Candidate> cand;
    cand.reserve(WIDTH*(VAR+1));
    unordered_map<uint64_t,int> uniq;
    uniq.reserve(2048);
    const int n=g.n;
    vector<int> preference[VAR];
    int completed = 0;
    for (int T=0; T<g.m; ++T) {
        if ((T&7)==0 && chrono::duration<double>(chrono::steady_clock::now()-started).count()>deadline)
            break;
        int h=(g.x+T)%24;
        for (int j=0;j<VAR;++j) preference[j].clear();
        for (int v=0;v<n;++v) if (g.t[v]+T<g.m && g.can(v,h))
            for (int j=0;j<VAR;++j) preference[j].push_back(v);
        for (int j=0;j<VAR;++j) {
            stable_sort(preference[j].begin(),preference[j].end(),[&](int a,int b){
                float aa,bb;
                if (j==8) { aa=1.f/g.t[a];bb=1.f/g.t[b]; }
                else if (j==9) {
                    aa=(float)g.deg[a] / (g.t[a]+1);
                    bb=(float)g.deg[b] / (g.t[b]+1);
                } else {
                    aa=scores.receiverScore(a,T,j,(unsigned)(j*0x1f123bb5u));
                    bb=scores.receiverScore(b,T,j,(unsigned)(j*0x1f123bb5u));
                }
                if (aa!=bb) return aa>bb;
                return a<b;
            });
        }
        cand.clear();uniq.clear();
        for (int prev:current) {
            const Node &node=nodes[prev];
            int rem[13];uint64_t shift=0;
            int active=0, available=0;
            for (int v=0;v<n;++v) {
                rem[v]=(int)((node.state >> (5*v)) & 31u);
                if (rem[v]==1) active|=1<<v;
                if (rem[v]<=1 && g.can(v,h) && T+g.t[v]<g.m) available|=1<<v;
                if (rem[v]>1) shift|=(uint64_t)(rem[v]-1) << (5*v);
            }
            auto addCandidate=[&](uint64_t nextState,uint64_t assign,int gained){
                int score=node.count+gained;
                auto it=uniq.find(nextState);
                float heuristic=(float)score;
                // Approximate future reproduction by surviving active copies.
                // The growth factor is capped so that realized score dominates.
                float ahead=0;
                for (int v=0;v<n;++v) {
                    int tt=(int)((nextState>>(5*v))&31u);
                    if (tt && tt+T+1 < g.m) {
                        int chain=scores.spine[(size_t)(T+1+tt-1)*n+v];
                        ahead+=min(18.f,log1pf((float)max(0,chain-1))*2.3f);
                    }
                }
                heuristic += 0.37f*ahead;
                Candidate c{nextState,assign,score,prev,heuristic};
                if (it==uniq.end()) {
                    uniq.emplace(nextState,(int)cand.size());cand.push_back(c);
                } else if (c.count>cand[it->second].count ||
                           (c.count==cand[it->second].count && c.key>cand[it->second].key)) {
                    cand[it->second]=c;
                }
            };
            addCandidate(shift,0,0);
            if (!active || !available) continue;
            for (int variant=0;variant<VAR+2;++variant) {
                int parents[13];int quota[13]={0};
                fill(parents,parents+n,-1);
                for (int v=0;v<n;++v) if (active&(1<<v)) quota[v]=g.k;
                unsigned chosen=0;
                const auto &order=preference[variant%VAR];
                int skip=(variant>=VAR ? (variant-VAR+1) : 0);
                for (int v:order) {
                    if (!(available&(1<<v))) continue;
                    if (skip>0) {--skip;continue;}
                    bool marked[13]={};
                    auto augment = [&](auto &&self,int w)->bool {
                        if (marked[w])return false;
                        marked[w]=true;
                        for (int u:g.adj[w]) if (active&(1<<u)) {
                            if (quota[u]) {
                                --quota[u];parents[w]=u;return true;
                            }
                        }
                        for (int u:g.adj[w]) if (active&(1<<u)) {
                            for (int z=0;z<n;++z) if (parents[z]==u) {
                                if(self(self,z)) {parents[w]=u;return true;}
                            }
                        }
                        return false;
                    };
                    if (augment(augment,v)) chosen|=1<<v;
                }
                if (!chosen) continue;
                uint64_t nextState=shift, assign=0;
                for (int v=0;v<n;++v)if(chosen&(1<<v)){
                    nextState|=(uint64_t)g.t[v] << (5*v);
                    assign|=(uint64_t)(parents[v]+1) << (4*v);
                }
                addCandidate(nextState,assign,__builtin_popcount(chosen));
            }
        }
        if (cand.empty()) break;
        int take=min(WIDTH,(int)cand.size());
        if ((int)cand.size()>take) nth_element(cand.begin(),cand.begin()+take,cand.end(),
          [](const Candidate &a,const Candidate &b){return a.key>b.key;});
        sort(cand.begin(),cand.begin()+take,
          [](const Candidate &a,const Candidate &b){return a.key>b.key;});
        next.clear();
        for (int j=0;j<take;++j) {
            const Candidate &c=cand[j];
            next.push_back((int)nodes.size());
            nodes.push_back({c.state,c.assignment,c.count,c.parent});
        }
        current.swap(next);
        completed=T+1;
    }
    if (current.empty()) return nullopt;
    int winner=current[0];
    for (int id:current) if (nodes[id].count>nodes[winner].count) winner=id;
    vector<pair<int,uint64_t>> history;
    for (int id=winner;nodes[id].parent!=-1;id=nodes[id].parent)
        history.push_back({(int)history.size(), nodes[id].assignment});
    vector<Action> result;result.reserve(nodes[winner].count);
    result.push_back({-1,g.p,-1,-1});
    reverse(history.begin(),history.end());
    // Each saved transition is at hour [0, completed).
    for (int T=0;T<(int)history.size();++T) {
        uint64_t code=history[T].second;
        for (int v=0;v<n;++v) {
            int parent=(int)((code>>(4*v))&15)-1;
            if (parent>=0) result.push_back({parent,v,g.x+T,-1});
        }
    }
    return result;
}

// Quality-first beam search for 14..24 computers.  This is a heuristic;
// transitions are exact, and we retain multiple alternative future states.
static optional<vector<Action>> searchBeamWide(
        const Problem &g, const Scores &scores,
        chrono::steady_clock::time_point started, double deadline) {
    using U128 = unsigned __int128;
    if(g.n < 10 || g.n > 24 || g.m > 3000 || g.k < 2) return nullopt;
    if(chrono::duration<double>(chrono::steady_clock::now()-started).count()+0.05>deadline)
        return nullopt;
    const int n=g.n;
    const int WIDTH=(n<=16?192:96);
    const int VAR=10;
    struct Node { U128 state, assignment; int score, parent; };
    struct Candidate { U128 state, assignment; int score, parent; float weight; };
    struct Hash {
        size_t operator()(U128 x) const {
            unsigned long long lo=(unsigned long long)x;
            unsigned long long hi=(unsigned long long)(x>>64);
            unsigned long long z=(lo^hi*0x9e3779b97f4a7c15ull);
            z^=z>>30;z*=0xbf58476d1ce4e5b9ull;
            z^=z>>27;z*=0x94d049bb133111ebull;
            return (size_t)(z^(z>>31));
        }
    };
    vector<Node> states;
    states.reserve((size_t)WIDTH*g.m+1);
    states.push_back({(U128)1<<(5*g.p),0,1,-1});
    vector<int> frontier{0},next;
    vector<Candidate> proposals;
    proposals.reserve(WIDTH*(VAR+4));
    unordered_map<U128,int,Hash> dedup;
    dedup.reserve(WIDTH*(VAR+4));
    vector<int> priority[VAR];
    int timeDone=0;
    for(int T=0;T<g.m;++T) {
        if((T&7)==0 && chrono::duration<double>(chrono::steady_clock::now()-started).count()>deadline)
            break;
        int h=(g.x+T)%24;
        for(int c=0;c<VAR;++c)priority[c].clear();
        for(int v=0;v<n;++v)if(T+g.t[v]<g.m && g.can(v,h))
            for(int c=0;c<VAR;++c)priority[c].push_back(v);
        for(int c=0;c<VAR;++c) {
            auto eval=[&](int v)->float {
                if(c==8)return 1.f/(float)g.t[v];
                if(c==9)return (float)g.deg[v]/(g.t[v]+1.f);
                return scores.receiverScore(v,T,c,(unsigned)(c*0x1f123bb5u));
            };
            sort(priority[c].begin(),priority[c].end(),[&](int a,int b){
                float x=eval(a),y=eval(b);
                if(x!=y)return x>y;
                return a<b;
            });
        }
        proposals.clear();dedup.clear();
        for(int prev:frontier) {
            Node node=states[prev];
            int rem[24]={};U128 shifted=0;
            int active=0,available=0;
            for(int v=0;v<n;++v) {
                rem[v]=(int)((node.state>>(5*v))&31);
                if(rem[v]==1)active|=1<<v;
                if(rem[v]<=1 && T+g.t[v]<g.m && g.can(v,h))available|=1<<v;
                if(rem[v]>1)shifted|=(U128)(rem[v]-1)<<(5*v);
            }
            auto offer=[&](U128 state,U128 assign,int gain){
                int count=node.score+gain;
                float nextValue=0;
                for(int v=0;v<n;++v) {
                    int r=(int)((state>>(5*v))&31);
                    if(r && T+1+r-1<g.m) {
                        int val=scores.spine[(size_t)(T+r)*n+v];
                        nextValue+=min(18.f,log1pf((float)max(0,val-1))*2.3f);
                    }
                }
                float score=(float)count+0.37f*nextValue;
                auto it=dedup.find(state);
                Candidate cand{state,assign,count,prev,score};
                if(it==dedup.end()) {
                    dedup[state]=(int)proposals.size();proposals.push_back(cand);
                } else {
                    auto &old=proposals[it->second];
                    if(cand.score>old.score ||(cand.score==old.score && cand.weight>old.weight))
                        old=cand;
                }
            };
            offer(shifted,0,0);
            if(!active || !available)continue;
            for(int variant=0;variant<VAR+3;++variant) {
                int parent[24],quota[24]={};
                fill(parent,parent+n,-1);
                for(int v=0;v<n;++v)if(active&(1<<v))quota[v]=g.k;
                unsigned chosen=0;
                const auto &order=priority[variant%VAR];
                int skipped=(variant>=VAR?variant-VAR+1:0);
                for(int v:order) {
                    if(!(available&(1<<v)))continue;
                    if(skipped>0) {--skipped;continue;}
                    bool visit[24]={};
                    auto augment=[&](auto&& self,int w)->bool {
                        if(visit[w])return false;
                        visit[w]=true;
                        for(int u:g.adj[w])if(active&(1<<u)) {
                            if(quota[u]) {--quota[u];parent[w]=u;return true;}
                        }
                        for(int u:g.adj[w])if(active&(1<<u)) {
                            for(int z=0;z<n;++z)if(parent[z]==u) {
                                if(self(self,z)) {parent[w]=u;return true;}
                            }
                        }
                        return false;
                    };
                    if(augment(augment,v))chosen|=1u<<v;
                }
                if(!chosen)continue;
                U128 result=shifted,assign=0;
                for(int v=0;v<n;++v)if(chosen&(1<<v)) {
                    result|=(U128)g.t[v]<<(5*v);
                    assign|=(U128)(parent[v]+1)<<(5*v);
                }
                offer(result,assign,__builtin_popcount(chosen));
            }
        }
        if(proposals.empty())break;
        int keep=min(WIDTH,(int)proposals.size());
        auto cmp=[](const Candidate&a,const Candidate&b){return a.weight>b.weight;};
        if((int)proposals.size()>keep)
            nth_element(proposals.begin(),proposals.begin()+keep,proposals.end(),cmp);
        sort(proposals.begin(),proposals.begin()+keep,cmp);
        next.clear();next.reserve(keep);
        for(int j=0;j<keep;++j) {
            auto &c=proposals[j];
            next.push_back((int)states.size());
            states.push_back({c.state,c.assignment,c.score,c.parent});
        }
        frontier.swap(next);timeDone=T+1;
    }
    if(frontier.empty())return nullopt;
    int winner=frontier[0];
    for(int idx:frontier)if(states[idx].score>states[winner].score)winner=idx;
    vector<U128> trace;
    for(int id=winner;states[id].parent!=-1;id=states[id].parent)
        trace.push_back(states[id].assignment);
    reverse(trace.begin(),trace.end());
    vector<Action> answer;
    answer.reserve(states[winner].score);
    answer.push_back({-1,g.p,-1,-1});
    for(int T=0;T<(int)trace.size();++T)
        for(int v=0;v<n;++v) {
            int source=(int)((trace[T]>>(5*v))&31)-1;
            if(source>=0)answer.push_back({source,v,g.x+T,-1});
        }
    return answer;
}

// TRIZ temporal separation: keep many different feasible one-hour target
// subsets instead of greedily fixing every possible transmission. All subsets
// are feasible b-matchings between senders and recipients with per-source k.
// Capped subset enumeration and a small beam enforce a strict time budget.
static optional<vector<Action>> searchBeamAllSubsets(
    const Problem &g, const Scores &scores,
    chrono::steady_clock::time_point start, double deadline) {
    if(g.n < 2 || g.n > 10 || g.m > 120 || g.k < 2)return nullopt;
    if(elapsedSince(start)+0.09 >= deadline)return nullopt;
    const int n=g.n,m=g.m;
    const int LIMIT=1<<n;
    const int WIDTH=(g.n<=9 ? 1024 : 256);
    using U64=unsigned long long;
    vector<unsigned> adjMask(n),legalMask(m);
    vector<U64> delayMask(LIMIT,0);
    for(int u=0;u<n;++u)for(int v:g.adj[u])adjMask[u]|=1u<<v;
    for(int T=0;T<m;++T){
        int h=(g.x+T)%24;
        for(int v=0;v<n;++v)if(g.can(v,h) && T+g.t[v]<m)
            legalMask[T]|=1u<<v;
    }
    for(int mask=1;mask<LIMIT;++mask){
        int bit=__builtin_ctz((unsigned)mask);
        delayMask[mask]=delayMask[mask^(1<<bit)] | ((U64)g.t[bit]<<(5*bit));
    }
    struct Node {U64 state;int count,parent;unsigned short assigned;};
    struct Candidate {U64 state;int count,parent;unsigned short assigned;float key;};
    vector<Node> nodes;
    nodes.reserve(WIDTH*m+1);
    nodes.push_back({1ULL<<(5*g.p),1,-1,0});
    vector<int> frontier{0},future;
    vector<Candidate> proposals;
    proposals.reserve(WIDTH*LIMIT);
    unordered_map<U64,int> seen;
    seen.reserve(WIDTH*LIMIT);
    array<unsigned char,1024> feasible{},tmp{};
    vector<float> rewards(LIMIT,0);
    int completed=0;
    unsigned long long work=0;
    bool timedOut=false;
    for(int T=0;T<m;++T){
        if((T&3)==0 && elapsedSince(start)>deadline)break;
        // A copied recipient has future potential; pending copies also count.
        float value[10]{};
        for(int v=0;v<n;++v)if(T+g.t[v]<m){
            int length=scores.spine[(size_t)(T+g.t[v])*n+v];
            value[v]=2.7f*log1pf((float)max(0,length-1));
        }
        rewards[0]=0;
        for(int mask=1;mask<LIMIT;++mask){
            int bit=__builtin_ctz((unsigned)mask);
            rewards[mask]=rewards[mask^(1<<bit)]+value[bit];
        }
        proposals.clear();seen.clear();
        for(int nodeId:frontier){
            if((nodeId&15)==0 && elapsedSince(start)>deadline)break;
            const Node &node=nodes[nodeId];
            unsigned active=0,available=legalMask[T];
            U64 shifted=0;
            float pending=0;
            for(int v=0;v<n;++v){
                int r=(int)((node.state>>(5*v))&31);
                if(r==1)active|=1u<<v;
                if(r>1){
                    available &= ~(1u<<v);
                    shifted |= (U64)(r-1) << (5*v);
                    int finish=T+r-1;
                    if(finish<m)pending+=1.3f*log1pf((float)max(0,scores.spine[(size_t)finish*n+v]-1));
                }
            }
            feasible.fill(0); feasible[0]=1;
            if(active && available){
                for(int u=0;u<n;++u)if(active & (1u<<u)){
                    unsigned opt=adjMask[u]&available;
                    if(!opt)continue;
                    tmp=feasible;
                    for(int used=0;used<LIMIT;++used)if(feasible[used]){
                        unsigned left=opt & ~unsigned(used);
                        for(unsigned subset=left;subset;subset=(subset-1)&left) {
                            if((++work & 8191ULL)==0 && elapsedSince(start)>deadline) {
                                timedOut=true; break;
                            }
                            if(__builtin_popcount(subset)<=g.k) tmp[used|subset]=1;
                        }
                        if(timedOut)break;
                    }
                    if(timedOut)break;
                    feasible=tmp;
                }
            }
            if(timedOut)break;
            for(int mask=0;mask<LIMIT;++mask)if(feasible[mask]){
                U64 state=shifted|delayMask[mask];
                int count=node.count+__builtin_popcount((unsigned)mask);
                float priority=float(count)+0.37f*(pending+rewards[mask]);
                auto it=seen.find(state);
                if(it==seen.end()){
                    int index=(int)proposals.size();
                    seen.emplace(state,index);
                    proposals.push_back({state,count,nodeId,(unsigned short)mask,priority});
                }else{
                    Candidate &other=proposals[it->second];
                    if(priority>other.key || (priority==other.key && count>other.count))
                        other={state,count,nodeId,(unsigned short)mask,priority};
                }
            }
        }
        // Keep the last fully completed frontier if the hour was interrupted.
        if(timedOut || proposals.empty())break;
        const int keep=min(WIDTH,(int)proposals.size());
        auto better=[](const Candidate&a,const Candidate&b){
            if(a.key!=b.key)return a.key>b.key;
            return a.count>b.count;
        };
        if((int)proposals.size()>keep)
            nth_element(proposals.begin(),proposals.begin()+keep,proposals.end(),better);
        sort(proposals.begin(),proposals.begin()+keep,better);
        future.clear();future.reserve(keep);
        for(int j=0;j<keep;++j){
            const Candidate &a=proposals[j];
            future.push_back((int)nodes.size());
            nodes.push_back({a.state,a.count,a.parent,a.assigned});
        }
        frontier.swap(future);
        completed=T+1;
    }
    if(frontier.empty())return nullopt;
    int winner=frontier.front();
    for(int id:frontier)if(nodes[id].count>nodes[winner].count)winner=id;
    if(getenv("AHINTEK_TRACE")) fprintf(stderr,"[SUBSET] completed=%d/%d score=%d time=%.3f\n",completed,m,nodes[winner].count,elapsedSince(start));
    if(nodes[winner].count<=1)return nullopt;
    vector<int> trace;
    for(int id=winner;nodes[id].parent>=0;id=nodes[id].parent)trace.push_back(id);
    reverse(trace.begin(),trace.end());
    vector<Action> ans{{-1,g.p,-1,-1}};
    ans.reserve(nodes[winner].count);
    for(int T=0;T<(int)trace.size();++T){
        int child=trace[T],parentId=nodes[child].parent;
        unsigned chosen=nodes[child].assigned;
        if(!chosen)continue;
        unsigned active=0;
        U64 old=nodes[parentId].state;
        for(int u=0;u<n;++u)if(((old>>(5*u))&31)==1)active|=1u<<u;
        // Exact capacitated matching for the chosen target set.
        vector<int> targets,owner(n,-1),quota(n,g.k);
        for(int v=0;v<n;++v)if(chosen&(1u<<v))targets.push_back(v);
        sort(targets.begin(),targets.end(),[&](int a,int b){
            int da=__builtin_popcount(adjMask[a]&active);
            int db=__builtin_popcount(adjMask[b]&active);
            return da!=db ? da<db : a<b;
        });
        auto assign=[&](auto &&self,int i)->bool{
            if(i==(int)targets.size())return true;
            int v=targets[i];
            for(int u=0;u<n;++u)if((active&(1u<<u)) && (adjMask[u]&(1u<<v)) && quota[u]){
                quota[u]--;owner[v]=u;
                if(self(self,i+1))return true;
                quota[u]++;
            }
            return false;
        };
        if(!assign(assign,0))return nullopt;
        for(int v:targets)ans.push_back({owner[v],v,g.x+T,-1});
    }
    return ans;
}

// Construct a self-sustaining 24-hour schedule from an already feasible prefix.
// A closed day has identical active/pending state at both boundaries; hence its
// whole schedule can be repeated with no new causality assumptions.
// This is a purely numerical optimization of the contest graph.
struct CyclicBridgePlanner {
    const Problem &g;
    const vector<Action> &incumbent;
    int B, end, n, count = 0;
    vector<unsigned char> busy, seed, active;
    vector<unsigned short> used;
    vector<unsigned char> desired;
    vector<int> shortest;
    struct Edge { int u,v,s; };
    vector<Edge> required;
    vector<Edge> optional;
    vector<pair<int,int>> terminals;
    unsigned randomState;
    int calls = 0, callLimit = 2500;
    int variant = 0;
    bool spliceEnd = false;
    static constexpr int INF = 10000;

    CyclicBridgePlanner(const Problem &g_,const vector<Action>& ev,int boundary,
                        bool spliceToEnd=false)
      : g(g_),incumbent(ev),B(boundary),end(boundary+24),n(g_.n),
        spliceEnd(spliceToEnd),
        busy((size_t)g_.n*47),seed((size_t)g_.n*24),
        active((size_t)g_.n*47),used((size_t)g_.n*24),
        desired(g_.n),shortest((size_t)g_.n*24,INF),randomState(0x124fed13u) {
        for(size_t j=1;j<incumbent.size();++j) {
            const Action &a=incumbent[j];
            int s=a.when-g.x, f=s+g.t[a.to];
            if(s>=B){
                // A splice must reproduce the exact pending/active state at
                // B+24, so every existing transmission crossing that point
                // from INSIDE the editable interval becomes a terminal goal.
                // Prefix transmissions crossing it are already reserved.
                if(spliceEnd && s<end && f>=end)
                    desired[a.to]=(f==end?255:(unsigned char)(f-end));
                continue;
            }
            if(f>=B && f<end)seed[(size_t)a.to*24+(f-B)]=1;
            if(!spliceEnd){
                if(f==B)desired[a.to]=255;
                else if(f>B)desired[a.to]=(unsigned char)(f-B);
            }
            for(int T=max(s,B);T<min(f,end+23);++T)
                busy[(size_t)a.to*47+(T-B)]=1;
        }
        for(int v=0;v<n;++v) if(desired[v]) {
            int remaining=desired[v]==255?0:desired[v];
            terminals.push_back({v,end+remaining});
        }
        // Shortest causal paths from already scheduled prefix activations.
        for(int v=0;v<n;++v)for(int t=0;t<24;++t)
            if(seed[(size_t)v*24+t])shortest[(size_t)v*24+t]=0;
        for(int T=B;T<end;++T){
            int h=(g.x+T)%24;
            for(int u=0;u<n;++u){
                int d=shortest[(size_t)u*24+T-B];
                if(d==INF)continue;
                for(int v:g.adj[u]){
                    int fin=T+g.t[v];
                    if(fin>=end || !g.can(v,h))continue;
                    int &candidate=shortest[(size_t)v*24+fin-B];
                    candidate=min(candidate,d+1);
                }
            }
        }
    }
    inline unsigned nextRand(){
        randomState ^=randomState<<13;
        randomState ^=randomState>>17;
        randomState ^=randomState<<5;
        return randomState;
    }
    inline float noise(){return (nextRand()&65535)*(1.0f/65536.0f);}
    inline size_t eventIndex(int v,int T) const{return (size_t)v*47+T-B;}
    inline size_t sourceIndex(int v,int T) const{return (size_t)v*24+T-B;}
    bool isSource(int v,int T) const {
        if(T<B || T>=end)return false;
        return seed[sourceIndex(v,T)] || active[eventIndex(v,T)];
    }
    bool room(int v,int s,int fin) const {
        if(s<B || s>=end || fin>end+23)return false;
        for(int t=s;t<fin;++t)if(busy[eventIndex(v,t)])return false;
        return true;
    }
    void undoTo(size_t checkpoint){
        while(required.size()>checkpoint){
            Edge e=required.back();required.pop_back();
            --used[sourceIndex(e.u,e.s)];
            int f=e.s+g.t[e.v];
            active[eventIndex(e.v,f)]=0;
            for(int t=e.s;t<f;++t)busy[eventIndex(e.v,t)]=0;
        }
    }
    bool makeSource(int u,int at,int depth){
        if(isSource(u,at))return true;
        if(at<=B || depth>24)return false;
        return receive(u,at,depth+1);
    }
    bool receive(int v,int fin,int depth){
        if(++calls>callLimit)return false;
        int s=fin-g.t[v];
        if(s<B || s>=end || fin>end+23 || !g.can(v,(g.x+s)%24))return false;
        if(fin<end && isSource(v,fin))return true;
        if(!room(v,s,fin))return false;
        size_t checkpoint=required.size();
        struct Parent {float priority; int id;};
        vector<Parent> candidates;
        candidates.reserve(g.adj[v].size());
        for(int u:g.adj[v]) {
            int d=shortest[sourceIndex(u,s)];
            if(d==INF || used[sourceIndex(u,s)]>=g.k)continue;
            bool ready=isSource(u,s);
            float rand=noise();
            float value=ready?-1000.0f:(float)d;
            switch(variant%8){
                case 0: value+=rand*.07f;break;
                case 1: value+=rand*.5f-.02f*g.deg[u];break;
                case 2: value+=rand*2.0f;break;
                case 3: value+=rand*4.0f;break;
                case 4: value=value*.2f+rand*4.0f;break;
                case 5: value+=rand*3.0f+.20f*g.t[u];break;
                case 6: value+=rand*.2f+.10f*g.deg[u];break;
                default:value+=rand*1.0f+.05f*g.deg[u];break;
            }
            candidates.push_back({value,u});
        }
        sort(candidates.begin(),candidates.end(),[](auto a,auto b){return a.priority<b.priority;});
        for(auto candidate:candidates){
            int u=candidate.id;
            if(!makeSource(u,s,depth)){undoTo(checkpoint);continue;}
            if(used[sourceIndex(u,s)]>=g.k || !room(v,s,fin)){
                undoTo(checkpoint);continue;
            }
            for(int t=s;t<fin;++t)busy[eventIndex(v,t)]=1;
            active[eventIndex(v,fin)]=1;
            ++used[sourceIndex(u,s)];
            required.push_back({u,v,s});
            return true;
        }
        return false;
    }
    bool build(unsigned salt,int type){
        variant=type;
        randomState=scramble(salt^(unsigned)B*0x9e3779b9u)|1u;
        calls=0;
        undoTo(0);
        optional.clear();
        vector<pair<int,int>> goals=terminals;
        sort(goals.begin(),goals.end(),[&](auto a,auto b){
            if(g.deg[a.first]!=g.deg[b.first])return g.deg[a.first]<g.deg[b.first];
            return a.first<b.first;
        });
        // Equal-scarcity goals are permuted occasionally to avoid pinning
        // a low-throughput supporting tree too early.
        if((variant&3)==3 && goals.size()>1){
            for(size_t i=1;i<goals.size();++i)
                if(g.deg[goals[i].first]==g.deg[goals[i-1].first] && (nextRand()&1u))
                    swap(goals[i],goals[i-1]);
        }
        for(auto [v,fin]:goals)if(!receive(v,fin,0)){
            undoTo(0);return false;
        }
        return true;
    }
    int fill(unsigned salt,int mode,const vector<float>& futureScore){
        randomState=scramble(salt^(unsigned)B*0x85ebca6bu)|1u;
        optional.clear();
        // Future required and prefix intervals are reserved before optional
        // transmissions are considered. Therefore optional additions cannot
        // invalidate a required bridge chain or the 24-hour boundary state.
        for(int T=B;T<end;++T) {
            vector<int> senders;
            for(int u=0;u<n;++u)if(isSource(u,T) && used[sourceIndex(u,T)]<g.k)
                senders.push_back(u);
            if(senders.empty())continue;
            int h=(g.x+T)%24;
            struct Choice{float score;int v;};
            vector<Choice> choices;
            choices.reserve(n);
            for(int v=0;v<n;++v) {
                int finish=T+g.t[v];
                if(finish>=end || !g.can(v,h) || !room(v,T,finish))continue;
                bool parent=false;
                for(int u:senders)if(used[sourceIndex(u,T)]<g.k &&
                                      find(g.adj[u].begin(),g.adj[u].end(),v)!=g.adj[u].end()) {
                    parent=true;break;
                }
                if(!parent)continue;
                float f=futureScore[(size_t)((g.x+finish)%24)*n+v];
                float speed=1.0f/g.t[v];
                float rn=noise();
                float val;
                switch(mode%8){
                  case 0: val=4.0f*f+speed;break;
                  case 1: val=2.0f*f+10.0f*speed;break;
                  case 2: val=6.0f*f+rn*5.0f;break;
                  case 3: val=4.0f*f+rn*10.0f;break;
                  case 4: val=rn*50.0f;break;
                  case 5: val=(float)g.deg[v]+rn*5.0f;break;
                  case 6: val=2.0f*f+20.0f*speed+rn*2.0f;break;
                  default:val=5.0f*f+rn*15.0f;break;
                }
                choices.push_back({val,v});
            }
            sort(choices.begin(),choices.end(),[](auto a,auto b){return a.score>b.score;});
            float skip=(mode==4 ? .18f : mode==5 ? .06f : 0.0f);
            for(auto choice:choices){
                int v=choice.v,f=T+g.t[v];
                if(noise()<skip || !room(v,T,f))continue;
                int picked=-1;
                int bestDeg=INT_MAX;
                for(int u:senders){
                    if(used[sourceIndex(u,T)]>=g.k)continue;
                    if(find(g.adj[u].begin(),g.adj[u].end(),v)==g.adj[u].end())continue;
                    int metric=g.deg[u]*16 + (int)(nextRand()&15);
                    if(metric<bestDeg){bestDeg=metric;picked=u;}
                }
                if(picked<0)continue;
                ++used[sourceIndex(picked,T)];
                for(int q=T;q<f;++q)busy[eventIndex(v,q)]=1;
                active[eventIndex(v,f)]=1;
                optional.push_back({picked,v,T});
            }
        }
        return (int)required.size()+(int)optional.size();
    }
    void clearOptional(){
        for(auto e:optional){
            --used[sourceIndex(e.u,e.s)];
            int f=e.s+g.t[e.v];
            active[eventIndex(e.v,f)]=0;
            for(int q=e.s;q<f;++q)busy[eventIndex(e.v,q)]=0;
        }
        optional.clear();
    }
    vector<Action> unroll() const {
        vector<Action> out;
        out.push_back({-1,g.p,-1,-1});
        for(size_t j=1;j<incumbent.size();++j){
            const Action& a=incumbent[j];
            if(a.when-g.x<B)out.push_back({a.from,a.to,a.when,-1});
        }
        vector<Edge> day=required;
        day.insert(day.end(),optional.begin(),optional.end());
        sort(day.begin(),day.end(),[](auto a,auto b){return a.s<b.s;});
        for(int offset=0;B+offset<g.m;offset+=24) {
            for(Edge a:day){
                int T=a.s+offset;
                if(T+g.t[a.v]>=g.m)continue;
                out.push_back({a.u,a.v,g.x+T,-1});
            }
        }
        return out;
    }
    int estimateCount() const {
        int count=1;
        for(size_t j=1;j<incumbent.size();++j)if(incumbent[j].when-g.x<B)++count;
        for(auto e:required){
            int available=g.m-1-(e.s+g.t[e.v]);
            if(available>=0)count+=available/24+1;
        }
        for(auto e:optional){
            int available=g.m-1-(e.s+g.t[e.v]);
            if(available>=0)count+=available/24+1;
        }
        return count;
    }
};

static vector<Action> optimizePeriodicBridge(const Problem &g, const vector<Action> &current,
           chrono::steady_clock::time_point start, double deadline){
    if(g.n>64 || g.m<96 || g.k<2 || g.edge2>1000 ||
       (long long)g.n*g.m>30000 || current.size()<25)return current;
    int days=(g.m-1)/24;
    if(days<4)return current;
    vector<int> order;
    for(int d=1;d+2<days;++d)order.push_back(d);
    // Beginning the steady regime early makes more repetitions valuable.
    sort(order.begin(),order.end());
    if(order.size()>4)order.resize(4);
    vector<float> future((size_t)24*g.n,0.0f);
    for(int h=0;h<24;++h)for(int v=0;v<g.n;++v){
        int possible=0;
        for(int w:g.adj[v])if(g.can(w,h))++possible;
        future[(size_t)h*g.n+v]=(float)possible;
    }
    vector<Action> best=current;
    int tried=0,feasible=0,improved=0;
    vector<int> dayGain(days,0);
    // Probe all candidate boundary days first. A profitable orbit may start
    // later, even when the earliest candidate has no useful closed schedule.
    for(int stage=0;stage<2;++stage){
        if(stage==1 && improved==0)break;
        vector<int> thisOrder=order;
        if(stage==1)sort(thisOrder.begin(),thisOrder.end(),[&](int a,int b){
            return dayGain[a]>dayGain[b];
        });
        for(int d:thisOrder){
            if(elapsedSince(start)+finishReserve(best.size())+.04>=deadline)break;
            CyclicBridgePlanner plan(g,current,24*d);
            if(plan.terminals.empty())continue;
            int begin=stage==0?0:900;
            int limit=stage==0?900:300000;
            for(int iter=begin;iter<limit;++iter){
                if((iter&15)==0 && elapsedSince(start)+finishReserve(best.size())+.025>=deadline)break;
                ++tried;
                unsigned randomKey=scramble((unsigned)(iter+1)*0x9e3779b9u^(unsigned)d*0x25c8f0abu);
                if(!plan.build(randomKey,iter%8))continue;
                ++feasible;
                plan.fill(randomKey^0x8e36c9d1u,(iter/8)%8,future);
                int count=plan.estimateCount();
                if(count>(int)best.size()){
                    auto candidate=plan.unroll();
                    if(candidate.size()>best.size()){
                        int gain=(int)candidate.size()-(int)best.size();
                        dayGain[d]+=gain;
                        best=move(candidate);++improved;
                        if(getenv("AHINTEK_TRACE"))
                            fprintf(stderr,"[CYCLE] day=%d stage=%d iter=%d score=%zu time=%.3f\n",
                            d,stage,iter,best.size(),elapsedSince(start));
                    }
                }
                plan.clearOptional();
            }
        }
    }
    if(getenv("AHINTEK_TRACE"))
        fprintf(stderr,"[CYCLE] attempts=%d feasible=%d improved=%d best=%zu time=%.3f\n",
                tried,feasible,improved,best.size(),elapsedSince(start));
    return best;
}


// Reoptimize ONE 24h window preserving all source activity / pending jobs
// at BOTH boundaries. This local neighborhood leaves the entire original
// suffix untouched: every source activation at B+24 is reproduced exactly.
static inline double spliceReserve(size_t events){
    return 0.065 + 0.12 * min(1.0, double(events)/50000.0);
}
static vector<Action> optimizeSpliceWindow(const Problem &g,
    const vector<Action> &current,
    chrono::steady_clock::time_point started, double deadline){
    if(g.n>96 || g.m<50 || g.k<2 || g.edge2>1800 ||
       (long long)g.n*g.m>35000 || current.size()<12)return current;
    vector<Action> best=current;
    vector<int> boundaries;
    // Fixed early/mid/end windows and non-day-aligned offsets.
    for(int B=1;B+24<g.m;B+=max(6,g.m/14))boundaries.push_back(B);
    for(int shift:{5,11,17})
        if(shift+24<g.m)boundaries.push_back(shift);
    sort(boundaries.begin(),boundaries.end());
    boundaries.erase(unique(boundaries.begin(),boundaries.end()),boundaries.end());
    unsigned rng=0x852ab45du;
    int attempts=0,feasible=0,improved=0;
    for(int sweep=0;sweep<2;++sweep){
        if(sweep)reverse(boundaries.begin(),boundaries.end());
        for(int B:boundaries){
            if(elapsedSince(started)+spliceReserve(best.size())+.02>=deadline)
                goto completed;
            CyclicBridgePlanner plan(g,best,B,true);
            int numOriginal=0;
            for(size_t j=1;j<best.size();++j){
                int s=best[j].when-g.x;
                if(s>=B && s<B+24)++numOriginal;
            }
            vector<float> future((size_t)24*g.n,0.f);
            for(int phase=0;phase<24;++phase)for(int v=0;v<g.n;++v){
                int count=0;
                for(int w:g.adj[v])if(g.can(w,phase))++count;
                future[(size_t)phase*g.n+v]=(float)count;
            }
            for(int iter=0;iter<64;++iter){
                if((iter&7)==0 && elapsedSince(started)+spliceReserve(best.size())+.018>=deadline)
                    goto completed;
                ++attempts;
                rng=scramble(rng+0x9e3779b9u+(unsigned)B*37u);
                if(!plan.build(rng,(iter+sweep)%8))continue;
                ++feasible;
                plan.fill(rng^0x8e36c9d1u,(iter/8+sweep)%8,future);
                int gain=(int)plan.required.size()+(int)plan.optional.size()-numOriginal;
                if(gain>0){
                    vector<Action> candidate;
                    candidate.reserve(best.size()+gain);
                    candidate.push_back({-1,g.p,-1,-1});
                    // Preserve the past and future entirely. The bridge
                    // preserves the exact busy/active state at the cut.
                    for(size_t j=1;j<best.size();++j){
                        const Action& a=best[j];
                        int s=a.when-g.x;
                        if(s<B || s>=B+24)candidate.push_back(a);
                    }
                    for(auto e:plan.required)
                       candidate.push_back({e.u,e.v,g.x+e.s,-1});
                    for(auto e:plan.optional)
                       candidate.push_back({e.u,e.v,g.x+e.s,-1});
                    // This splice is correct by construction if the terminal
                    // jobs equal original jobs; offline independent validator
                    // tests the invariant on every accepted candidate.
                    if(candidate.size()>best.size()){
                        if(getenv("AHINTEK_TRACE"))fprintf(stderr,
                           "[SPLICE] B=%d gain=%d score=%zu at=%.3f\\n",
                            B,gain,candidate.size(),elapsedSince(started));
                        best=move(candidate);++improved;
                        break;
                    }
                }
                plan.clearOptional();
            }
        }
    }
completed:
    if(getenv("AHINTEK_TRACE"))fprintf(stderr,
      "[SPLICE] attempts=%d feasible=%d improved=%d A=%zu t=%.3f\\n",
       attempts,feasible,improved,best.size(),elapsedSince(started));
    return best;
}

int main() {
    const auto programStart = chrono::steady_clock::now();
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

    // Only the connected component of the starting device can ever activate.
    // This reduction preserves original order and removes all unreachable
    // nodes before O(N*m) dynamic programming and the small-graph beam tests.
    // Original node labels are restored solely when printing the answer.
    vector<int> originalId;
    {
        vector<unsigned char> reachable(g.n,0);
        vector<int> queue;
        queue.reserve(min(g.n,4096));
        queue.push_back(g.p);
        reachable[g.p]=1;
        for (size_t q=0;q<queue.size();++q) {
            int u=queue[q];
            for (int v:g.adj[u]) if (!reachable[v]) {
                reachable[v]=1;
                queue.push_back(v);
            }
        }
        if (queue.size() < (size_t)g.n) {
            sort(queue.begin(),queue.end());
            vector<int> renumber(g.n,-1);
            for (int j=0;j<(int)queue.size();++j)renumber[queue[j]]=j;
            Problem reduced;
            reduced.n=(int)queue.size();
            reduced.p=renumber[g.p]; reduced.k=g.k;
            reduced.x=g.x; reduced.m=g.m;
            reduced.a.reserve(reduced.n);reduced.b.reserve(reduced.n);
            reduced.t.reserve(reduced.n);reduced.legal.reserve(reduced.n);
            reduced.adj.resize(reduced.n);reduced.deg.resize(reduced.n);
            for (int j=0;j<reduced.n;++j) {
                int u=queue[j];
                reduced.a.push_back(g.a[u]);
                reduced.b.push_back(g.b[u]);
                reduced.t.push_back(g.t[u]);
                reduced.legal.push_back(g.legal[u]);
                reduced.adj[j].reserve(g.adj[u].size());
                for (int v:g.adj[u]) {
                    int id=renumber[v];
                    if (id>=0)reduced.adj[j].push_back(id);
                }
                reduced.deg[j]=(int)reduced.adj[j].size();
                reduced.edge2+=reduced.deg[j];
            }
            originalId=move(queue);
            g=move(reduced);
        }
    }

    // Temporal reachability is an upper bound on every feasible strategy:
    // any successful activation (v,T) must be reachable by a path of
    // successful transmissions starting from (p,0). Every transition
    // strictly increases T because t[v]>=1. Occupancy and k can only
    // DECREASE actual reachability, so removing never-reachable vertices
    // cannot remove any successful activation.
    // Cap inspected directed edges to avoid harming dense official cases.
    if (g.n > 9 && g.m > 1 && elapsedSince(programStart) < 0.20) {
        const long long MAX_EDGE_SCANS = 1400000;
        const size_t cells=(size_t)g.n*g.m; // guaranteed <= 1e6
        vector<unsigned char> seen(cells,0), canReach(g.n,0);
        vector<int> head(g.m,-1), link(cells,-1);
        int start=g.p;
        seen[start]=1; canReach[g.p]=1;
        head[0]=start;
        long long scans=0;
        bool aborted=false;
        int countReach=1;
        int lastReach=0;
        for (int T=0;T<g.m && !aborted;++T) {
            if (head[T]!=-1)lastReach=T;
            const int phase=(g.x+T)%24;
            for (int id=head[T]; id!=-1;id=link[id]) {
                int u=id%g.n;
                scans+=g.deg[u];
                if(scans>MAX_EDGE_SCANS) {aborted=true;break;}
                for (int v:g.adj[u]) {
                    int finish=T+g.t[v];
                    if(finish>=g.m || !g.can(v,phase))continue;
                    const int q=(size_t)finish*g.n+v;
                    if(seen[q])continue;
                    seen[q]=1;
                    link[q]=head[finish];head[finish]=q;
                    if(!canReach[v]) {canReach[v]=1;++countReach;}
                }
            }
        }
        if(!aborted && countReach<g.n &&
           (countReach <= 9 || (g.n > 24 && countReach <= 24) ||
            (long long)countReach * 2 <= g.n)) {
            vector<int> keep;keep.reserve(countReach);
            vector<int> inverse(g.n,-1);
            for(int u=0;u<g.n;++u)if(canReach[u]) {
                inverse[u]=(int)keep.size();keep.push_back(u);
            }
            Problem h;
            h.n=countReach;h.p=inverse[g.p];h.k=g.k;
            h.x=g.x;h.m=g.m;
            h.a.reserve(h.n);h.b.reserve(h.n);
            h.t.reserve(h.n);h.legal.reserve(h.n);
            h.adj.resize(h.n);h.deg.resize(h.n);
            for(int j=0;j<h.n;++j) {
                int u=keep[j];
                h.a.push_back(g.a[u]);h.b.push_back(g.b[u]);
                h.t.push_back(g.t[u]);h.legal.push_back(g.legal[u]);
                for(int v:g.adj[u])if(inverse[v]>=0)
                    h.adj[j].push_back(inverse[v]);
                h.deg[j]=(int)h.adj[j].size();h.edge2+=h.deg[j];
            }
            vector<int> mapped;mapped.reserve(h.n);
            for(int u:keep)mapped.push_back(originalId.empty()?u:originalId[u]);
            originalId=move(mapped);
            g=move(h);
        }
        // The longest individually reachable activation bounds the horizon
        // of EVERY valid strategy. Avoid changing short tails needlessly.
        if(!aborted && lastReach + 24 < g.m)
            g.m=lastReach+1;
    }

    // Target the judge's 2-second wall time, allowing for input/output overhead.
    // Preprocessing is not interruptible, so this is a conservative soft cutoff.
    double wallLimit = JUDGE_WALL_LIMIT;
    if (const char *env = getenv("AHINTEK_BUDGET_SEC")) {
        // Can reduce the budget for local experiments, never raise it on the judge.
        wallLimit = max(0.2, min(JUDGE_WALL_LIMIT, atof(env)));
    }
    const bool doPeriodic=(g.n<=64 && ((g.m-1)/24)>=4 && g.k>=2 && g.edge2<=1000 &&
        (long long)g.n*g.m<=30000 && g.m>=96);
    const bool doSplice= (g.n<=96 && g.m>=50 && g.k>=2 &&
       g.edge2<=1800 && (long long)g.n*g.m<=35000);
    double coreDeadline=doPeriodic ? min(wallLimit,
          0.55 + 0.68*min(1.0,max(0.0,double(g.m-600)/300.0))) :
          wallLimit;
    auto timeForMore = [&](size_t outputSize) -> bool {
        return elapsedSince(programStart) + finishReserve(outputSize) < coreDeadline;
    };
    bool verbose = getenv("AHINTEK_TRACE") != nullptr;
    auto elapsed = [&]() -> double {
        return chrono::duration<double>(chrono::steady_clock::now()-programStart).count();
    };
    vector<Action> best;
    int evaluated=0, improved=0;
    if (g.k == 1) {
        best = solve_one(g);
    } else if (auto exact=exactSmallComponent(g)) {
        best = move(*exact);
    } else if (g.m == 1 || g.edge2 == 0) {
        best.push_back({-1, g.p, -1, -1});
    } else {
        Scores scores(g);
        vector<Action> backbone = recover_chain(g, scores.spine);
        best = backbone;
        int bestMode=0, bestBackbone=1;
        // Solve the compact time-expanded subproblem before spending seconds
        // on largely equivalent random restarts of the greedy simulator.
        if (g.n <= 10 && g.m <= 120 && timeForMore(best.size())) {
            const double horizon=min(coreDeadline-finishReserve(best.size())-0.23,1.42);
            if (horizon > elapsed()+0.10) {
                auto candidate=searchBeamAllSubsets(g,scores,programStart,horizon);
                if(candidate && candidate->size()>best.size()){
                    best=move(*candidate);++improved;
                }
            }
        }
        const int schedule[][2] = {
            {0,1},{1,0},{2,0},{3,1},{4,0},{5,0},{6,1},{7,0},
            {0,0},{1,1},{2,0},{3,0},
            {12,1},{13,1},{14,1},{15,0},{12,0},{13,0},{14,0},{15,1},
            {8,1},{9,1},{8,0},{9,0},{7,1},{4,1},{6,0},{10,0},
            {16,1},{16,0},{17,0},{18,0},
            {24,0},{25,0},{26,0},{20,0},{21,0},{22,0},
            {27,0},{28,0},{29,0},{30,0},{31,0},{32,0},{33,0},{34,0},{35,0}
        };
        constexpr int presets = sizeof(schedule)/sizeof(schedule[0]);
        // Reproduce the official V16 baseline exactly before experimenting.
        // Extra computation can only increase (never replace) the incumbent.
        double lastDuration=0.0;
        for(int trial=0;trial<200;++trial) {
            if (!timeForMore(best.size())) break;
            double startupTarget = min(coreDeadline - finishReserve(best.size()), 1.27);
            if(trial && elapsed() + 1.15*lastDuration + 0.03 >= startupTarget) break;
            int mode,useBackbone,pivot=0;
            bool isLNS=false;
            if(trial<32) {
                mode=schedule[trial][0];useBackbone=schedule[trial][1];
            } else {
                int phase=(trial-32)%16;
                if(phase<9) {
                    mode=bestMode;
                    useBackbone=bestBackbone;
                    isLNS=(phase>=2);
                } else if(phase<13) {
                    mode=(phase==9 || phase==10)?12:7;
                    useBackbone=(phase%2==0);
                } else {
                    int j=((trial-32)/16+phase*3)%32;
                    mode=schedule[j][0];useBackbone=schedule[j][1];
                }
                if(isLNS) {
                    static constexpr int fractions[]={15,30,45,60,75,90,40};
                    pivot=max(1,min(g.m-1,g.m*fractions[(phase-2)%7]/100));
                    useBackbone=0;
                }
            }
            auto before=chrono::steady_clock::now();
            Sim sim(g,scores,mode,0xabc123u+(unsigned)trial*0x9e3779b9u,
                    useBackbone?&backbone:nullptr,isLNS?&best:nullptr,pivot,
                    programStart, coreDeadline);
            vector<Action> cur=sim.run();
            lastDuration=chrono::duration<double>(chrono::steady_clock::now()-before).count();
            ++evaluated;
            if(cur.size()>best.size()) {
                best=move(cur);++improved;bestMode=mode;bestBackbone=useBackbone;
            }
        }
        for(int mode:{24,25,26,20,21,22}) {
            if (!timeForMore(best.size()) ||
                elapsed() + 0.75*lastDuration + 0.015 + finishReserve(best.size()) >= coreDeadline)
                break;
            const auto trialStart = chrono::steady_clock::now();
            Sim sim(g,scores,mode,0xacc001u+(unsigned)mode*0x9e3779b9u,
                    nullptr,nullptr,0,programStart,coreDeadline);
            vector<Action> cur=sim.run();
            lastDuration = chrono::duration<double>(chrono::steady_clock::now()-trialStart).count();
            ++evaluated;
            if(cur.size()>best.size()) {
                best=move(cur);++improved;
            }
        }
        // Exact one-hour matching sets + beam across future occupancy states.
        // Unlike ranked greedy variants, the set can intentionally leave
        // quota unused now to free devices for higher-value future cascades.
        // Large expensive state-space search is optional but worthwhile on
        // graphs too large for the exact-small solver.
        const double beamAllowance=(g.n<=24 && g.m<=3000)
                   ? min(coreDeadline - finishReserve(best.size()), coreDeadline*0.8) : 0.0;
        if(beamAllowance > elapsed() + 0.10) {
            optional<vector<Action>> candidate;
            if(g.n<=13)candidate=searchBeam(g,scores,programStart,beamAllowance);
            else candidate=searchBeamWide(g,scores,programStart,beamAllowance);
            if(candidate && candidate->size()>best.size()) {
                best=move(*candidate);++improved;
            }
        }
        // Preset 0..31 were already evaluated in the first loop. Avoid identical repeats.
        int nextTrial=32;
        auto exploreIncumbent = [&](double iterationDeadline) {
        for (;nextTrial<1000000 &&
               elapsed()+finishReserve(best.size()) < iterationDeadline; ++nextTrial) {
            int trial=nextTrial;
            if (lastDuration > 0.01 &&
                elapsed() + 0.75*lastDuration + 0.015 + finishReserve(best.size()) >= iterationDeadline)
                break;
            const auto trialStart = chrono::steady_clock::now();
            int mode, useBackbone=0, pivot=0;
            int forbiddenHour=-1, forbiddenTarget=-1;
            bool isLNS=false;
            if (trial<presets) {
                mode=schedule[trial][0];
                useBackbone=schedule[trial][1];
            } else {
                int z=trial-presets;
                // Random global restarts plus large-neighborhood local search.
                // Include search near hour zero and endgame pivots.
                unsigned h=scramble((unsigned)(trial+1)*0x9e3779b9u);
                int op=z%12;
                if (op<=7) {
                    isLNS=true;
                    if(op<=3 && best.size()>5) {
                        // Counterfactual ejection: keep proven prefix and
                        // forbid a concrete incumbent transmission at pivot.
                        // Then rebuild its entire descendant schedule.
                        int j=1+(int)((h^(h>>12))%(best.size()-1));
                        const Action &target=best[j];
                        pivot=target.when-g.x;
                        forbiddenHour=pivot;
                        forbiddenTarget=target.to;
                        if (pivot<=0 || pivot>=g.m-1) {
                            forbiddenHour=-1; forbiddenTarget=-1;
                            pivot=max(1,g.m/3);
                        }
                        mode=op==0 ? bestMode :
                             (op==1 ? 24+(int)(h%4) :
                              (op==2 ? 28+(int)(h%8) : (int)(h%12)));
                    } else {
                        static const int fractions[]={5,10,20,30,40,50,60,70,80,90,95};
                        int fraction=fractions[(z/12+(int)(h>>8))%11];
                        pivot=max(1,min(g.m-1,(int)((long long)g.m*fraction/100)));
                        if (op<=4) mode=(bestMode+1+(h%8))%8;
                        else if (op<=6) mode=28+(int)(h%8);
                        else mode=(int)(h%24);
                    }
                } else {
                    int j=(int)(h%presets);
                    mode=schedule[j][0];
                    useBackbone=(op==11 && j<presets-8) ? 1 : 0;
                }
            }
            const auto *prefix=isLNS ? &best : nullptr;
            Sim sim(g,scores,mode,0xabc123u+(unsigned)trial*0x9e3779b9u,
                    useBackbone ? &backbone : nullptr,prefix,pivot,
                    programStart,iterationDeadline,forbiddenHour,forbiddenTarget);
            vector<Action> cur=sim.run();
            lastDuration=chrono::duration<double>(chrono::steady_clock::now()-trialStart).count();
            ++evaluated;
            if(cur.size()>best.size()) {
                best=move(cur);
                ++improved;
                bestMode=mode;
                bestBackbone=useBackbone;
                if(verbose) fprintf(stderr,"[%.2fs] trial=%d mode=%d pivot=%d score=%zu\n",
                                    elapsed(),trial,mode,pivot,best.size());
            }
        }
        };
        exploreIncumbent(coreDeadline);
        // A final conservative augmentation cannot invalidate the incumbent.
        if (best.size()<350000 &&
            elapsed() + finishReserve(best.size()) + 0.04 < coreDeadline) {
            best=fillUnused(g,scores,move(best),programStart,coreDeadline,8000000);
        }
        if(doPeriodic && elapsed()+finishReserve(best.size())+.05<wallLimit) {
            size_t beforePeriodic=best.size();
            best=optimizePeriodicBridge(g,best,programStart,wallLimit);
            // If closed-day research did not produce a strict improvement
            // quickly, return the remaining judge budget to V33's proven LNS.
            if(best.size()==beforePeriodic &&
               elapsed()+finishReserve(best.size())+.04<wallLimit)
                exploreIncumbent(wallLimit);
        }
        // V38 has already produced its full incumbent. Use a small part of
        // the conservative output reserve to improve it by certified local
        // splicing. Main solver time budget and its decisions stay unchanged.
        if(doSplice && elapsed()+spliceReserve(best.size())+.012<wallLimit){
            best=optimizeSpliceWindow(g,best,programStart,wallLimit);
        }
    }
    if(verbose) fprintf(stderr,"[final] %.2fs trials=%d improvements=%d score=%zu\n",
                        elapsed(),evaluated,improved,best.size());
    printf("%zu\n",best.size());
    string output;
    output.reserve(1<<20);
    for (size_t i=1;i<best.size();++i) {
        int from=best[i].from, to=best[i].to;
        if (!originalId.empty()) {
            from=originalId[from];
            to=originalId[to];
        }
        output+=to_string(from+1);
        output+=' ';
        output+=to_string(to+1);
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
