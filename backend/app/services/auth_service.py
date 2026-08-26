from __future__ import annotations
import hashlib,hmac,json,secrets
from datetime import datetime,timedelta
from typing import Any,Callable
from fastapi import Depends,HTTPException,Request,status
from sqlalchemy import text
from backend.app.database import engine

COOKIE_NAME="stock_session"; SESSION_DAYS=7; IDLE_MINUTES=30

def hash_password(password:str)->str:
    validate_password(password);salt=secrets.token_bytes(16);digest=hashlib.scrypt(password.encode(),salt=salt,n=2**14,r=8,p=1,dklen=32)
    return f"scrypt$16384$8$1${salt.hex()}${digest.hex()}"

def verify_password(password:str,encoded:str)->bool:
    try:
        _,n,r,p,salt,digest=encoded.split("$");actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=int(n),r=int(r),p=int(p),dklen=32);return hmac.compare_digest(actual.hex(),digest)
    except Exception:return False

def validate_password(password:str)->None:
    if len(password)<10 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):raise ValueError("密码至少10位，并同时包含字母和数字")

def token_hash(token:str)->str:return hashlib.sha256(token.encode()).hexdigest()
def client_ip(request:Request)->str:return request.client.host if request.client else ""

def audit(action:str,request:Request|None=None,user:dict|None=None,success:bool=True,resource_type:str|None=None,resource_id:Any=None,detail:dict|None=None)->None:
    payload=json.dumps(detail,ensure_ascii=False) if detail else None
    with engine().begin() as conn:conn.execute(text("""INSERT INTO audit_log(user_id,username,action,resource_type,resource_id,request_method,request_path,request_ip,success,detail)
      VALUES(:uid,:username,:action,:type,:rid,:method,:path,:ip,:success,:detail)"""),{"uid":user.get("id") if user else None,"username":user.get("username") if user else None,"action":action,"type":resource_type,"rid":str(resource_id) if resource_id is not None else None,"method":request.method if request else None,"path":request.url.path if request else None,"ip":client_ip(request) if request else None,"success":int(success),"detail":payload})

def user_access(user_id:int)->dict:
    with engine().connect() as conn:
        user=conn.execute(text("SELECT id,username,display_name,email,mobile,status,must_change_password,last_login_at,created_at FROM app_user WHERE id=:id"),{"id":user_id}).mappings().first()
        if not user:return {}
        roles=[dict(r) for r in conn.execute(text("""SELECT r.id,r.role_code,r.role_name FROM app_role r JOIN app_user_role ur ON ur.role_id=r.id WHERE ur.user_id=:id ORDER BY r.role_name"""),{"id":user_id}).mappings()]
        permissions=[r[0] for r in conn.execute(text("""SELECT DISTINCT p.permission_code FROM app_permission p JOIN app_role_permission rp ON rp.permission_id=p.id JOIN app_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=:id ORDER BY p.permission_code"""),{"id":user_id})]
    value=dict(user);value["roles"]=roles;value["permissions"]=permissions;return value

def create_session(user_id:int,request:Request)->tuple[str,dict]:
    raw=secrets.token_urlsafe(48);csrf=secrets.token_hex(32);expires=datetime.now()+timedelta(days=SESSION_DAYS)
    with engine().begin() as conn:
        result=conn.execute(text("INSERT INTO app_session(user_id,token_hash,csrf_token,expires_at,ip_address,user_agent) VALUES(:uid,:token,:csrf,:expires,:ip,:agent)"),{"uid":user_id,"token":token_hash(raw),"csrf":csrf,"expires":expires,"ip":client_ip(request),"agent":request.headers.get("user-agent","")[:500]})
        session_id=int(result.lastrowid)
    return raw,{"id":session_id,"csrf_token":csrf,"expires_at":expires}

def current_auth(request:Request)->dict:
    raw=request.cookies.get(COOKIE_NAME)
    if not raw:raise HTTPException(status.HTTP_401_UNAUTHORIZED,"请先登录")
    with engine().begin() as conn:
        session=conn.execute(text("""SELECT s.id,s.user_id,s.csrf_token,s.expires_at,s.last_active_at,u.status,u.must_change_password
          FROM app_session s JOIN app_user u ON u.id=s.user_id WHERE s.token_hash=:token AND s.revoked_at IS NULL"""),{"token":token_hash(raw)}).mappings().first()
        now=datetime.now()
        if not session or session["expires_at"]<=now or session["last_active_at"]<now-timedelta(minutes=IDLE_MINUTES) or session["status"]!="active":raise HTTPException(status.HTTP_401_UNAUTHORIZED,"登录已失效，请重新登录")
        conn.execute(text("UPDATE app_session SET last_active_at=:now WHERE id=:id"),{"now":now,"id":session["id"]})
    user=user_access(session["user_id"]);user["session_id"]=session["id"];user["csrf_token"]=session["csrf_token"];return user

def require_permission(code:str)->Callable:
    def dependency(request:Request,user:dict=Depends(current_auth))->dict:
        if request.method not in ("GET","HEAD","OPTIONS") and request.headers.get("x-csrf-token")!=user["csrf_token"]:raise HTTPException(status.HTTP_403_FORBIDDEN,"安全令牌无效，请刷新页面")
        if code not in user["permissions"]:raise HTTPException(status.HTTP_403_FORBIDDEN,"没有执行该操作的权限")
        return user
    return dependency

def create_user(username:str,password:str,display_name:str,email:str|None,mobile:str|None,role_ids:list[int],created_by:int|None=None,must_change:bool=False)->int:
    encoded=hash_password(password)
    with engine().begin() as conn:
        result=conn.execute(text("INSERT INTO app_user(username,password_hash,display_name,email,mobile,must_change_password,created_by) VALUES(:username,:password,:name,:email,:mobile,:must,:creator)"),{"username":username.lower().strip(),"password":encoded,"name":display_name,"email":email or None,"mobile":mobile or None,"must":int(must_change),"creator":created_by});uid=int(result.lastrowid)
        if role_ids:conn.execute(text("INSERT INTO app_user_role(user_id,role_id) VALUES(:uid,:rid)"),[{"uid":uid,"rid":rid} for rid in role_ids])
    return uid
