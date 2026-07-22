from sqlalchemy import select

from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models.auth import User


DEMO_USERS = (
    ("executive", "AlphaExec!2026", "经营负责人", "executive", None),
    ("regional", "AlphaRegion!2026", "区域运营经理", "regional_manager", "R01"),
    ("analyst", "AlphaAnalyst!2026", "数据分析师/管理员", "analyst_admin", None),
)


def bootstrap_demo_users() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        for username, password, display_name, role, region_code in DEMO_USERS:
            if db.scalar(select(User.id).where(User.username == username)) is None:
                db.add(User(username=username, password_hash=hash_password(password), display_name=display_name, role=role, region_code=region_code))
        db.commit()
