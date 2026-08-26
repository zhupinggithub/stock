from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,Request,Response
from sqlalchemy import text
from backend.app.database import engine
from backend.app.schemas.auth import ChangePasswordBody,LoginBody,RegisterBody,ResetConsumeBody
from backend.app.services.auth_service import COOKIE_NAME,audit,create_session,create_user,current_auth,hash_password,token_hash,user_access,verify_password

router=APIRouter(prefix="/auth",tags=["auth"])

@router.post("/register",status_code=201)
def register(body:RegisterBody,request:Request,response:Response):
    with engine().connect() as conn:role_id=conn.execute(text("SELECT id FROM app_role WHERE role_code='viewer'")).scalar_one()
    try:uid=create_user(body.username,body.password,body.display_name,body.email,body.mobile,[role_id],must_change=False)
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception as exc:raise HTTPException(409,"用户名、邮箱或手机号已被使用") from exc
    raw,session=create_session(uid,request);response.set_cookie(COOKIE_NAME,raw,max_age=7*86400,httponly=True,samesite="lax",secure=False,path="/")
    access=user_access(uid);audit("auth.register",request,access,True);return {"user":access,"csrf_token":session["csrf_token"]}

@router.post("/login")
def login(body:LoginBody,request:Request,response:Response):
    failure_user=None
    with engine().begin() as conn:
        user=conn.execute(text("SELECT * FROM app_user WHERE username=:username"),{"username":body.username.lower().strip()}).mappings().first();now=datetime.now()
        invalid=not user or user["status"]=="disabled" or (user["locked_until"] and user["locked_until"]>now) or not verify_password(body.password,user["password_hash"])
        if invalid:
            if user and user["status"]!="disabled":
                failures=int(user["failed_login_count"])+1;locked=now+timedelta(minutes=15) if failures>=5 else None
                conn.execute(text("UPDATE app_user SET failed_login_count=:count,locked_until=:locked,status=IF(:locked IS NULL,status,'locked') WHERE id=:id"),{"count":failures,"locked":locked,"id":user["id"]})
            failure_user={"id":user["id"],"username":user["username"]} if user else {"username":body.username}
        else:
            conn.execute(text("UPDATE app_user SET failed_login_count=0,locked_until=NULL,status='active',last_login_at=:now,last_login_ip=:ip WHERE id=:id"),{"now":now,"ip":request.client.host if request.client else "","id":user["id"]})
    if failure_user:
        audit("auth.login",request,failure_user,False,detail={"reason":"invalid_credentials"})
        raise HTTPException(401,"用户名或密码错误，连续失败 5 次将锁定 15 分钟")
    raw,session=create_session(user["id"],request);response.set_cookie(COOKIE_NAME,raw,max_age=7*86400,httponly=True,samesite="lax",secure=False,path="/")
    access=user_access(user["id"]);audit("auth.login",request,access,True);return {"user":access,"csrf_token":session["csrf_token"]}

@router.get("/me")
def me(user:dict=Depends(current_auth)):return user

@router.post("/logout")
def logout(request:Request,response:Response,user:dict=Depends(current_auth)):
    with engine().begin() as conn:conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE id=:id"),{"id":user["session_id"]})
    response.delete_cookie(COOKIE_NAME,path="/");audit("auth.logout",request,user);return {"ok":True}

@router.post("/change-password")
def change_password(body:ChangePasswordBody,request:Request,user:dict=Depends(current_auth)):
    if request.headers.get("x-csrf-token")!=user["csrf_token"]:raise HTTPException(403,"安全令牌无效")
    with engine().begin() as conn:
        encoded=conn.execute(text("SELECT password_hash FROM app_user WHERE id=:id"),{"id":user["id"]}).scalar_one()
        if not verify_password(body.current_password,encoded):raise HTTPException(400,"当前密码错误")
        try:new_hash=hash_password(body.new_password)
        except ValueError as exc:raise HTTPException(422,str(exc))
        conn.execute(text("UPDATE app_user SET password_hash=:password,must_change_password=0,password_changed_at=NOW() WHERE id=:id"),{"password":new_hash,"id":user["id"]});conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE user_id=:id AND id<>:session"),{"id":user["id"],"session":user["session_id"]})
    audit("auth.change_password",request,user);return {"ok":True}

@router.post("/reset-password")
def consume_reset(body:ResetConsumeBody,request:Request):
    try:new_hash=hash_password(body.new_password)
    except ValueError as exc:raise HTTPException(422,str(exc))
    with engine().begin() as conn:
        token=conn.execute(text("SELECT * FROM password_reset_token WHERE token_hash=:token AND used_at IS NULL AND expires_at>NOW()"),{"token":token_hash(body.token)}).mappings().first()
        if not token:raise HTTPException(400,"重置链接无效或已过期")
        conn.execute(text("UPDATE password_reset_token SET used_at=NOW() WHERE id=:id"),{"id":token["id"]});conn.execute(text("UPDATE app_user SET password_hash=:password,must_change_password=0,status='active',failed_login_count=0,locked_until=NULL,password_changed_at=NOW() WHERE id=:id"),{"password":new_hash,"id":token["user_id"]});conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE user_id=:id AND revoked_at IS NULL"),{"id":token["user_id"]})
    audit("auth.reset_password",request,{"id":token["user_id"]},True);return {"ok":True}

@router.get("/sessions")
def my_sessions(user:dict=Depends(current_auth)):
    with engine().connect() as conn:rows=conn.execute(text("SELECT id,ip_address,user_agent,created_at,last_active_at,expires_at,revoked_at FROM app_session WHERE user_id=:id ORDER BY created_at DESC"),{"id":user["id"]}).mappings()
    return [{**dict(row),"current":row["id"]==user["session_id"]} for row in rows]

@router.delete("/sessions/{session_id}")
def revoke_my_session(session_id:int,request:Request,user:dict=Depends(current_auth)):
    if request.headers.get("x-csrf-token")!=user["csrf_token"]:raise HTTPException(403,"安全令牌无效")
    with engine().begin() as conn:conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE id=:id AND user_id=:uid"),{"id":session_id,"uid":user["id"]})
    audit("session.revoke_own",request,user,resource_type="session",resource_id=session_id);return {"ok":True}
