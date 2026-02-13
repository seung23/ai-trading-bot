# data_manager.py
# XGBoost 전략용 데이터 엔진 (일봉 + 5분봉)
import yfinance as yf
import pandas_ta as ta
import pandas as pd
import numpy as np


# ══════════════════════════════════════════════════════════
# 5분봉 데이터 (기존 유지, backtester용)
# ══════════════════════════════════════════════════════════

def fetch_large_data(ticker):
    """60일치 5분봉 데이터 + 코스닥 지수를 수집합니다."""
    print(f"📥 {ticker} 및 코스닥 지수 60일 데이터 수집 중...")
    df = yf.download(tickers=ticker, period='60d', interval='5m')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={
        'Datetime': '시간', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })

    index_data = yf.download(tickers='^KQ11', period='60d', interval='5m')
    if isinstance(index_data.columns, pd.MultiIndex):
        index_data.columns = index_data.columns.get_level_values(0)
    index_data = index_data.reset_index()[['Datetime', 'Close']].rename(
        columns={'Datetime': '시간', 'Close': 'KOSDAQ_Index'}
    )

    df = pd.merge(df, index_data, on='시간', how='left').ffill()
    return df


def fetch_today_data(ticker):
    """당일 5분봉 데이터만 가볍게 다운로드합니다."""
    df = yf.download(tickers=ticker, period='1d', interval='5m')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={
        'Datetime': '시간', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })

    index_data = yf.download(tickers='^KQ11', period='1d', interval='5m')
    if isinstance(index_data.columns, pd.MultiIndex):
        index_data.columns = index_data.columns.get_level_values(0)
    index_data = index_data.reset_index()[['Datetime', 'Close']].rename(
        columns={'Datetime': '시간', 'Close': 'KOSDAQ_Index'}
    )

    df = pd.merge(df, index_data, on='시간', how='left').ffill()
    return df


def refresh_data(df_base, ticker):
    """기존 60일 데이터에 당일 최신 캔들을 덮어씌워 갱신합니다."""
    today = fetch_today_data(ticker)
    if today is None or len(today) == 0:
        return df_base

    yesterday_end = today['시간'].iloc[0]
    df_old = df_base[df_base['시간'] < yesterday_end].copy()
    df_merged = pd.concat([df_old, today], ignore_index=True)
    return df_merged


def add_indicators(df):
    """XGBoost 5분봉 학습용 피처를 계산합니다."""
    if len(df) < 50:
        return None

    bb = ta.bbands(df['종가'], length=20, std=2)
    if bb is not None:
        df['BB_Lower'] = bb.iloc[:, 0]
        df['BB_Mid'] = bb.iloc[:, 1]
        df['BB_Upper'] = bb.iloc[:, 2]
        bb_width = df['BB_Upper'] - df['BB_Lower']
        df['BB_Pct'] = np.where(bb_width > 0, (df['종가'] - df['BB_Lower']) / bb_width, 0.5)

    macd = ta.macd(df['종가'], fast=12, slow=26, signal=9)
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_Hist'] = macd.iloc[:, 1]
        df['MACD_Sig'] = macd.iloc[:, 2]

    df['MA5'] = ta.sma(df['종가'], length=5)
    df['MA20'] = ta.sma(df['종가'], length=20)
    df['MA60'] = ta.sma(df['종가'], length=60)
    df['RSI'] = ta.rsi(df['종가'], length=14)

    stoch_rsi = ta.stochrsi(df['종가'], length=14)
    if stoch_rsi is not None:
        df['StochRSI_K'] = stoch_rsi.iloc[:, 0]
        df['StochRSI_D'] = stoch_rsi.iloc[:, 1]

    df['ATR'] = ta.atr(df['고가'], df['저가'], df['종가'], length=14)

    df['Vol_Avg'] = df['거래량'].rolling(window=20).mean()
    df['Vol_Ratio'] = np.where(df['Vol_Avg'] > 0, df['거래량'] / df['Vol_Avg'], 1.0)
    df['Vol_Spike'] = (df['Vol_Ratio'] > 2.0).astype(int)

    candle_range = df['고가'] - df['저가']
    df['Body_Ratio'] = np.where(candle_range > 0, (df['종가'] - df['시가']) / candle_range, 0)
    df['Ret_1'] = df['종가'].pct_change(1)
    df['Ret_3'] = df['종가'].pct_change(3)
    df['Ret_6'] = df['종가'].pct_change(6)
    df['Ret_12'] = df['종가'].pct_change(12)
    df['MA5_Dist'] = np.where(df['MA5'] > 0, (df['종가'] / df['MA5'] - 1) * 100, 0)
    df['MA20_Dist'] = np.where(df['MA20'] > 0, (df['종가'] / df['MA20'] - 1) * 100, 0)
    df['Intraday_Pos'] = np.where(candle_range > 0, (df['종가'] - df['저가']) / candle_range, 0.5)

    if 'KOSDAQ_Index' in df.columns:
        df['KQ_Ret_1'] = df['KOSDAQ_Index'].pct_change(1)
        df['KQ_Ret_6'] = df['KOSDAQ_Index'].pct_change(6)
        df['Spread'] = df['Ret_1'] - df['KQ_Ret_1']

    df['VOL'] = df['고가'] - df['저가']
    df['Vol_6'] = df['종가'].rolling(6).std()

    lookahead = 6
    profit_target = 0.008  # 0.8% (5분봉 단타용, 1.5%에서 하향)
    target = pd.Series(0, index=df.index)
    for i in range(len(df) - lookahead):
        current_price = df['종가'].iloc[i]
        future_highs = df['고가'].iloc[i + 1:i + 1 + lookahead]
        if len(future_highs) > 0:
            max_profit = (future_highs / current_price - 1).max()
            if max_profit >= profit_target:
                target.iloc[i] = 1
    df['target'] = target

    df.dropna(inplace=True)
    return df


FEATURES = [
    '종가', 'MA5', 'MA20', 'RSI',
    'BB_Pct', 'MACD', 'MACD_Hist',
    'StochRSI_K', 'StochRSI_D', 'ATR',
    'Vol_Ratio', 'Vol_Spike', 'Body_Ratio',
    'Ret_1', 'Ret_3', 'Ret_6', 'Ret_12',
    'MA5_Dist', 'MA20_Dist', 'Intraday_Pos',
    'VOL', 'Vol_6', '거래량',
]
FEATURES_WITH_INDEX = FEATURES + ['KQ_Ret_1', 'KQ_Ret_6', 'Spread']


def get_feature_columns(df):
    """데이터프레임에 존재하는 피처만 필터링하여 반환합니다."""
    all_features = FEATURES_WITH_INDEX
    return [f for f in all_features if f in df.columns]


# ══════════════════════════════════════════════════════════
# 일봉 데이터 (AI 일봉 전략 - main.py용)
# ══════════════════════════════════════════════════════════

DAILY_FEATURES = [
    '종가', 'MA5', 'MA20', 'RSI', 'VOL', '거래량',
    'BB_Upper', 'BB_Lower', 'Vol_Ratio', 'MACD', 'MACD_Sig',
]


def fetch_daily_data(ticker):
    """1년치 일봉 데이터를 수집합니다."""
    print(f"📥 {ticker} 1년치 일봉 데이터 수집 중...")
    df = yf.download(ticker, period='1y', interval='1d')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index().rename(columns={
        'Date': '날짜', 'Close': '종가', 'High': '고가',
        'Low': '저가', 'Open': '시가', 'Volume': '거래량'
    })
    print(f"   총 {len(df)}개 일봉 로드 완료")
    return df


def add_daily_indicators(df):
    """일봉 기술 지표 + XGBoost 타겟을 계산합니다."""
    if len(df) < 30:
        return None

    df['MA5'] = ta.sma(df['종가'], length=5)
    df['MA20'] = ta.sma(df['종가'], length=20)
    df['RSI'] = ta.rsi(df['종가'], length=14)

    bb = ta.bbands(df['종가'], length=20, std=2)
    if bb is not None:
        df['BB_Lower'] = bb.iloc[:, 0]
        df['BB_Upper'] = bb.iloc[:, 2]

    macd = ta.macd(df['종가'])
    if macd is not None:
        df['MACD'] = macd.iloc[:, 0]
        df['MACD_Sig'] = macd.iloc[:, 2]

    df['VOL'] = df['고가'] - df['저가']
    df['Vol_Avg'] = df['거래량'].rolling(window=10).mean()
    df['Vol_Ratio'] = df['거래량'] / df['Vol_Avg']

    # 타겟: 다음날 시가 매수 시, 향후 5일 이내 3% 수익 도달 여부
    # (실제 매매: 어제 데이터로 예측 → 오늘 시가에 매수)
    lookahead = 5
    profit_target = 0.03
    target = pd.Series(0, index=df.index)
    for i in range(len(df) - lookahead - 1):
        entry_price = df['시가'].iloc[i + 1]  # 다음날 시가 (실제 진입가)
        if entry_price <= 0:
            continue
        future_highs = df['고가'].iloc[i + 1:i + 1 + lookahead]
        max_profit = (future_highs / entry_price - 1).max()
        if max_profit >= profit_target:
            target.iloc[i] = 1
    df['target'] = target

    df.dropna(inplace=True)
    return df


def get_daily_feature_columns(df):
    """일봉 피처 중 데이터프레임에 존재하는 것만 반환합니다."""
    return [f for f in DAILY_FEATURES if f in df.columns]
