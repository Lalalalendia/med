#include <bits/stdc++.h>
using namespace std;

struct Solver {
    int n, k, q, used = 0;
    vector<vector<short>> yes, no;
    mt19937_64 rng;

    Solver(int n_, int k_, int q_)
        : n(n_), k(k_), q(q_),
          yes(n_ + 1, vector<short>(n_ + 1, 0)),
          no(n_ + 1, vector<short>(n_ + 1, 0)),
          rng(([] { const char *env = std::getenv("SORT_LIAR_SEED"); return env ? std::strtoull(env, nullptr, 10) : (unsigned long long)chrono::steady_clock::now().time_since_epoch().count(); }())) {}

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
        if (ans) {
            ++yes[x][y];
            ++no[y][x];
        } else {
            ++no[x][y];
            ++yes[y][x];
        }
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

    vector<int> solve() {
        vector<int> start(n);
        iota(start.begin(), start.end(), 1);
        shuffle(start.begin(), start.end(), rng);
        vector<int> a = merge_sort(start, 0, n - 1);
        if (k == 0 || used == q) return a;

        int lg = 32 - __builtin_clz((unsigned)n);
        int h = 32 - __builtin_clz((unsigned)(n - 1));
        int worst_sort = n * h - (1 << h) + 1;

        // A signed vote margin >= k+1 certifies the pair against ANY
        // sequence of at most k lies (even an adaptive adversary).
        bool can_certify =
            1LL * worst_sort + 1LL * k * (n - 1)
            + 1LL * k * (lg + 12) + n / 5 <= q;
        int target = can_certify ? k + 1 : ((k <= 2) ? k + 1 : 2);
        int confidence = 2;

        for (int round = 0;
             round < max(8, 4 * k + 2 * target + 20) && used < q;
             ++round) {
            int fixes = 0, checked = 0;
            for (int i = 0; i + 1 < n && used < q; ++i) {
                int x = a[i], y = a[i + 1];
                if (margin(x, y) >= confidence) continue;
                ++checked;
                if (!verify(x, y)) {
                    ++fixes;
                    if (used + lg + 2 >= q) break;
                    repair(a, i);
                    i = max(-1, i - 3);
                    if (fixes >= max(20, 4 * k + 20)) break;
                }
            }
            if (fixes == 0 && checked == 0) {
                if (confidence >= target) break;
                if (!can_certify && used + n > q) break;
                ++confidence;
            }
        }

        bool certified = true;
        for (int i = 0; i + 1 < n; ++i) {
            if (margin(a[i], a[i + 1]) < k + 1) {
                certified = false;
                break;
            }
        }
        if (certified || used >= q) return a;

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
