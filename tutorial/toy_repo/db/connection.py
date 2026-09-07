"""数据库连接。全局唯一出口，别在别处自己连。"""

import sqlite3

DB_PATH = "app.db"


def get_conn():
    """拿一个连接。行结果按 dict 返回，方便直接解包。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query_one(sql, *params):
    """查单行。查不到返回 None，不抛异常。"""
    conn = get_conn()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(sql, *params):
    """写操作。自动提交，失败回滚。"""
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
