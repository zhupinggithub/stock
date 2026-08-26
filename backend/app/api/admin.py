import json,secrets
from datetime import datetime,timedelta
from fastapi import APIRouter,Depends,HTTPException,Query,Request
from sqlalchemy import text
from backend.app.database import engine
from backend.app.repositories.query_repository import fetch_all,fetch_one
from backend.app.schemas.auth import RoleCreate,RoleUpdate,UserCreate,UserStatus,UserUpdate
from backend.app.services.auth_service import audit,create_user,require_permission,token_hash

router=APIRouter(tags=["account-management"])

@router.get("/users")
def users(_:dict=Depends(require_permission("user:view"))):
    values=fetch_all("""SELECT u.id,u.username,u.display_name,u.email,u.mobile,u.status,u.must_change_password,u.last_login_at,u.last_login_ip,u.created_at FROM app_user u ORDER BY u.id""")
    roles=fetch_all("SELECT ur.user_id,r.id,r.role_code,r.role_name FROM app_user_role ur JOIN app_role r ON r.id=ur.role_id")
    for value in values:value["roles"]=[r for r in roles if r["user_id"]==value["id"]]
    return values

@router.post("/users",status_code=201)
def add_user(body:UserCreate,request:Request,user:dict=Depends(require_permission("user:create"))):
    try:uid=create_user(body.username,body.password,body.display_name,body.email,body.mobile,body.role_ids,user["id"])
    except ValueError as exc:raise HTTPException(422,str(exc))
    except Exception as exc:raise HTTPException(409,"用户名或邮箱已存在") from exc
    audit("user.create",request,user,resource_type="user",resource_id=uid,detail={"username":body.username});return {"id":uid}

@router.put("/users/{user_id}")
def edit_user(user_id:int,body:UserUpdate,request:Request,user:dict=Depends(require_permission("user:update"))):
    with engine().begin() as conn:
        if not conn.execute(text("SELECT id FROM app_user WHERE id=:id"),{"id":user_id}).scalar():raise HTTPException(404,"用户不存在")
        conn.execute(text("UPDATE app_user SET display_name=:name,email=:email,mobile=:mobile WHERE id=:id"),{"name":body.display_name,"email":body.email or None,"mobile":body.mobile or None,"id":user_id});conn.execute(text("DELETE FROM app_user_role WHERE user_id=:id"),{"id":user_id})
        if body.role_ids:conn.execute(text("INSERT INTO app_user_role(user_id,role_id) VALUES(:uid,:rid)"),[{"uid":user_id,"rid":rid} for rid in body.role_ids])
    audit("user.update",request,user,resource_type="user",resource_id=user_id);return {"ok":True}

@router.put("/users/{user_id}/status")
def change_status(user_id:int,body:UserStatus,request:Request,user:dict=Depends(require_permission("user:disable"))):
    if user_id==user["id"] and body.status=="disabled":raise HTTPException(400,"不能禁用当前登录账号")
    with engine().begin() as conn:
        if body.status=="disabled":
            admins=conn.execute(text("""SELECT COUNT(DISTINCT u.id) FROM app_user u JOIN app_user_role ur ON ur.user_id=u.id JOIN app_role r ON r.id=ur.role_id WHERE r.role_code='admin' AND u.status='active'""")).scalar_one();is_admin=conn.execute(text("SELECT 1 FROM app_user_role ur JOIN app_role r ON r.id=ur.role_id WHERE ur.user_id=:id AND r.role_code='admin'"),{"id":user_id}).scalar()
            if is_admin and admins<=1:raise HTTPException(400,"系统必须保留至少一个有效管理员")
        conn.execute(text("UPDATE app_user SET status=:status WHERE id=:id"),{"status":body.status,"id":user_id})
        if body.status=="disabled":conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE user_id=:id AND revoked_at IS NULL"),{"id":user_id})
    audit("user.status",request,user,resource_type="user",resource_id=user_id,detail={"status":body.status});return {"ok":True}

@router.post("/users/{user_id}/reset-token")
def reset_token(user_id:int,request:Request,user:dict=Depends(require_permission("user:reset_password"))):
    raw=secrets.token_urlsafe(36);expires=datetime.now()+timedelta(hours=1)
    with engine().begin() as conn:
        if not conn.execute(text("SELECT id FROM app_user WHERE id=:id"),{"id":user_id}).scalar():raise HTTPException(404,"用户不存在")
        conn.execute(text("UPDATE password_reset_token SET used_at=NOW() WHERE user_id=:id AND used_at IS NULL"),{"id":user_id});conn.execute(text("INSERT INTO password_reset_token(user_id,token_hash,expires_at,created_by) VALUES(:uid,:token,:expires,:creator)"),{"uid":user_id,"token":token_hash(raw),"expires":expires,"creator":user["id"]})
    audit("user.reset_token",request,user,resource_type="user",resource_id=user_id);return {"token":raw,"expires_at":expires.isoformat()}

@router.get("/permissions")
def permissions(_:dict=Depends(require_permission("role:view"))):return fetch_all("SELECT * FROM app_permission ORDER BY permission_group,permission_code")

@router.get("/roles")
def roles(_:dict=Depends(require_permission("role:view"))):
    values=fetch_all("SELECT * FROM app_role ORDER BY is_system DESC,id");links=fetch_all("SELECT role_id,permission_id FROM app_role_permission")
    for value in values:value["permission_ids"]=[x["permission_id"] for x in links if x["role_id"]==value["id"]]
    return values

@router.post("/roles",status_code=201)
def add_role(body:RoleCreate,request:Request,user:dict=Depends(require_permission("role:manage"))):
    try:
        with engine().begin() as conn:
            result=conn.execute(text("INSERT INTO app_role(role_code,role_name,description) VALUES(:code,:name,:description)"),{"code":body.role_code,"name":body.role_name,"description":body.description});rid=int(result.lastrowid)
            if body.permission_ids:conn.execute(text("INSERT INTO app_role_permission(role_id,permission_id) VALUES(:rid,:pid)"),[{"rid":rid,"pid":pid} for pid in body.permission_ids])
    except Exception as exc:raise HTTPException(409,"角色代码已存在") from exc
    audit("role.create",request,user,resource_type="role",resource_id=rid);return {"id":rid}

@router.put("/roles/{role_id}")
def edit_role(role_id:int,body:RoleUpdate,request:Request,user:dict=Depends(require_permission("role:manage"))):
    with engine().begin() as conn:
        role=conn.execute(text("SELECT is_system FROM app_role WHERE id=:id"),{"id":role_id}).mappings().first()
        if not role:raise HTTPException(404,"角色不存在")
        if role["is_system"]:raise HTTPException(400,"系统角色不可修改")
        conn.execute(text("UPDATE app_role SET role_name=:name,description=:description WHERE id=:id"),{"name":body.role_name,"description":body.description,"id":role_id});conn.execute(text("DELETE FROM app_role_permission WHERE role_id=:id"),{"id":role_id})
        if body.permission_ids:conn.execute(text("INSERT INTO app_role_permission(role_id,permission_id) VALUES(:rid,:pid)"),[{"rid":role_id,"pid":pid} for pid in body.permission_ids])
    audit("role.update",request,user,resource_type="role",resource_id=role_id);return {"ok":True}

@router.delete("/roles/{role_id}")
def delete_role(role_id:int,request:Request,user:dict=Depends(require_permission("role:manage"))):
    with engine().begin() as conn:
        role=conn.execute(text("SELECT is_system FROM app_role WHERE id=:id"),{"id":role_id}).mappings().first()
        if not role:raise HTTPException(404,"角色不存在")
        if role["is_system"]:raise HTTPException(400,"系统角色不可删除")
        conn.execute(text("DELETE FROM app_role WHERE id=:id"),{"id":role_id})
    audit("role.delete",request,user,resource_type="role",resource_id=role_id);return {"ok":True}

@router.get("/sessions")
def sessions(user_id:int|None=None,user:dict=Depends(require_permission("session:manage"))):return fetch_all("""SELECT s.id,s.user_id,u.username,u.display_name,s.ip_address,s.user_agent,s.created_at,s.last_active_at,s.expires_at,s.revoked_at FROM app_session s JOIN app_user u ON u.id=s.user_id WHERE (:uid IS NULL OR s.user_id=:uid) ORDER BY s.created_at DESC LIMIT 500""",{"uid":user_id})

@router.delete("/sessions/{session_id}")
def revoke_session(session_id:int,request:Request,user:dict=Depends(require_permission("session:manage"))):
    with engine().begin() as conn:conn.execute(text("UPDATE app_session SET revoked_at=NOW() WHERE id=:id"),{"id":session_id})
    audit("session.revoke",request,user,resource_type="session",resource_id=session_id);return {"ok":True}

@router.get("/audit-logs")
def audit_logs(action:str="",username:str="",success:int|None=None,page:int=Query(1,ge=1),page_size:int=Query(50,ge=10,le=200),_:dict=Depends(require_permission("audit:view"))):
    where=["1=1"];params={"limit":page_size,"offset":(page-1)*page_size}
    if action:where.append("action LIKE :action");params["action"]=f"%{action}%"
    if username:where.append("username LIKE :username");params["username"]=f"%{username}%"
    if success is not None:where.append("success=:success");params["success"]=success
    clause=" AND ".join(where);total=fetch_one(f"SELECT COUNT(*) total FROM audit_log WHERE {clause}",params)["total"];items=fetch_all(f"SELECT * FROM audit_log WHERE {clause} ORDER BY id DESC LIMIT :limit OFFSET :offset",params);return {"items":items,"total":total,"page":page,"pages":max(1,(total+page_size-1)//page_size)}
