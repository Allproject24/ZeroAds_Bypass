import urllib.parse
import requests

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
GRAPHQL_URL = "https://publisher.linkvertise.com/graphql"

Q1 = "mutation getDetailPageContent($a:PublicLinkIdentificationInput!,$o:String,$ad:CustomAdOfferProviderAdditionalData!){getDetailPageContent(linkIdentificationInput:$a,origin:$o,additional_data:$ad){access_token}}"
Q2 = "mutation completeDetailPageContent($a:PublicLinkIdentificationInput!,$c:CompleteDetailPageContentInput!){completeDetailPageContent(linkIdentificationInput:$a,completeDetailPageContentInput:$c){TARGET}}"
Q3 = "mutation getDetailPageTarget($a:PublicLinkIdentificationInput!,$t:String!){getDetailPageTarget(linkIdentificationInput:$a,token:$t){url}}"

def resolve(url):
    """Fungsi utama untuk mem-bypass Linkvertise. Return URL asli atau None."""
    parsed = urllib.parse.urlparse(url)
    path = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path) < 2:
        return None
        
    uid, pid = path[0], path[1]
    session = requests.Session()
    session.headers.update({
        "User-Agent": UA, 
        "Origin": "https://linkvertise.com", 
        "Referer": "https://linkvertise.com"
    })
    
    pd = {"userIdAndUrl": {"user_id": uid, "url": pid}}
    
    try:
        # Step 1: Get Access Token
        r1 = session.post(GRAPHQL_URL, json={
            "operationName": "getDetailPageContent",
            "variables": {
                "linkIdentificationInput": pd,
                "origin": "sharing",
                "additional_data": {"taboola": {"user_id": "fallbackUserId", "url": url}}
            },
            "query": Q1
        }, timeout=15)
        d1 = r1.json()
        if "errors" in d1: return None
        access_token = d1["data"]["getDetailPageContent"]["access_token"]
        
        # Step 2: Complete Detail Page
        r2 = session.post(GRAPHQL_URL, json={
            "operationName": "completeDetailPageContent",
            "variables": {
                "linkIdentificationInput": pd,
                "completeDetailPageContentInput": {"access_token": access_token}
            },
            "query": Q2
        }, timeout=15)
        d2 = r2.json()
        if "errors" in d2: return None
        target_token = d2["data"]["completeDetailPageContent"]["TARGET"]
        
        # Step 3: Get Target URL
        r3 = session.post(GRAPHQL_URL, json={
            "operationName": "getDetailPageTarget",
            "variables": {
                "linkIdentificationInput": pd,
                "token": target_token
            },
            "query": Q3
        }, timeout=15)
        d3 = r3.json()
        if "errors" in d3: return None
        
        return d3["data"]["getDetailPageTarget"]["url"]
    except Exception:
        return None
