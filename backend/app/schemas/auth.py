from pydantic import BaseModel,Field
from typing import Literal

class LoginBody(BaseModel):username:str;password:str
class RegisterBody(BaseModel):
    username:str=Field(min_length=3,max_length=50,pattern=r'^[A-Za-z][A-Za-z0-9_]{2,49}$');password:str;display_name:str=Field(min_length=1,max_length=100);email:str|None=None;mobile:str|None=None
class ChangePasswordBody(BaseModel):current_password:str;new_password:str
class ResetConsumeBody(BaseModel):token:str;new_password:str
class UserCreate(BaseModel):
    username:str=Field(min_length=3,max_length=50);password:str;display_name:str=Field(min_length=1,max_length=100);email:str|None=None;mobile:str|None=None;role_ids:list[int]=[]
class UserUpdate(BaseModel):display_name:str;email:str|None=None;mobile:str|None=None;role_ids:list[int]=[]
class UserStatus(BaseModel):status:Literal['active','disabled']
class RoleCreate(BaseModel):role_code:str=Field(pattern=r'^[a-z][a-z0-9_]{2,49}$');role_name:str;description:str|None=None;permission_ids:list[int]=[]
class RoleUpdate(BaseModel):role_name:str;description:str|None=None;permission_ids:list[int]=[]
