#include <bits/stdc++.h>
using namespace std;
using Clock=chrono::steady_clock;
static mt19937_64 RNG(20261121);
struct FastInput {
 static constexpr int SZ=1<<16;
 char b[SZ]; int p=0,n=0;
 inline char c(){if(p==n){n=fread(b,1,SZ,stdin);p=0;if(!n)return 0;}return b[p++];}
 inline int num(){int x=0;char a=c();while(a&&a<'0')a=c();while(a>='0'&&a<='9'){x=x*10+a-'0';a=c();}return x;}
};
struct Solver{
 int n,m; vector<int> R,W,rs,ws,headR,headW,nextR,nextW,toR,toW,cR,cW,xR,xW,ib0,ob0;
 vector<long long> dIn,dOut;
 vector<int> repairOrder1;
 Clock::time_point begun;
 double elapsed()const{return chrono::duration<double>(Clock::now()-begun).count();}
 bool canSpend(double reserve=.2)const{return elapsed()<2.75-reserve;}
 void input(){FastInput in;n=in.num();m=in.num();
  rs.resize(n+2);ws.resize(n+2);headR.assign(m+1,-1);headW.assign(m+1,-1);cR.assign(m+1,0);cW.assign(m+1,0);xR.assign(m+1,0);xW.assign(m+1,0);
  R.reserve(500000);W.reserve(500000);nextR.reserve(500000);nextW.reserve(500000);toR.reserve(500000);toW.reserve(500000);
  for(int i=1;i<=n;i++){int r=in.num(),w=in.num();rs[i]=R.size();ws[i]=W.size();
   while(r--){int l=in.num();R.push_back(l);cR[l]++;xR[l]^=i;nextR.push_back(headR[l]);headR[l]=toR.size();toR.push_back(i);}
   while(w--){int l=in.num();W.push_back(l);cW[l]++;xW[l]^=i;nextW.push_back(headW[l]);headW[l]=toW.size();toW.push_back(i);}
  }rs[n+1]=R.size();ws[n+1]=W.size();
 }
 void degrees(){ib0.assign(n+1,0);ob0.assign(n+1,0);dIn.assign(n+1,0);dOut.assign(n+1,0);
  vector<int> markR(m+1),markW(m+1);
  for(int i=1;i<=n;i++){
   for(int p=rs[i];p<rs[i+1];p++)markR[R[p]]=i;
   for(int p=ws[i];p<ws[i+1];p++)markW[W[p]]=i;
   for(int p=ws[i];p<ws[i+1];p++){int l=W[p],cnt=cR[l]-(markR[l]==i);ib0[i]+=(cnt>0);dIn[i]+=cnt;}
   for(int p=rs[i];p<rs[i+1];p++){int l=R[p],cnt=cW[l]-(markW[l]==i);ob0[i]+=(cnt>0);dOut[i]+=cnt;}
  }
  repairOrder1.resize(n);iota(repairOrder1.begin(),repairOrder1.end(),1);
  sort(repairOrder1.begin(),repairOrder1.end(),[&](int a,int b){return dIn[a]>dIn[b] || (dIn[a]==dIn[b]&&a>b);});
 }
 vector<int> peel(const vector<int>& order,int dynamic=0){
  vector<int> rc=cR,wc=cW,rx=xR,wx=xW,ib=ib0,ob=ob0;
  vector<uint8_t> alive(n+1,1);deque<int> src,sink;
  for(int i=1;i<=n;i++){if(!ib[i])src.push_back(i);if(!ob[i])sink.push_back(i);}
  vector<int> prefix,suffix;prefix.reserve(n);suffix.reserve(n);
  int pos=0;
  for(int remain=n;remain;remain--){
   while(!src.empty()&&!alive[src.front()])src.pop_front();
   while(!sink.empty()&&!alive[sink.front()])sink.pop_front();
   int i;
   if(!src.empty()){i=src.front();src.pop_front();prefix.push_back(i);}
   else if(!sink.empty()){i=sink.front();sink.pop_front();suffix.push_back(i);}
   else {
    while(pos<n&&!alive[order[pos]])pos++;
    if(dynamic==0){i=order[pos++];}
    else {
     int bestId=order[pos];long double bestScore=-1;
     int count=0;
     for(int t=pos;t<n&&count<24;t++)if(alive[order[t]]){
      count++;int tx=order[t];long long a=0,b=0;
      for(int z=ws[tx];z<ws[tx+1];z++)a+=rc[W[z]];
      for(int z=rs[tx];z<rs[tx+1];z++)b+=wc[R[z]];
      long double v=dynamic==1?(long double)a*b:(dynamic==2?min(a,b):
       dynamic==3?(long double)a/(b+1.0L):(long double)b/(a+1.0L));
      if(v>bestScore){bestScore=v;bestId=tx;}
     }
     i=bestId;
    }
   }
   alive[i]=0;
   for(int p=rs[i];p<rs[i+1];p++){
    int l=R[p];rc[l]--;rx[l]^=i;
    if(rc[l]==1 && wc[l]){int only=rx[l];if(alive[only]){
      for(int e=headW[l];e!=-1;e=nextW[e])if(toW[e]==only){if(!--ib[only])src.push_back(only);break;}
    }}else if(rc[l]==0 && wc[l]){
      for(int e=headW[l];e!=-1;e=nextW[e]){int j=toW[e];if(alive[j]&&!--ib[j])src.push_back(j);}
    }
   }
   for(int p=ws[i];p<ws[i+1];p++){
    int l=W[p];wc[l]--;wx[l]^=i;
    if(wc[l]==1 && rc[l]){int only=wx[l];if(alive[only]){
      for(int e=headR[l];e!=-1;e=nextR[e])if(toR[e]==only){if(!--ob[only])sink.push_back(only);break;}
    }}else if(wc[l]==0 && rc[l]){
      for(int e=headR[l];e!=-1;e=nextR[e]){int j=toR[e];if(alive[j]&&!--ob[j])sink.push_back(j);}
    }
   }
  }
  reverse(suffix.begin(),suffix.end());prefix.insert(prefix.end(),suffix.begin(),suffix.end());return prefix;
 }
 // Opposite construction: COMMIT a low-cost vertex on the left/right,
 // immediately excluding only neighbors made impossible by the commit.
 vector<int> pack(const vector<int>& sorted,int mode){
  vector<int> rc=cR,wc=cW,rx=xR,wx=xW,ib=ib0,ob=ob0;
  vector<uint8_t> alive(n+1,1);
  deque<int> sources,sinks;
  for(int i=1;i<=n;i++){if(!ib[i])sources.push_back(i);if(!ob[i])sinks.push_back(i);}
  vector<int> left,right;left.reserve(n);right.reserve(n);
  vector<int> ranking=sorted;
  int rerankAt=n*7/10, rerankCount=0;

  int cursor=0,remaining=n;
  uint64_t packState=0xbafebabe1234567ULL + 19ULL*mode;
  auto erase=[&](int i){
   if(!alive[i])return;
   alive[i]=0;remaining--;
   for(int p=rs[i];p<rs[i+1];p++){
    int l=R[p],rem=--rc[l];rx[l]^=i;
    if(rem==1&&wc[l]){int only=rx[l];if(alive[only]){
      for(int e=headW[l];e!=-1;e=nextW[e])if(toW[e]==only){if(!--ib[only])sources.push_back(only);break;}
    }}else if(rem==0&&wc[l]){
      for(int e=headW[l];e!=-1;e=nextW[e]){int v=toW[e];if(alive[v]&&!--ib[v])sources.push_back(v);}
    }
   }
   for(int p=ws[i];p<ws[i+1];p++){
    int l=W[p],rem=--wc[l];wx[l]^=i;
    if(rem==1&&rc[l]){int only=wx[l];if(alive[only]){
      for(int e=headR[l];e!=-1;e=nextR[e])if(toR[e]==only){if(!--ob[only])sinks.push_back(only);break;}
    }}else if(rem==0&&rc[l]){
      for(int e=headR[l];e!=-1;e=nextR[e]){int v=toR[e];if(alive[v]&&!--ob[v])sinks.push_back(v);}
    }
   }
  };
  while(remaining){
   while(!sources.empty()&&!alive[sources.front()])sources.pop_front();
   while(!sinks.empty()&&!alive[sinks.front()])sinks.pop_front();
   if(sources.empty() && sinks.empty() && rerankCount<4 && remaining<=rerankAt && n>1000 && m>=n/2 && m<=3*n){
    vector<long long> cost(n+1,LLONG_MAX);
    for(int i=1;i<=n;i++)if(alive[i]){
      long long a=0,b=0;
      for(int p=ws[i];p<ws[i+1];p++)a+=rc[W[p]];
      for(int p=rs[i];p<rs[i+1];p++)b+=wc[R[p]];
      cost[i]=min(a,b);
      if(mode&1)cost[i]=3*cost[i]+llabs(a-b);
    }
    stable_sort(ranking.begin(),ranking.end(),[&](int a,int b){return cost[a]<cost[b];});
    cursor=0;
    rerankCount++;
    rerankAt=remaining*65/100;
   }
   int v,side;
   if(!sources.empty()){
    v=sources.front();sources.pop_front();side=0;
   }else if(!sinks.empty()){
    v=sinks.front();sinks.pop_front();side=1;
   }else{
    while(cursor<n&&!alive[ranking[cursor]])cursor++;
    v=ranking[cursor];long long best=LLONG_MAX;side=0;
    auto consider=[&](int i){
     long long front=0,back=0;
     for(int p=ws[i];p<ws[i+1];p++){int l=W[p];front+=rc[l];}
     for(int p=rs[i];p<rs[i+1];p++){int l=R[p];back+=wc[l];}
     long long cost=min(front,back);
     if((mode&1)!=0)cost=3*cost+abs(front-back);
     if(cost<best){best=cost;v=i;side=(back<front);}
    };
    int looked=0;
    for(int j=cursor;j<n&&looked<24;j++){
     int i=ranking[j];if(!alive[i])continue;looked++;
     consider(i);
    }
    if(mode>=2 && n>1000){
      uint64_t &state=packState;
      for(int trial=0;trial<192;trial++){
        state=state*2862933555777941757ULL+3037000493ULL;
        int i=(int)(state%(uint64_t)n)+1;
        if(alive[i])consider(i);
      }
    }
   }
   if(side==0){
    // Place v at beginning of the remaining sequence; no later reader of its writes.
    left.push_back(v);erase(v);
    for(int p=ws[v];p<ws[v+1];p++){
     int l=W[p];if(rc[l])for(int e=headR[l];e!=-1;e=nextR[e])if(alive[toR[e]])erase(toR[e]);
    }
   }else{
    right.push_back(v);erase(v);
    for(int p=rs[v];p<rs[v+1];p++){
     int l=R[p];if(wc[l])for(int e=headW[l];e!=-1;e=nextW[e])if(alive[toW[e]])erase(toW[e]);
    }
   }
  }
  reverse(right.begin(),right.end());left.insert(left.end(),right.begin(),right.end());return left;
 }
 vector<int> repair(const vector<int>& old,int mode=0){
  int k=old.size();if(k==n)return old;
  vector<int> lastR(m+1,-1),firstW(m+1,k),head(k+1,-1),next(n+1,-1);
  vector<uint8_t> selected(n+1,0);
  for(int p=0;p<k;p++){int i=old[p];selected[i]=1;
   for(int j=rs[i];j<rs[i+1];j++)lastR[R[j]]=p;
   for(int j=ws[i];j<ws[i+1];j++)if(firstW[W[j]]==k)firstW[W[j]]=p;
  }
  // Modes: id ascending, least write impact first, higher out-degree first.
  // Order for mode 1 depends only on static dIn and transaction ID. Computing
  // the sort once outside repair() preserves the exact candidate order.
  vector<int> fallback;
  if(mode>1){
    fallback.reserve(n-k);
    for(int i=1;i<=n;i++)if(!selected[i])fallback.push_back(i);
    sort(fallback.begin(),fallback.end(),[&](int a,int b){return dOut[a]<dOut[b] || (dOut[a]==dOut[b]&&a>b);});
  }
  int cnt=mode==1?n:mode>1?(int)fallback.size():n;
  for(int q=0;q<cnt;q++){
   int i=mode==1?repairOrder1[q]:mode>1?fallback[q]:(q+1);if(selected[i])continue;
   int lo=0,hi=k;
   for(int j=ws[i];j<ws[i+1];j++)lo=max(lo,lastR[W[j]]+1);
   for(int j=rs[i];j<rs[i+1];j++)hi=min(hi,firstW[R[j]]);
   if(lo<=hi){next[i]=head[lo];head[lo]=i;}
  }
  vector<uint8_t> seenWrite(m+1,0);vector<int> result;result.reserve(n);
  for(int pos=0;pos<=k;pos++){
   for(int i=head[pos];i!=-1;i=next[i]){
    bool ok=true;for(int j=rs[i];j<rs[i+1];j++)if(seenWrite[R[j]]){ok=false;break;}
    if(ok){result.push_back(i);for(int j=ws[i];j<ws[i+1];j++)seenWrite[W[j]]=1;}
   }
   if(pos<k){int i=old[pos];result.push_back(i);for(int j=ws[i];j<ws[i+1];j++)seenWrite[W[j]]=1;}
  }
  return result;
 }
 vector<int> greedy(const vector<int>& order,bool backward){
  vector<uint8_t> touched(m+1,0);vector<int> ans;ans.reserve(n);
  for(int i:order){bool ok=true;
   if(!backward){for(int j=rs[i];j<rs[i+1];j++)if(touched[R[j]]){ok=false;break;}}
   else{for(int j=ws[i];j<ws[i+1];j++)if(touched[W[j]]){ok=false;break;}}
   if(!ok)continue;
   ans.push_back(i);
   if(!backward){for(int j=ws[i];j<ws[i+1];j++)touched[W[j]]=1;}
   else{for(int j=rs[i];j<rs[i+1];j++)touched[R[j]]=1;}
  }
  if(backward)reverse(ans.begin(),ans.end());return ans;
 }
 struct SCC {vector<int> comp; int groups;};
 SCC scc(){
  vector<int> node(m+1,0),loc(1,0);int total=n;
  for(int l=1;l<=m;l++)if(cR[l]&&cW[l]){node[l]=++total;loc.push_back(l);}
  vector<uint8_t> seen(total+1,0);
  vector<int> cursor(total+1,0),finish;finish.reserve(total);
  vector<int> st;st.reserve(total);
  for(int first=1;first<=n;first++){
   if(seen[first])continue;
   seen[first]=1;cursor[first]=rs[first];st.push_back(first);
   while(!st.empty()){
    int u=st.back(),v=0;
    if(u<=n){int p=cursor[u];while(p<rs[u+1]&&!node[R[p]])p++;
     if(p==rs[u+1]){finish.push_back(u);st.pop_back();continue;}
     cursor[u]=p+1;v=node[R[p]];
    }else{int p=cursor[u];if(p==-1){finish.push_back(u);st.pop_back();continue;}
     v=toW[p];cursor[u]=nextW[p];}
    if(!seen[v]){seen[v]=1;cursor[v]=v<=n?rs[v]:headW[loc[v-n]];st.push_back(v);}
   }
  }
  vector<int> comp(total+1,-1);int nc=0;
  for(int z=(int)finish.size()-1;z>=0;z--){int first=finish[z];if(comp[first]!=-1)continue;
   comp[first]=nc;st.push_back(first);
   while(!st.empty()){
    int u=st.back();st.pop_back();
    if(u<=n){for(int p=ws[u];p<ws[u+1];p++){int v=node[W[p]];if(v&&comp[v]==-1){comp[v]=nc;st.push_back(v);}}}
    else {int l=loc[u-n];for(int e=headR[l];e!=-1;e=nextR[e]){int v=toR[e];if(comp[v]==-1){comp[v]=nc;st.push_back(v);}}}
   }nc++;
  }
  comp.resize(n+1);return {move(comp),nc};
 }
 struct TinyGraph{vector<bitset<128>> out,in;};
 TinyGraph tiny(const vector<int>& v){
  int q=v.size();TinyGraph g;g.out.resize(q);g.in.resize(q);
  unordered_map<int,bitset<128>> writers;writers.reserve(q*6+2);
  for(int j=0;j<q;j++)for(int p=ws[v[j]];p<ws[v[j]+1];p++)writers[W[p]].set(j);
  for(int j=0;j<q;j++){
   for(int p=rs[v[j]];p<rs[v[j]+1];p++){
    auto it=writers.find(R[p]);if(it!=writers.end())g.out[j]|=it->second;
   }
   g.out[j].reset(j);
   for(int x=0;x<q;x++)if(g.out[j][x])g.in[x].set(j);
  }
  return g;
 }
 vector<int> exact(const vector<int>& v,const TinyGraph& g){
  int q=v.size(),full=(1<<q),bestMask=0,best=0;
  vector<uint8_t> ok(full,0);vector<int8_t> chosen(full,-1);ok[0]=1;
  vector<uint32_t> out(q);for(int i=0;i<q;i++)out[i]=(uint32_t)g.out[i].to_ulong();
  for(int mask=1;mask<full;mask++){
   for(int t=mask;t;t&=t-1){int p=__builtin_ctz(t),rest=mask^(1<<p);
    if(ok[rest]&&!(out[p]&rest)){
     ok[mask]=1;chosen[mask]=p;int c=__builtin_popcount((unsigned)mask);
     if(c>best){best=c;bestMask=mask;}break;
    }
   }
  }
  vector<int> ans;ans.reserve(best);
  while(bestMask){int j=chosen[bestMask];ans.push_back(v[j]);bestMask^=1<<j;}
  reverse(ans.begin(),ans.end());return ans;
 }
 vector<int> smallLocal(const vector<int>& v,const vector<int>& seq,const TinyGraph& g,double deadline){
  const int q=v.size();vector<int> id(n+1,-1);for(int j=0;j<q;j++)id[v[j]]=j;
  vector<int> order;for(int tx:seq)order.push_back(id[tx]);
  vector<int> best=order;int bestSize=best.size();
  set<pair<int,int>> taboo;
  for(int iter=0;iter<130 && elapsed()<deadline;iter++){
   bitset<128> selected;for(int j:order)selected.set(j);
   vector<tuple<int,int,int>> zero,swap;
   for(int u=0;u<q;u++)if(!selected[u]){
    bitset<128> prior,after=selected;
    int lowCost=INT_MAX,slot=0,blocker=-1;
    for(int pos=0;pos<=(int)order.size();pos++){
     auto conflict=(g.out[u]&prior)|(g.in[u]&after);
     int cost=conflict.count();
     if(cost<lowCost){lowCost=cost;slot=pos;blocker=cost==1?int(conflict._Find_first()):-1;}
     if(pos<(int)order.size()){int v=order[pos];prior.set(v);after.reset(v);}
    }
    if(lowCost==0)zero.emplace_back(u,slot,-1);
    else if(lowCost==1)swap.emplace_back(u,slot,blocker);
   }
   if(!zero.empty()){
    auto [u,pos,_]=zero[RNG()%zero.size()];order.insert(order.begin()+pos,u);
    if((int)order.size()>bestSize){best=order;bestSize=order.size();}taboo.clear();continue;
   }
   shuffle(swap.begin(),swap.end(),RNG);
   bool moved=false;
   if(iter%5!=4){for(auto [u,pos,bad]:swap){if(taboo.count({u,bad}))continue;
     taboo.insert({u,bad});order.insert(order.begin()+pos,u);auto it=find(order.begin(),order.end(),bad);order.erase(it);moved=true;break;
   }}
   if(moved)continue;
   // Random topological order of the current induced DAG (Kahn algorithm).
   bitset<128> remain;for(int j:order)remain.set(j);
   vector<int> reordered;reordered.reserve(order.size());
   while(remain.any()){
    vector<int> sources;for(int j=0;j<q;j++)if(remain[j]&&(g.in[j]&remain).none())sources.push_back(j);
    if(sources.empty())break;int x=sources[RNG()%sources.size()];reordered.push_back(x);remain.reset(x);
   }
   if(reordered.size()==order.size())order.swap(reordered);
   if(taboo.size()>32)taboo.clear();
  }
  vector<int> answer;for(int j:best)answer.push_back(v[j]);return answer;
 }
 // Reorder a valid DAG without changing its selected vertices, then repair.
 // The implicit incidence representation keeps processing O(n log n + S), not O(n^2).
 vector<int> reshuffle(const vector<int>& initial,int mode){
  int k=initial.size();
  vector<int> rc(m+1,0),rx(m+1,0),mark(m+1,0),indeg(n+1,0),seq;
  vector<uint8_t> selected(n+1,0),used(n+1,0);
  for(int i:initial){selected[i]=1;for(int e=rs[i];e<rs[i+1];e++){
    int l=R[e];rc[l]++;rx[l]^=i;
  }}
  // Detect self-read by stamping each selected transaction while processing writes.
  for(int i:initial){for(int e=rs[i];e<rs[i+1];e++)mark[R[e]]=i;
   for(int e=ws[i];e<ws[i+1];e++){
    int l=W[e];if(rc[l] > (mark[l]==i))indeg[i]++;
   }
  }
  vector<uint64_t> rank(n+1);
  for(int z=0;z<k;z++){
   int i=initial[z];
   if(mode==0)rank[i]=RNG();
   else if(mode==1)rank[i]=(uint64_t)(k-1-z);
   else if(mode==2)rank[i]=(uint64_t)z;
   else if(mode==3)rank[i]=(uint64_t)min(dIn[i],dOut[i]);
   else rank[i]=(uint64_t)(dIn[i]+dOut[i]);
  }
  using Elem=pair<uint64_t,int>;
  priority_queue<Elem,vector<Elem>,greater<Elem>> ready;
  for(int i:initial)if(!indeg[i])ready.emplace(rank[i],i);
  seq.reserve(k);
  while(!ready.empty()){
   auto [rank_i,i]=ready.top();ready.pop();
   if(used[i])continue;
   used[i]=1;seq.push_back(i);
   for(int e=rs[i];e<rs[i+1];e++){
    int l=R[e],rem=--rc[l];rx[l]^=i;
    if(rem==0){for(int j=headW[l];j!=-1;j=nextW[j]){
      int tx=toW[j];if(selected[tx]&&!used[tx]&&!--indeg[tx])ready.emplace(rank[tx],tx);
    }}else if(rem==1){int tx=rx[l];if(selected[tx]&&!used[tx]){
      for(int j=headW[l];j!=-1;j=nextW[j])if(toW[j]==tx){
        if(!--indeg[tx])ready.emplace(rank[tx],tx);break;
      }
    }}
   }
  }
  if((int)seq.size()!=k){
   fprintf(stderr,"reshuffle DAG failure k=%d produced=%zu\n",k,seq.size());exit(6);
  }
  return seq;
 }
 // Large-neighborhood search: destroy a bounded fraction of the chosen order,
 // then rebuild with the same feasibility-preserving insertion repair.
 vector<int> perturb(const vector<int>& initial,int mode){
  int k=(int)initial.size(); if(k<3)return initial;
  vector<int> subset;subset.reserve(k);
  // Every 4th trial: deterministic shift of the hole pattern; other trials random.
  int div=mode%3==0?20:(mode%3==1?50:100);
  uint64_t threshold=UINT64_MAX/(uint64_t)div;
  uint64_t seed=RNG();
  for(int pos=0;pos<k;pos++){
   int x=initial[pos];
   uint64_t v=mode%4==0?(uint64_t)(pos*11400714819323198485ULL+seed):RNG();
   if(v>=threshold)subset.push_back(x);
  }
  if(subset.size()==initial.size())return initial;
  return repair(subset,1);
 }
 // Global one-exchange (inspired by PACE 2022), selected graph kept implicitly.
 vector<int> exchange(vector<int> best,double deadline){
  int k=best.size();if(k>=n)return best;
  vector<int> incumbent=best;
  int neutralSteps=0;
  vector<int> position(n+1,-1),hr(m+1,-1),hw(m+1,-1),nextSelR,nextSelW,ownerSelR,ownerSelW;
  vector<int> cSelR(m+1,0),cSelW(m+1,0);
  nextSelR.reserve(R.size());nextSelW.reserve(W.size());ownerSelR.reserve(R.size());ownerSelW.reserve(W.size());
  vector<int> flags(n+1,0),stamp(n+1,0);
  int token=0;
  for(int attempt=0;attempt<14 && elapsed()<deadline;attempt++){
   k=best.size();fill(position.begin(),position.end(),-1);fill(hr.begin(),hr.end(),-1);fill(hw.begin(),hw.end(),-1);
   fill(cSelR.begin(),cSelR.end(),0);fill(cSelW.begin(),cSelW.end(),0);
   nextSelR.clear();nextSelW.clear();ownerSelR.clear();ownerSelW.clear();
   for(int p=0;p<k;p++){
    int tx=best[p];position[tx]=p;
    for(int e=rs[tx];e<rs[tx+1];e++){int l=R[e];cSelR[l]++;nextSelR.push_back(hr[l]);hr[l]=ownerSelR.size();ownerSelR.push_back(tx);}
    for(int e=ws[tx];e<ws[tx+1];e++){int l=W[e];cSelW[l]++;nextSelW.push_back(hw[l]);hw[l]=ownerSelW.size();ownerSelW.push_back(tx);}
   }
   struct Move{int u,slot,bad;long long weight;};
   vector<Move> moves; moves.reserve(5000);
   bool direct=false;int directU=0,directSlot=0;
   for(int u=1;u<=n && elapsed()<deadline;u++)if(position[u]<0){
    int bound=0;
    for(int p=rs[u];p<rs[u+1];p++){bound+=cSelW[R[p]];if(bound>192)break;}
    if(bound>192)continue;
    for(int p=ws[u];p<ws[u+1];p++){bound+=cSelR[W[p]];if(bound>192)break;}
    if(bound>192)continue;
    token++;vector<int> neighbors;neighbors.reserve(bound+1);
    for(int p=rs[u];p<rs[u+1];p++)for(int e=hw[R[p]];e!=-1;e=nextSelW[e]){
      int v=ownerSelW[e];if(stamp[v]!=token){stamp[v]=token;flags[v]=1;neighbors.push_back(v);}else flags[v]|=1;
    }
    for(int p=ws[u];p<ws[u+1];p++)for(int e=hr[W[p]];e!=-1;e=nextSelR[e]){
      int v=ownerSelR[e];if(stamp[v]!=token){stamp[v]=token;flags[v]=2;neighbors.push_back(v);}else flags[v]|=2;
    }
    // Build event-based conflict count over insertion slots; flags=3 are permanent conflicts.
    int cost=0;vector<pair<int,int>> events;events.reserve(neighbors.size());
    for(int v:neighbors){int f=flags[v];if(f==1)events.emplace_back(position[v],+1);
      else if(f==2){cost++;events.emplace_back(position[v],-1);}else cost++;
    }
    int mincost=cost,bestSlot=0;
    sort(events.begin(),events.end());
    for(auto [pos,delta]:events){cost+=delta;
      if(cost<mincost){mincost=cost;bestSlot=pos+1;}
    }
    if(mincost==0){direct=true;directU=u;directSlot=bestSlot;break;}
    if(mincost==1){int bad=0;for(int v:neighbors){int f=flags[v];
      if(f==3||(f==1 && position[v]<bestSlot)||(f==2 && position[v]>=bestSlot)){bad=v;break;}}
      if(bad){long long weight=(dIn[bad]+dOut[bad])-(dIn[u]+dOut[u]);moves.push_back({u,bestSlot,bad,weight});}
    }
   }
   if(direct){best.insert(best.begin()+directSlot,directU);best=repair(best,1);if(best.size()>incumbent.size())incumbent=best;neutralSteps=0;continue;}
   sort(moves.begin(),moves.end(),[](auto &a,auto &b){return a.weight>b.weight;});
   bool improved=false;
   vector<int> neutral;
   int limit=min<int>(moves.size(),40);
   for(int it=0;it<limit && elapsed()<deadline;it++){
    int j=it<20?it:(20+RNG()%(moves.size()-20));
    auto move=moves[j];vector<int> trial=best;
    trial.insert(trial.begin()+move.slot,move.u);
    auto f=find(trial.begin(),trial.end(),move.bad);if(f==trial.end())continue;
    trial.erase(f);trial=repair(trial,1);
    if(trial.size()>best.size()){best.swap(trial);improved=true;neutralSteps=0;if(best.size()>incumbent.size())incumbent=best;break;}
    if(trial.size()==best.size() && neutral.empty() && move.weight>=0 && neutralSteps<6){neutral=std::move(trial);}
   }
   if(!improved){
    if(!neutral.empty() && neutralSteps<6){best.swap(neutral);neutralSteps++;}
    else break;
   }
  }
  return incumbent;
 }
 bool verify(const vector<int>& seq)const{vector<uint8_t> seenW(m+1,0),seen(n+1,0);
  for(int i:seq){if(i<1||i>n||seen[i])return false;seen[i]=1;
   for(int p=rs[i];p<rs[i+1];p++)if(seenW[R[p]])return false;
   for(int p=ws[i];p<ws[i+1];p++)seenW[W[p]]=1;
  }return true;
 }
 vector<int> solve(){begun=Clock::now();input();degrees();
  vector<int> indices(n);iota(indices.begin(),indices.end(),1);
  vector<vector<int>> solutions;solutions.reserve(20);
  auto keep=[&](vector<int> x){if(!verify(x)){fprintf(stderr,"internal invalid solution\n");exit(4);}solutions.push_back(move(x));};
  long long totalConflicts=0;for(int tx=1;tx<=n;tx++)totalConflicts+=dOut[tx];
  bool startupDense=(totalConflicts>(long long)8*n) &&
       (R.size()<=3*W.size() && W.size()<=3*R.size());
  // Pack has much better starts than peel on dense balanced incidence graphs.
  vector<int> modes=startupDense?vector<int>{0,1}:vector<int>{0,1,2,3,4,5,6,7};
  for(int mode:modes){
   if(!canSpend(.55)&&solutions.size()>=2)break;
   vector<int> order=indices;
   auto score=[&](int i)->long double{
    auto a=(long double)dIn[i],b=(long double)dOut[i];
    switch(mode){
     case 0:return a*b;
     case 1:return min(a,b);
     case 2:return a+b;
     case 3:return a;
     case 4:return b;
     case 5:return (a+.3L)/(b+.3L);
     case 6:return (b+.3L)/(a+.3L);
     default:return (a*b)/(a+b+1.0L);
    }
   };
   sort(order.begin(),order.end(),[&](int a,int b){auto x=score(a),y=score(b);if(x!=y)return x>y;return (mode&1)?a>b:a<b;});
   vector<int> peeled=peel(order);
   auto res=repair(peeled,0);keep(move(res));
   if(canSpend(.7))keep(repair(peeled,1));
  }
  size_t prePackBest=0;for(auto &v:solutions)prePackBest=max(prePackBest,v.size());
  // Packing-based alternatives: choose inclusion, then drop newly incompatible vertices.
  if(canSpend(.85)){
    int packTries=(startupDense && m>=n/2 && m<=3*n)?4:2;
    for(int mode=0;mode<packTries && canSpend(.55);mode++){
      vector<int> order=indices;
      sort(order.begin(),order.end(),[&](int a,int b){
       long long x=min(dIn[a],dOut[a]),y=min(dIn[b],dOut[b]);
       if(x!=y)return x<y;return (mode&1)==0?a<b:a>b;
      });
      auto packed=pack(order,mode);
      keep(repair(packed,1));
    }
  }
  size_t postPackBest=0;for(auto &v:solutions)postPackBest=max(postPackBest,v.size());
  // On atypical dense graphs, pack need not dominate all peel orders.
  // Keep the full old starter portfolio unless pack wins comfortably.
  if(startupDense && (n<=10000 || postPackBest*100 <= prePackBest*105)){
    for(int mode=2;mode<=7 && canSpend(.55);mode++){
      vector<int> order=indices;
      auto score=[&](int i)->long double{
        auto a=(long double)dIn[i],b=(long double)dOut[i];
        switch(mode){
          case 2:return a+b;
          case 3:return a;
          case 4:return b;
          case 5:return (a+.3L)/(b+.3L);
          case 6:return (b+.3L)/(a+.3L);
          default:return (a*b)/(a+b+1.0L);
        }
      };
      sort(order.begin(),order.end(),[&](int a,int b){auto x=score(a),y=score(b);if(x!=y)return x>y;return (mode&1)?a>b:a<b;});
      vector<int> peeled=peel(order);
      keep(repair(peeled,0));
      if(canSpend(.7))keep(repair(peeled,1));
    }
    postPackBest=0;for(auto &v:solutions)postPackBest=max(postPackBest,v.size());
  }
  bool packDominant=(postPackBest*100 > prePackBest*102);
  // Adaptively re-evaluate some candidate cycle breakers under live counts.
  for(int dynamic=1;dynamic<=4 && !packDominant && canSpend(.58) && m>=n/2;dynamic++){
   vector<int> order=indices;
   int mode=dynamic==1?0:dynamic==2?1:dynamic==3?3:4;
   auto score=[&](int i)->long double{
    long double a=dIn[i],b=dOut[i];
    if(mode==0)return a*b;
    if(mode==1)return min(a,b);
    if(mode==3)return a;
    return b;
   };
   sort(order.begin(),order.end(),[&](int a,int b){auto x=score(a),y=score(b);if(x!=y)return x>y;return a<b;});
   vector<int> peeled=peel(order,dynamic);
   keep(repair(peeled,0));
   if(canSpend(.7))keep(repair(peeled,1));
  }
  // Independent greedy forward/reverse selections, useful for large SCCs.
  for(int mode=0;mode<4 && canSpend(.55);mode++){
   vector<int> order=indices;
   sort(order.begin(),order.end(),[&](int a,int b){long long x=mode<2?dIn[a]:dOut[a],y=mode<2?dIn[b]:dOut[b];if(x!=y)return mode%2?x>y:x<y;return a<b;});
   keep(repair(greedy(order,mode==3),1));
  }
  int ibest=0;for(int j=1;j<(int)solutions.size();j++)if(solutions[j].size()>solutions[ibest].size())ibest=j;
  vector<int> best=solutions[ibest];
  if(best.size()==n || !canSpend(.25))return best;
  SCC c=scc();int C=c.groups;
  vector<int> winner(C,-1),bestCount(C,0),count(C,0),touched;
  for(int s=0;s<(int)solutions.size();s++){
   touched.clear();for(int tx:solutions[s]){int cc=c.comp[tx];if(!count[cc])touched.push_back(cc);count[cc]++;}
   for(int cc:touched){if(count[cc]>bestCount[cc]){bestCount[cc]=count[cc];winner[cc]=s;}count[cc]=0;}
  }
  vector<vector<int>> groups(C);for(int s=0;s<(int)solutions.size();s++)for(int tx:solutions[s]){
   int cc=c.comp[tx];if(winner[cc]==s)groups[cc].push_back(tx);
  }
  vector<vector<int>> vtx(C);for(int tx=1;tx<=n;tx++)vtx[c.comp[tx]].push_back(tx);
  // Components with little or no loss don't need a costly improvement pass.
  vector<int> interesting;for(int cc=0;cc<C;cc++){
   int q=vtx[cc].size();if(q>=2&&q<=128&&bestCount[cc]<q-1)interesting.push_back(cc);
  }
  sort(interesting.begin(),interesting.end(),[&](int a,int b){int da=vtx[a].size()-bestCount[a],db=vtx[b].size()-bestCount[b];return da>db || (da==db && vtx[a].size()<vtx[b].size());});
  long long exactBudget=16000000;
  for(int cc:interesting){if(!canSpend(.22))break;
   auto &v=vtx[cc];int q=v.size();auto g=tiny(v);
   if(q<=17 && exactBudget>=(1LL<<q)){auto result=exact(v,g);exactBudget-=(1LL<<q);
    if(result.size()>groups[cc].size())groups[cc]=move(result);
   }else if(q<=96){auto result=smallLocal(v,groups[cc],g,2.65);
    if(result.size()>groups[cc].size())groups[cc]=move(result);
   }
  }
  vector<int> joined;joined.reserve(n);
  for(auto &v:groups)joined.insert(joined.end(),v.begin(),v.end());
  if(!verify(joined)){fprintf(stderr,"SCC invalid!\n");exit(5);}
  if(joined.size()>best.size())best.swap(joined);
  // Every nontrivial SCC contains at least one cycle. If the constructed
  // solution already hits the sum of these elementary component bounds,
  // it is provably optimal: skip any further randomized work.
  int sccUpper=n;
  for(const auto& component:vtx)if(component.size()>1)--sccUpper;
  if((int)best.size()>=sccUpper)return best;
  // The asymmetric read/write workload has traditionally benefited from exchanges.
  // Balanced workloads show larger gains from multiple topological reorders.
  bool asymmetric=(R.size()>3*W.size() || W.size()>3*R.size());
  if(asymmetric){
    if(canSpend(.85)){
      vector<int> original=best;
      for(int mode=0;mode<4 && canSpend(.55);mode++){
        auto order=reshuffle(original,mode);
        auto candidate=repair(order,1);
        if(candidate.size()>best.size())best=move(candidate);
      }
    }
    if(canSpend(.25)){auto res=exchange(best,2.70);if(res.size()>best.size())best.swap(res);}
  } else {
    // Use the final budget even when earlier startup stages have run past 1.90s.
    // Prefer large-neighborhood reconstruction when the implicit conflict
    // density is high, and conserve the traditional DAG reorder on sparse data.
    long long volume=0;
    for(int tx=1;tx<=n;tx++)volume+=dOut[tx];
    bool dense=(volume>(long long)8*n);
    if(elapsed()<3.34){
      vector<int> original=best;
      vector<int> current=best;
      for(int mode=0;mode<3000 && elapsed()<3.52;mode++){
        if(mode>=4 && mode%29==0)current=best;
        const auto &base=(mode<4?original:(mode%3==0?best:current));
        vector<int> candidate;
        if(dense && mode>=4 && mode%2==0)candidate=perturb(base,mode);
        else {
          auto order=reshuffle(base,mode<4?mode:0);
          candidate=repair(order,1);
        }
        if(candidate.size()>best.size()){best=candidate;current=candidate;}
        else if(mode>=4 && candidate.size()+1>=best.size() && (candidate.size()>current.size()||mode%4==0))current=move(candidate);
      }
    }
  }
  return best;
 }
};
int main(){Solver s;auto ans=s.solve();printf("%zu\n",ans.size());for(int x:ans)printf("%d ",x);putchar('\n');}
