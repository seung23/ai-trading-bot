# model.py
# XGBoost 모델 학습/예측/저장/로드
# 레버리지 ETF 5분봉 단타에 최적화된 하이퍼파라미터
import os
import pandas as pd
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report


def train_model(df, features):
    """
    XGBoost 모델을 학습합니다.
    - 시계열 순서 유지 (shuffle=False)
    - 클래스 불균형 자동 보정 (scale_pos_weight)
    - 과적합 방지를 위한 regularization
    """
    X = df[features]
    y = df['target']

    # 시계열이므로 shuffle=False
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, shuffle=False
    )

    # 클래스 불균형 보정 (매수 신호는 전체의 일부)
    pos_count = y_train.sum()
    neg_count = len(y_train) - pos_count
    scale_weight = neg_count / pos_count if pos_count > 0 else 1.0

    model = XGBClassifier(
        n_jobs=-1,
        n_estimators=300,
        learning_rate=0.05,
        max_depth=6,
        min_child_weight=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=0.1,          # L1 정규화
        reg_lambda=1.0,         # L2 정규화
        scale_pos_weight=scale_weight,
        eval_metric='logloss',
        random_state=42,
    )

    print(f"🧠 XGBoost 학습 시작 (피처 {len(features)}개, 데이터 {len(X_train)}행)")
    print(f"   클래스 비율 - 매수신호: {pos_count}개 ({pos_count/len(y_train)*100:.1f}%) / 대기: {neg_count}개")

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )

    # 평가
    preds = model.predict(X_test)
    acc = accuracy_score(y_test, preds)

    print(f"🎯 모델 학습 완료! 전체 정확도: {acc:.2%}")
    print(classification_report(
        y_test, preds, target_names=['대기', '매수신호'], zero_division=0
    ))

    # 피처 중요도 상위 10개
    importances = model.feature_importances_
    feat_imp = sorted(zip(features, importances), key=lambda x: x[1], reverse=True)
    print("📊 피처 중요도 TOP 10:")
    for name, imp in feat_imp[:10]:
        bar = "█" * int(imp * 50)
        print(f"   {name:15s} {imp:.3f} {bar}")

    return model


def predict_signal(model, row_data, features, threshold=0.60):
    """
    단일 캔들 데이터에 대해 매수 신호를 예측합니다.

    Returns:
        (signal, probability)
        signal: 'BUY' | 'HOLD'
        probability: 상승 확률 (0.0 ~ 1.0)
    """
    input_df = pd.DataFrame([row_data[features].values], columns=features)
    prob = model.predict_proba(input_df)[0][1]

    if prob >= threshold:
        return 'BUY', prob
    return 'HOLD', prob


def save_model(model, filename="trading_brain.json"):
    model.save_model(filename)
    print(f"💾 모델을 '{filename}'으로 저장했습니다.")


def load_model(filename="trading_brain.json"):
    if not os.path.exists(filename):
        print(f"⚠️ 저장된 모델 '{filename}'이 없습니다.")
        return None
    loaded = XGBClassifier()
    loaded.load_model(filename)
    print(f"📂 저장된 모델 '{filename}'을 불러왔습니다.")
    return loaded
