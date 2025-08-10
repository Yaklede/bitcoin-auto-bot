#!/usr/bin/env python3
"""
완전한 Upbit API 구현 테스트 스크립트
모든 API 엔드포인트를 테스트하여 정상 작동 확인
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.upbit_api import upbit_api
from app.data import UpbitDataCollector
from app.broker import TradingBroker
import logging
import json
from datetime import datetime

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_public_apis():
    """공개 API 테스트"""
    print("\n" + "="*50)
    print("공개 API 테스트 시작")
    print("="*50)
    
    try:
        # 1. 마켓 리스트 조회
        print("\n1. 마켓 리스트 조회")
        markets = upbit_api.get_markets()
        print(f"   총 마켓 수: {len(markets)}")
        print(f"   첫 5개 마켓: {[m['market'] for m in markets[:5]]}")
        
        # 2. 현재가 조회
        print("\n2. 현재가 조회 (KRW-BTC)")
        ticker = upbit_api.get_ticker(['KRW-BTC'])
        if ticker:
            print(f"   현재가: {ticker[0]['trade_price']:,}원")
            print(f"   24시간 변동률: {ticker[0]['change_rate']*100:.2f}%")
        
        # 3. 호가 정보 조회
        print("\n3. 호가 정보 조회 (KRW-BTC)")
        orderbook = upbit_api.get_orderbook(['KRW-BTC'])
        if orderbook:
            units = orderbook[0]['orderbook_units'][:3]
            print("   매수 호가:")
            for unit in units:
                print(f"     {unit['bid_price']:,}원 - {unit['bid_size']:.8f} BTC")
            print("   매도 호가:")
            for unit in units:
                print(f"     {unit['ask_price']:,}원 - {unit['ask_size']:.8f} BTC")
        
        # 4. 캔들 데이터 조회
        print("\n4. 캔들 데이터 조회 (KRW-BTC, 1분)")
        candles = upbit_api.get_candles_minutes('KRW-BTC', 1, count=5)
        if candles:
            print("   최근 5개 캔들:")
            for candle in candles:
                print(f"     {candle['candle_date_time_kst']}: "
                      f"시가 {candle['opening_price']:,} -> 종가 {candle['trade_price']:,}")
        
        # 5. 체결 내역 조회
        print("\n5. 최근 체결 내역 조회 (KRW-BTC)")
        trades = upbit_api.get_trades_ticks('KRW-BTC', count=5)
        if trades:
            print("   최근 5개 체결:")
            for trade in trades:
                print(f"     {trade['trade_time_utc']}: "
                      f"{trade['trade_price']:,}원 x {trade['trade_volume']:.8f} BTC")
        
        print("\n✅ 공개 API 테스트 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 공개 API 테스트 실패: {e}")
        return False

def test_private_apis():
    """인증 API 테스트 (API 키가 있는 경우)"""
    print("\n" + "="*50)
    print("인증 API 테스트 시작")
    print("="*50)
    
    if not upbit_api.access_key or not upbit_api.secret_key:
        print("⚠️  API 키가 설정되지 않아 인증 API 테스트를 건너뜁니다.")
        return True
    
    try:
        # 1. 계좌 조회
        print("\n1. 계좌 조회")
        accounts = upbit_api.get_accounts()
        print(f"   계좌 수: {len(accounts)}")
        for account in accounts[:5]:  # 처음 5개만 표시
            balance = float(account['balance'])
            locked = float(account['locked'])
            if balance > 0 or locked > 0:
                print(f"   {account['currency']}: "
                      f"사용가능 {balance:.8f}, 사용중 {locked:.8f}")
        
        # 2. 주문 가능 정보 조회
        print("\n2. 주문 가능 정보 조회 (KRW-BTC)")
        order_chance = upbit_api.get_order_chance('KRW-BTC')
        if order_chance:
            bid_fee = order_chance['bid_fee']
            ask_fee = order_chance['ask_fee']
            print(f"   매수 수수료: {float(bid_fee)*100:.3f}%")
            print(f"   매도 수수료: {float(ask_fee)*100:.3f}%")
            
            market_info = order_chance['market']
            print(f"   마켓 상태: {market_info['state']}")
            print(f"   최소 주문 금액: {market_info.get('bid', {}).get('min_total', 'N/A')}")
        
        # 3. 미체결 주문 조회
        print("\n3. 미체결 주문 조회")
        open_orders = upbit_api.get_orders_open()
        print(f"   미체결 주문 수: {len(open_orders)}")
        for order in open_orders[:3]:  # 처음 3개만 표시
            print(f"   {order['uuid'][:8]}...: "
                  f"{order['side']} {order['volume']} @ {order.get('price', 'market')}")
        
        # 4. 주문 내역 조회
        print("\n4. 최근 주문 내역 조회")
        order_history = upbit_api.get_orders_closed(limit=5)
        print(f"   최근 주문 수: {len(order_history)}")
        for order in order_history:
            created_at = order['created_at'][:19].replace('T', ' ')
            print(f"   {created_at}: "
                  f"{order['side']} {order['volume']} @ {order.get('price', 'market')} "
                  f"({order['state']})")
        
        print("\n✅ 인증 API 테스트 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 인증 API 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_data_collector():
    """데이터 수집기 테스트"""
    print("\n" + "="*50)
    print("데이터 수집기 테스트 시작")
    print("="*50)
    
    try:
        collector = UpbitDataCollector()
        
        # 1. 연결 테스트
        print("\n1. 연결 테스트")
        connection_ok = collector.test_connection()
        print(f"   연결 상태: {'✅ 성공' if connection_ok else '❌ 실패'}")
        
        # 2. 계좌 잔고 조회
        print("\n2. 계좌 잔고 조회")
        try:
            balance = collector.get_account_balance()
            print(f"   KRW 잔고: {balance['krw']['total']:,.0f}원")
            print(f"   BTC 잔고: {balance['btc']['total']:.8f} BTC")
        except Exception as e:
            print(f"   ⚠️  잔고 조회 실패 (API 키 필요): {e}")
        
        # 3. 캔들 데이터 조회
        print("\n3. 캔들 데이터 조회")
        candles = collector.get_candles('KRW-BTC', '1m', 5)
        print(f"   캔들 수: {len(candles)}")
        if candles:
            latest = candles[0]
            print(f"   최신 캔들: {latest['datetime'][:19]} "
                  f"OHLC({latest['open']:,}, {latest['high']:,}, "
                  f"{latest['low']:,}, {latest['close']:,})")
        
        # 4. 현재 가격 조회
        print("\n4. 현재 가격 조회")
        price_info = collector.get_current_price()
        print(f"   현재가: {price_info['last']:,}원")
        print(f"   24시간 변동: {price_info['change']:+,}원 ({price_info['percentage']:+.2f}%)")
        
        # 5. 호가 정보 조회
        print("\n5. 호가 정보 조회")
        orderbook = collector.get_orderbook(5)
        print(f"   매수 1호가: {orderbook['bids'][0][0]:,}원")
        print(f"   매도 1호가: {orderbook['asks'][0][0]:,}원")
        
        print("\n✅ 데이터 수집기 테스트 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 데이터 수집기 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_broker():
    """브로커 테스트"""
    print("\n" + "="*50)
    print("브로커 테스트 시작")
    print("="*50)
    
    try:
        broker = TradingBroker()
        
        # 1. 계좌 정보 조회
        print("\n1. 계좌 정보 조회")
        account_info = broker.get_account_info()
        print(f"   모드: {account_info.get('mode', 'unknown')}")
        print(f"   활성 주문 수: {account_info.get('orders', 0)}")
        
        # 2. 거래 수수료 조회
        print("\n2. 거래 수수료 조회")
        fees = broker.get_trading_fees()
        print(f"   Maker 수수료: {fees['maker']*100:.3f}%")
        print(f"   Taker 수수료: {fees['taker']*100:.3f}%")
        
        # 3. 미체결 주문 조회
        print("\n3. 미체결 주문 조회")
        open_orders = broker.get_open_orders()
        print(f"   미체결 주문 수: {len(open_orders)}")
        
        # 4. 주문 내역 조회
        print("\n4. 주문 내역 조회")
        history = broker.get_order_history(5)
        print(f"   최근 주문 수: {len(history)}")
        
        # 5. 거래 통계
        print("\n5. 거래 통계")
        stats = broker.get_statistics()
        print(f"   총 주문: {stats['total_orders']}")
        print(f"   성공률: {stats['success_rate']:.1f}%")
        
        print("\n✅ 브로커 테스트 완료")
        return True
        
    except Exception as e:
        print(f"\n❌ 브로커 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """메인 테스트 함수"""
    print("Upbit API 완전 구현 테스트 시작")
    print(f"테스트 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # 1. 공개 API 테스트
    results.append(("공개 API", test_public_apis()))
    
    # 2. 인증 API 테스트
    results.append(("인증 API", test_private_apis()))
    
    # 3. 데이터 수집기 테스트
    results.append(("데이터 수집기", test_data_collector()))
    
    # 4. 브로커 테스트
    results.append(("브로커", test_broker()))
    
    # 결과 요약
    print("\n" + "="*50)
    print("테스트 결과 요약")
    print("="*50)
    
    passed = 0
    total = len(results)
    
    for test_name, result in results:
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{test_name:15}: {status}")
        if result:
            passed += 1
    
    print(f"\n총 {total}개 테스트 중 {passed}개 통과 ({passed/total*100:.1f}%)")
    
    if passed == total:
        print("\n🎉 모든 테스트가 성공적으로 완료되었습니다!")
        print("Upbit API 구현이 정상적으로 작동합니다.")
    else:
        print(f"\n⚠️  {total-passed}개 테스트가 실패했습니다.")
        print("실패한 테스트를 확인하고 문제를 해결해주세요.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
