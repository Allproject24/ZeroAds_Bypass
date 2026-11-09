import urllib.parse
import requests

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
GRAPHQL_URL = "https://publisher.linkvertise.com/graphql"

Q1 = "mutation getDetailPageContent($a:PublicLinkIdentificationInput!,$o:String,$ad:CustomAdOfferProviderAdditionalData!){getDetailPageContent(linkIdentificationInput:$a,origin:$o,additional_data:$ad){access_token}}"
Q2 = "mutation completeDetailPageContent($a:PublicLinkIdentificationInput!,$c:CompleteDetailPageContentInput!){completeDetailPageContent(linkIdentificationInput:$a,completeDetailPageContentInput:$c){TARGET}}"
Q3 = "mutation getDetailPageTarget($a:PublicLinkIdentificationInput!,$t:String!){getDetailPageTarget(linkIdentificationInput:$a,token:$t){url}}"

def resolve(url):
    parsed = urllib.parse.urlparse(url)
    path = [p for p in parsed.path.strip("/").split("/") if p]
    
    if len(path) < 2:
        print(f"TIMING stage=lv_err msg=path_terlalu_pendek url={url}", flush=True)
        return None
        
    uid, pid = path[0], path[1]
    
    # Ambil domain asli (misal: link-target.net) untuk Referer & Origin
    domain = parsed.netloc.lower()
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA, 
        "Origin": f"https://{domain}",
        "Referer": f"https://{domain}/",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "X-Requested-With": "XMLHttpRequest"
    })
    
    pd = {"userIdAndUrl": {"user_id": uid, "url": pid}}
    
    try:
        r1 = session.post(GRAPHQL_URL, json={
            "operationName": "getDetailPageContent",
            "variables": {
                "linkIdentificationInput": pd,
                "origin": "sharing",
                "additional_data": {"taboola": {"user_id": "fallbackUserId", "url": url}}
            },
            "query": Q1
        }, timeout=15)
        
        if r1.status_code != 200:
            print(f"TIMING stage=lv_err step=1 status={r1.status_code} text={r1.text[:150]}", flush=True)
            return None
            
        d1 = r1.json()
        if "errors" in d1:
            print(f"TIMING stage=lv_err step=1 msg={d1['errors'][0].get('message', 'unknown')}", flush=True)
            return None
            
        access_token = d1["data"]["getDetailPageContent"]["access_token"]
        
        r2 = session.post(GRAPHQL_URL, json={
            "operationName": "completeDetailPageContent",
            "variables": {
                "linkIdentificationInput": pd,
                "completeDetailPageContentInput": {"access_token": access_token}
            },
            "query": Q2
        }, timeout=15)
        
        if r2.status_code != 200:
            print(f"TIMING stage=lv_err step=2 status={r2.status_code}", flush=True)
            return None
            
        d2 = r2.json()
        if "errors" in d2:
            print(f"TIMING stage=lv_err step=2 msg={d2['errors'][0].get('message', 'unknown')}", flush=True)
            return None
            
        target_token = d2["data"]["completeDetailPageContent"]["TARGET"]
        
        r3 = session.post(GRAPHQL_URL, json={
            "operationName": "getDetailPageTarget",
            "variables": {
                "linkIdentificationInput": pd,
                "token": target_token
            },
            "query": Q3
        }, timeout=15)
        
        if r3.status_code != 200:
            print(f"TIMING stage=lv_err step=3 status={r3.status_code}", flush=True)
            return None
            
        d3 = r3.json()
        if "errors" in d3:
            print(f"TIMING stage=lv_err step=3 msg={d3['errors'][0].get('message', 'unknown')}", flush=True)
            return None
            
        return d3["data"]["getDetailPageTarget"]["url"]
        
    except Exception as e:
        print(f"TIMING stage=lv_err exception={str(e)}", flush=True)
        return None
