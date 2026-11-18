#!/usr/bin/env python3
"""Survey openly readable 史莱姆真仙 mirrors without bypassing access controls.
Emit chapter body-length diagnostics only; do not export full prose."""
from urllib.parse import urljoin,urlsplit
from urllib.robotparser import RobotFileParser
import re,requests
from bs4 import BeautifulSoup

UA='MedNovelCollector/1.0 (authorized textual archive; no evasion)'
SITES=[
 ('sudugu','https://www.sudugu520.com/978/'),
 ('biquge2026','https://www.biquge2026.com/book/shilaimuzhenxian/'),
 ('xiaoshuo_tw','https://www.xiaoshuo.com.tw/882005/'),
 ('tacapro','https://www.tacapro.com/novel/15902172219/'),
 ('readnovel','https://www.readnovel.com/bookquery/qbcliqpekgyc'),
]
HEAD=re.compile(r'第\s*(\d+)\s*章\s*[\s：:]*(.*)')
SLOTS=['#content','#chaptercontent','.con','.content','.read-content',
       '.chapter-content','.chapter_content','.txtnav','#chapterContent',
       '.container','article','main']
BLOCK=('验证码','captcha','正在验证浏览器','请输入验证码','访问频繁','登录后阅读')
def cjk(v):return len(re.findall(r'[\u3400-\u9fff]',v))
def allowed(s,u):
 a,b=urlsplit(u),urlsplit(s)
 return a.scheme=='https' and a.hostname==b.hostname and a.username is None and a.password is None
def probe(name,index):
 sess=requests.Session()
 sess.headers.update({'User-Agent':UA,'Accept-Language':'zh-CN,zh;q=0.9'})
 s=urlsplit(index); robots=f'{s.scheme}://{s.netloc}/robots.txt'
 try:
  rob=sess.get(robots,timeout=(5,12),allow_redirects=False)
  rp=RobotFileParser()
  if rob.status_code in (404,410):
   rp.parse(['User-agent: *','Allow: /'])
  elif rob.status_code==200 and 'user-agent:' in rob.text.lower():
   rp.parse(rob.text.splitlines())
  else:
   print(name,'BLOCK: robots unavailable',rob.status_code,flush=True);return
  if not rp.can_fetch(UA,index):
   print(name,'BLOCK: robots disallows catalog',flush=True);return
  page=sess.get(index,timeout=(6,20),allow_redirects=False)
  if page.status_code!=200:
   print(name,'BLOCK: catalog HTTP',page.status_code,flush=True);return
  page.encoding=page.apparent_encoding or page.encoding
  soup=BeautifulSoup(page.text,'html.parser')
  targets={}
  for a in soup.select('a[href]'):
   label=re.sub(r'\s+',' ',a.get_text(' ',strip=True))
   if any(x in label for x in ('惊人谋划','战争开启','艰难的推进')):
    url=urljoin(index,a['href'])
    if allowed(index,url):
     targets[label]=(url,label)
  print(name,'catalog_bytes',len(page.content),'targets',list(targets)[:10],flush=True)
  if not targets:return
  for label,(u,_) in list(targets.items())[:3]:
   if not rp.can_fetch(UA,u):
    print(name,'BLOCK: chapter robots',label,flush=True);continue
   r=sess.get(u,timeout=(6,20),allow_redirects=False)
   if r.status_code!=200:
    print(name,'BLOCK: chapter HTTP',r.status_code,label,flush=True);continue
   r.encoding=r.apparent_encoding or r.encoding
   doc=BeautifulSoup(r.text,'html.parser')
   candidates=[]
   for selector in SLOTS:
    for node in doc.select(selector)[:2]:
     text=node.get_text('\n',strip=True)
     candidates.append((cjk(text),selector,text))
   candidates.sort(reverse=True)
   if candidates:
    length,selector,text=candidates[0]
   else:
    length,selector,text=0,'NONE',''
   flags=[x for x in BLOCK if x.lower() in r.text.lower()]
   print(name,'chapter',label,'url',urlsplit(u).path,'htmlbytes',len(r.content),
         'max_text_CJK',length,'selector',selector,'flags',flags,
         'intro',repr(text[:110]),'tail',repr(text[-170:]),flush=True)
 except Exception as e:
  print(name,'ERROR',type(e).__name__,str(e)[:160],flush=True)

if __name__=='__main__':
 for row in SITES:probe(*row)
