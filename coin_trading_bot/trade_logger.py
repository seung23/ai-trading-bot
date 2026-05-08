# trade_logger.py
# 거래 로그 + 피처 SQLite 저장 전담 모듈
# ──────────────────────────────────────────────────────────
# - 모든 DB 연결은 호출 시 열고 즉시 닫기 (메모리 점유 방지)
# - DB 저장 실패가 봇 운영을 멈추면 안 됨 (try-except)
# ──────────────────────────────────────────────────────────
import os
import sqlite3
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

DEFAULT_DB_PATH = os.environ.get("TRADE_DB_PATH", os.path.expanduser("~/trades.db"))

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 거래 정보
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    symbol TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    position_size REAL,
    pnl_pct REAL,
    exit_reason TEXT,

    -- 변동성 돌파 핵심 피처
    k_value REAL,
    target_price REAL,

    -- 노이즈 비율 (평균 방식)
    noise_1d REAL,
    noise_avg_3d REAL,
    noise_avg_7d REAL,
    noise_avg_14d REAL,

    -- 노이즈 비율 (윈도우 방식)
    noise_window_3d REAL,
    noise_window_7d REAL,
    noise_window_14d REAL,

    -- 거래량 / 시장 환경
    volume_ratio REAL,
    btc_trend TEXT,
    btc_24h_change_pct REAL,

    -- 시간 정보
    hour_kst INTEGER,
    day_of_week INTEGER,

    -- 어제 OHLC (raw)
    prev_open REAL,
    prev_high REAL,
    prev_low REAL,
    prev_close REAL,
    prev_volume REAL
);
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_entry_time ON trades(entry_time);",
    "CREATE INDEX IF NOT EXISTS idx_symbol ON trades(symbol);",
]


def init_db(db_path=None):
    """테이블이 없으면 생성. 이미 있으면 스킵."""
    db_path = db_path or DEFAULT_DB_PATH
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(CREATE_TABLE_SQL)
        for idx_sql in CREATE_INDEX_SQL:
            cur.execute(idx_sql)
        conn.commit()
        conn.close()
        print(f"   [TradeLogger] DB 초기화 완료: {db_path}")
    except Exception as e:
        print(f"   [TradeLogger] DB 초기화 실패: {e}")


def log_entry(features, db_path=None):
    """진입 시점 호출. 거래 ID(int) 반환. 실패 시 None."""
    db_path = db_path or DEFAULT_DB_PATH
    try:
        entry_time = datetime.now(KST).isoformat()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO trades (
                entry_time, symbol, entry_price, position_size,
                k_value, target_price,
                noise_1d, noise_avg_3d, noise_avg_7d, noise_avg_14d,
                noise_window_3d, noise_window_7d, noise_window_14d,
                volume_ratio, btc_trend, btc_24h_change_pct,
                hour_kst, day_of_week,
                prev_open, prev_high, prev_low, prev_close, prev_volume
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?, ?, ?, ?
            )
        """, (
            entry_time,
            features.get("symbol"),
            features.get("entry_price"),
            features.get("position_size"),
            features.get("k_value"),
            features.get("target_price"),
            features.get("noise_1d"),
            features.get("noise_avg_3d"),
            features.get("noise_avg_7d"),
            features.get("noise_avg_14d"),
            features.get("noise_window_3d"),
            features.get("noise_window_7d"),
            features.get("noise_window_14d"),
            features.get("volume_ratio"),
            features.get("btc_trend"),
            features.get("btc_24h_change_pct"),
            features.get("hour_kst"),
            features.get("day_of_week"),
            features.get("prev_open"),
            features.get("prev_high"),
            features.get("prev_low"),
            features.get("prev_close"),
            features.get("prev_volume"),
        ))
        conn.commit()
        trade_id = cur.lastrowid
        conn.close()
        print(f"   [TradeLogger] 진입 기록 완료 (trade_id={trade_id})")
        return trade_id
    except Exception as e:
        print(f"   [TradeLogger] 진입 기록 실패: {e}")
        return None


def log_exit(trade_id, exit_price, pnl_pct, exit_reason, db_path=None):
    """청산 시점 호출. 성공 시 True, 실패 시 False."""
    db_path = db_path or DEFAULT_DB_PATH
    if trade_id is None:
        print("   [TradeLogger] trade_id가 None이므로 청산 기록 스킵")
        return False
    try:
        exit_time = datetime.now(KST).isoformat()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            UPDATE trades
            SET exit_time = ?, exit_price = ?, pnl_pct = ?, exit_reason = ?
            WHERE id = ?
        """, (exit_time, exit_price, pnl_pct, exit_reason, trade_id))
        conn.commit()
        conn.close()
        print(f"   [TradeLogger] 청산 기록 완료 (trade_id={trade_id}, pnl={pnl_pct:+.2f}%)")
        return True
    except Exception as e:
        print(f"   [TradeLogger] 청산 기록 실패: {e}")
        return False
