#!/usr/bin/env python3
"""
전략 엔진 테스트 스크립트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import pandas as pd
from app.data import data_manager
from app.strategy import strategy_engine
from app.indicators import indicator_analyzer

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_indicators():
    """기술적 지표 테스트"""
    print("=== 기술적 지표 테스트 ===")
    
    try:
        # 1. 데이터 수집
        print("1. 데이터 수집...")
        ohlcv_data = data_manager.collector.get_ohlcv_data(timeframe='1h', limit=100)
        
        if ohlcv_data.empty:
            print("❌ 데이터 수집 실패")
            return False
        
        print(f"✅ {len(ohlcv_data)}개 1시간봉 데이터 수집 완료")
        
        # 2. 지표 계산
        print("\n2. 기술적 지표 계산...")
        config_params = {
            'ema_fast': 20,
            'ema_slow': 50,
            'atr_len': 14,
            'trail_atr_mult': 3.0
        }
        
        data_with_indicators = indicator_analyzer.calculate_all_indicators(ohlcv_data, config_params)
        
        if data_with_indicators.empty:
            print("❌ 지표 계산 실패")
            return False
        
        print(f"✅ 지표 계산 완료: {len(data_with_indicators.columns)}개 컬럼")
        
        # 3. 최신 지표 값 출력
        print("\n3. 최신 지표 값:")
        latest = data_with_indicators.iloc[-1]
        
        print(f"   현재가: {latest['close']:,.0f}원")
        print(f"   EMA20: {latest.get('ema_20', 0):,.0f}원")
        print(f"   EMA50: {latest.get('ema_50', 0):,.0f}원")
        print(f"   ATR: {latest.get('atr', 0):,.0f}원")
        print(f"   RSI: {latest.get('rsi', 0):.1f}")
        
        # 4. 추세 방향 확인
        print("\n4. 추세 분석:")
        trend = indicator_analyzer.get_trend_direction(data_with_indicators, 'ema_20', 'ema_50')
        current_trend = trend.iloc[-1]
        
        if current_trend == 1:
            print("   📈 상승 추세")
        elif current_trend == -1:
            print("   📉 하락 추세")
        else:
            print("   ➡️ 횡보")
        
        return True
        
    except Exception as e:
        print(f"❌ 지표 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_strategies():
    """전략 시그널 테스트"""
    print("\n=== 전략 시그널 테스트 ===")
    
    try:
        # 1. 데이터 수집 (더 많은 데이터 필요)
        print("1. 전략용 데이터 수집...")
        ohlcv_data = data_manager.collector.get_ohlcv_data(timeframe='1h', limit=200)
        
        if len(ohlcv_data) < 100:
            print("❌ 충분한 데이터가 없습니다")
            return False
        
        print(f"✅ {len(ohlcv_data)}개 데이터 수집 완료")
        
        # 2. 전략별 시그널 생성
        print("\n2. 전략별 시그널 생성...")
        all_signals = strategy_engine.generate_all_signals(ohlcv_data)
        
        total_signals = 0
        for strategy_name, signals in all_signals.items():
            signal_count = len(signals)
            total_signals += signal_count
            print(f"   {strategy_name}: {signal_count}개 시그널")
            
            # 최근 시그널 출력
            if signals:
                latest_signal = max(signals, key=lambda s: s.timestamp)
                print(f"     → 최근: {latest_signal.signal_type.value} @ {latest_signal.price:,.0f}원 "
                      f"(신뢰도: {latest_signal.confidence:.2f})")
        
        print(f"\n   총 {total_signals}개 시그널 생성")
        
        # 3. 통합 시그널 생성
        print("\n3. 통합 시그널 생성...")
        combined_signal = strategy_engine.get_combined_signal(ohlcv_data)
        
        if combined_signal:
            print(f"✅ 통합 시그널: {combined_signal.signal_type.value}")
            print(f"   가격: {combined_signal.price:,.0f}원")
            print(f"   신뢰도: {combined_signal.confidence:.2f}")
            print(f"   전략: {combined_signal.metadata.get('strategy', 'unknown')}")
            if combined_signal.stop_loss:
                print(f"   손절가: {combined_signal.stop_loss:,.0f}원")
        else:
            print("⚠️  현재 유효한 통합 시그널 없음")
        
        # 4. 전략 상태 확인
        print("\n4. 전략 엔진 상태:")
        status = strategy_engine.get_strategy_status()
        print(f"   활성 전략: {', '.join(status['active_strategies'])}")
        print(f"   메인 전략: {status['main_strategy']}")
        
        return True
        
    except Exception as e:
        print(f"❌ 전략 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_backtest_sample():
    """간단한 백테스트 샘플"""
    print("\n=== 백테스트 샘플 ===")
    
    try:
        # 과거 데이터로 시그널 테스트
        print("1. 과거 데이터 수집...")
        historical_data = data_manager.collector.get_historical_data(timeframe='1h', days=7)
        
        if len(historical_data) < 100:
            print("❌ 충분한 과거 데이터가 없습니다")
            return False
        
        print(f"✅ {len(historical_data)}개 과거 데이터 수집")
        
        # 시그널 생성 및 분석
        print("\n2. 과거 시그널 분석...")
        all_signals = strategy_engine.generate_all_signals(historical_data)
        
        # 전략별 성과 요약
        for strategy_name, signals in all_signals.items():
            if not signals:
                continue
                
            buy_signals = [s for s in signals if s.signal_type.value == 'buy']
            sell_signals = [s for s in signals if s.signal_type.value == 'sell']
            
            print(f"\n   {strategy_name}:")
            print(f"     매수 시그널: {len(buy_signals)}개")
            print(f"     매도 시그널: {len(sell_signals)}개")
            
            if buy_signals:
                avg_confidence = sum(s.confidence for s in buy_signals) / len(buy_signals)
                print(f"     평균 신뢰도: {avg_confidence:.2f}")
        
        return True
        
    except Exception as e:
        print(f"❌ 백테스트 샘플 실패: {e}")
        return False

def main():
    """메인 테스트 함수"""
    print("🚀 전략 엔진 종합 테스트 시작\n")
    
    success_count = 0
    total_tests = 3
    
    # 1. 지표 테스트
    if test_indicators():
        success_count += 1
    
    # 2. 전략 테스트
    if test_strategies():
        success_count += 1
    
    # 3. 백테스트 샘플
    if test_backtest_sample():
        success_count += 1
    
    # 결과 요약
    print(f"\n{'='*50}")
    print(f"테스트 결과: {success_count}/{total_tests} 성공")
    
    if success_count == total_tests:
        print("🎉 모든 테스트 통과!")
        return True
    else:
        print("⚠️  일부 테스트 실패")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
