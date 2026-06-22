# backend/alembic/env.py

import os
import sys
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 1. 경로 설정 (이게 있어야 app을 찾음)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 2. 우리가 만든 설정 임포트
from app.core.config import settings 
from app.db.base import Base

config = context.config
fileConfig(config.config_file_name)

# 3. [핵심] 설정값 주입
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

target_metadata = Base.metadata

# ... (이하 기존 run_migrations_online 함수 코드들) ...
