"""Slack OpenID Connect login for LINK-ing.
The verified person_id is exactly the Slack user ID and must exist in persons.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from src.db import SupabaseStore

SESSION = "linking_slack_session"
STATE = "linking_slack_oauth_state"
SESSION_SECONDS = 8 * 3600

def enabled():
    return all(os.getenv(x) for x in ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET", "SLACK_REDIRECT_URI"))

def _secret():
    return os.environ["SLACK_CLIENT_SECRET"].encode("utf-8")

def _signed(payload):
    body = base64.urlsafe_b64encode(json.dumps(payload,separators=(",",":"),ensure_ascii=True).encode()).rstrip(b"=").decode()
    mac = hmac.new(_secret(),body.encode(),hashlib.sha256).hexdigest()
    return body + "." + mac

def _read(token):
    try:
        body,mac=token.split(".",1)
        valid=hmac.new(_secret(),body.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(mac,valid):
            return None
        data=json.loads(base64.urlsafe_b64decode(body+"="*((-len(body))%4)))
        if not isinstance(data,dict) or not 0<=time.time()-int(data["iat"])<SESSION_SECONDS:
            return None
        return data
    except (ValueError,KeyError,TypeError):
        return None

def actor(request: Request):
    if not enabled():
        return None  # existing UI demo only; NEVER use this as secure authorization
    claim=_read(request.cookies.get(SESSION,""))
    if not claim or not claim.get("person_id"):
        raise HTTPException(401,"Sign in with Slack required")
    return {"person_id":claim["person_id"],"team":claim.get("team")}

def begin():
    if not enabled():
        raise HTTPException(503,"Slack login is not configured")
    state=secrets.token_urlsafe(32)
    url="https://slack.com/openid/connect/authorize?"+urllib.parse.urlencode({
        "client_id":os.environ["SLACK_CLIENT_ID"],
        "redirect_uri":os.environ["SLACK_REDIRECT_URI"],
        "scope":"openid email profile",
        "response_type":"code",
        "state":state,
    })
    response=RedirectResponse(url,status_code=302)
    response.set_cookie(STATE,_signed({"state":state,"iat":int(time.time())}),secure=True,httponly=True,samesite="lax",max_age=600)
    return response

def callback(code: str,state: str,request: Request):
    if not enabled():
        raise HTTPException(503,"Slack login is not configured")
    saved=_read(request.cookies.get(STATE,""))
    if not saved or not hmac.compare_digest(saved.get("state",""),state):
        raise HTTPException(403,"Invalid Slack login state")
    form=urllib.parse.urlencode({
        "client_id":os.environ["SLACK_CLIENT_ID"],
        "client_secret":os.environ["SLACK_CLIENT_SECRET"],
        "code":code,
        "redirect_uri":os.environ["SLACK_REDIRECT_URI"],
        "grant_type":"authorization_code",
    }).encode()
    exchange=urllib.request.Request("https://slack.com/api/openid.connect.token",data=form,headers={"Content-Type":"application/x-www-form-urlencoded"},method="POST")
    try:
        with urllib.request.urlopen(exchange,timeout=20) as res:
            token=json.load(res)
        if not token.get("ok") or not token.get("access_token"):
            raise HTTPException(401,"Slack token exchange failed")
        identity=urllib.request.Request("https://slack.com/api/openid.connect.userInfo",headers={"Authorization":"Bearer "+token["access_token"]})
        with urllib.request.urlopen(identity,timeout=20) as res:
            info=json.load(res)
    except (urllib.error.URLError, ValueError):
        raise HTTPException(502,"Slack login unavailable") from None
    if info.get("ok") is False:
        raise HTTPException(401,"Slack identity could not be confirmed")
    uid=info.get("https://slack.com/user_id") or info.get("sub")
    team=info.get("https://slack.com/team_id")
    expected=os.getenv("SLACK_WORKSPACE_TEAM_ID")
    if not isinstance(uid,str) or not uid.startswith("U") or (expected and team!=expected):
        raise HTTPException(403,"Unexpected Slack account or workspace")
    store=SupabaseStore()
    persons=store.request("persons",params={"select":"person_id,name,team","person_id":"eq."+uid,"limit":1})
    if not persons:
        raise HTTPException(403,"Slack person_id is not registered in persons")
    if persons[0].get('team','').strip().casefold() != 'marketing':
        raise HTTPException(403,"Only Marketing team members may sign in for this demo")
    response=RedirectResponse("/?slack_login=1",status_code=303)
    response.delete_cookie(STATE)
    response.set_cookie(SESSION,_signed({"person_id":uid,"team":team,"iat":int(time.time())}),secure=True,httponly=True,samesite="lax",max_age=SESSION_SECONDS)
    return response

def logout():
    response=RedirectResponse("/",status_code=303)
    response.delete_cookie(SESSION)
    response.delete_cookie(STATE)
    return response
