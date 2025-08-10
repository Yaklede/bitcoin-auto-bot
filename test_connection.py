#!/usr/bin/env python3
"""
Upbit API 연결 테스트 스크립트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
from app.data import data_manager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_upbit_connection():
    """Upbit API 연결 테스트"""
    print("=== Upbit API 연결 테스트 ===")
    
    try:
        # 1. 연결 테스트
        print("1. 연결 테스트...")
        if data_manager.collector.test_connection():
            print("✅ 연결 성공")
        else:
            print("❌ 연결 실패")
            return False
        
        # 2. 현재 가격 조회
        print("\n2. 현재 가격 조회...")
        try:
            price_data = data_manager.collector.get_current_price()
            print(f"✅ {price_data['symbol']}: {price_data['last']:,}원")
            print(f"   변동률: {price_data['percentage']:.2f}%")
        except Exception as e:
            print(f"❌ 현재 가격 조회 실패: {e}")
        
        # 3. 계좌 잔고 조회 (API 키가 있는 경우)
        print("\n3. 계좌 잔고 조회...")
        try:
            balance = data_manager.collector.get_account_balance()
            print(f"✅ KRW 잔고: {balance['krw']['total']:,.0f}원")
            print(f"   BTC 잔고: {balance['btc']['total']:.8f} BTC")
        except Exception as e:
            print(f"⚠️  계좌 조회 실패: {e}")
        
        # 4. OHLCV 데이터 조회
        print("\n4. OHLCV 데이터 조회...")
        try:
            ohlcv_data = data_manager.collector.get_ohlcv_data(timeframe='1m', limit=10)
            if not ohlcv_data.empty:
                print(f"✅ 1분봉 데이터 {len(ohlcv_data)}개 조회 성공")
                print(f"   최신 데이터: {ohlcv_data.index[-1]} - 종가: {ohlcv_data['close'].iloc[-1]:,}원")
            else:
                print("❌ OHLCV 데이터 조회 실패")
        except Exception as e:
            print(f"❌ OHLCV 데이터 조회 실패: {e}")
        
        # 5. 호가 정보 조회
        print("\n5. 호가 정보 조회...")
        try:
            orderbook = data_manager.collector.get_orderbook(limit=5)
            print(f"✅ 호가 정보 조회 성공")
            print(f"   최고 매수호가: {orderbook['bids'][0][0]:,}원")
            print(f"   최저 매도호가: {orderbook['asks'][0][0]:,}원")
        except Exception as e:
            print(f"❌ 호가 정보 조회 실패: {e}")
        
        print("\n🎉 테스트 완료!")
        return True
        
    except Exception as e:
        print(f"❌ 전체 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_upbit_connection()
    sys.exit(0 if success else 1)
