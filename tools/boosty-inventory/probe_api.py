#!/usr/bin/env python3
"""Check documented anonymous Boosty metadata listing, honoring API host robots.txt."""
import json, urllib.request, urllib.parse, urllib.error, urllib.robotparser
from pathlib import Path
UA="BookPlacementAudit/1.0 (+https://github.com/Lalalalendia/med)"
base="https://api.boosty.to"
robot_url=base+"/robots.txt"
res={}
req=urllib.request.Request(robot_url,headers={"User-Agent":UA})
try:
    with urllib.request.urlopen(req,timeout=20) as r:
        res["robots_status"]=r.status
        rules=r.read(200000).decode("utf-8","replace")
except urllib.error.HTTPError as e:
    res["robots_status"]=e.code
    rules=""
except Exception as e:
    res["robots_status"]="network_error"
    res["error"]=str(e)[:180]
    rules=""
print("ROBOTS_STATUS",res["robots_status"])
if res["robots_status"]==200:
    rp=urllib.robotparser.RobotFileParser()
    rp.parse(rules.splitlines())
    allowed=rp.can_fetch(UA,base+"/v1/blog/ranobemen/post/?limit=2")
    res["robots_allowed"]=allowed
    print("ROBOTS_RELEVANT", " | ".join(x.strip() for x in rules.splitlines() if ("user-agent" in x.lower() or "disallow" in x.lower() or "allow:" in x.lower()))[:1600])
elif res["robots_status"] in (404,410):
    allowed=True
    res["robots_allowed"]=True
else:
    allowed=False
    res["robots_allowed"]=False
if allowed:
    u=base+"/v1/blog/ranobemen/post/?limit=2"
    req=urllib.request.Request(u,headers={"User-Agent":UA,"Accept":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=25) as r:
            res["api_status"]=r.status
            ct=r.headers.get("content-type")
            raw=r.read(2000000)
        data=json.loads(raw)
        res["response_type"]=type(data).__name__
        if isinstance(data,dict):
            res["keys"]=list(data)[:30]
            ex=data.get("extra",{})
            res["extra_keys"]=list(ex)[:20] if isinstance(ex,dict) else []
            res["extra_offset"]=(str(ex.get("offset"))[:60] if isinstance(ex,dict) else None)
            arr=data.get("data",[])
            res["returned_posts"]=len(arr) if isinstance(arr,list) else None
            if isinstance(arr,list):
                for item in arr[:2]:
                    print("PUBLIC_POST_SCHEMA",json.dumps({
                        "keys":list(item)[:60],
                        "title":item.get("title"),
                        "id":item.get("id"),
                        "tags":item.get("tags"),
                        "tagsIds":item.get("tagsIds"),
                        "publishTime":item.get("publishTime"),
                        "publish_time":item.get("publish_time"),
                    },ensure_ascii=False,default=str)[:1700])
    except urllib.error.HTTPError as e:
        res["api_status"]=e.code
        res["api_error"]="HTTP "+str(e.code)
    except Exception as e:
        res["api_error"]=f"{type(e).__name__}: {str(e)[:180]}"
print("METADATA_API_DIAGNOSTIC",json.dumps(res,ensure_ascii=False))
Path("out/boosty-discovery").mkdir(parents=True,exist_ok=True)
Path("out/boosty-discovery/metadata-api.json").write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
