import os
import psycopg
from psycopg_pool import AsyncConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/physio")

pool = AsyncConnectionPool(conninfo=DATABASE_URL, open=False)

async def get_db_pool():
    if pool is None:
        await pool.open()
    return pool
