"""Local recovery/bootstrap commands for application accounts."""
import argparse,getpass,secrets,string,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sqlalchemy import text
from backend.app.database import engine,init_schema
from backend.app.services.auth_service import create_user,hash_password

def generated_password(length=18):
    alphabet=string.ascii_letters+string.digits+"!@#%"
    while True:
        value="".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.isalpha() for c in value) and any(c.isdigit() for c in value):return value

def create_admin(args):
    password=generated_password() if args.generate else getpass.getpass("Initial password: ")
    with engine().connect() as conn:
        if conn.execute(text("SELECT 1 FROM app_user WHERE username=:name"),{"name":args.username.lower()}).first():raise SystemExit("Account already exists")
        role_id=conn.execute(text("SELECT id FROM app_role WHERE role_code='admin'")).scalar_one()
    create_user(args.username,password,args.display_name,None,None,[role_id],must_change=False)
    print(f"Created administrator: {args.username}")
    if args.generate:print(f"One-time initial password: {password}")

def reset_password(args):
    password=generated_password() if args.generate else getpass.getpass("New password: ")
    encoded=hash_password(password)
    with engine().begin() as conn:
        result=conn.execute(text("UPDATE app_user SET password_hash=:password,must_change_password=0,status='active',failed_login_count=0,locked_until=NULL WHERE username=:name"),{"password":encoded,"name":args.username.lower()})
        if not result.rowcount:raise SystemExit("Account not found")
        conn.execute(text("UPDATE app_session s JOIN app_user u ON u.id=s.user_id SET s.revoked_at=NOW() WHERE u.username=:name AND s.revoked_at IS NULL"),{"name":args.username.lower()})
    print(f"Reset account: {args.username}")
    if args.generate:print(f"One-time initial password: {password}")

def list_users(_args):
    with engine().connect() as conn:
        rows=conn.execute(text("SELECT username,display_name,status,must_change_password,last_login_at FROM app_user ORDER BY id")).mappings()
        for row in rows:print(f"{row['username']:<20} {row['status']:<9} force_change={bool(row['must_change_password'])} last_login={row['last_login_at'] or '-'}")

def main():
    parser=argparse.ArgumentParser(description="Manage Stock Lab accounts")
    commands=parser.add_subparsers(required=True)
    create=commands.add_parser("create-admin");create.add_argument("--username",default="admin");create.add_argument("--display-name",default="管理员");create.add_argument("--generate",action="store_true");create.set_defaults(func=create_admin)
    reset=commands.add_parser("reset-password");reset.add_argument("--username",required=True);reset.add_argument("--generate",action="store_true");reset.set_defaults(func=reset_password)
    listing=commands.add_parser("list");listing.set_defaults(func=list_users)
    args=parser.parse_args();init_schema();args.func(args)

if __name__=="__main__":main()
