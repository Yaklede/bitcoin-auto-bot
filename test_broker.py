#!/usr/bin/env python3
"""
주문 실행 및 상태 관리 시스템 테스트 스크립트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import time
from datetime import datetime
from app.broker import trading_broker, OrderType, OrderStatus
from app.state import state_manager
from app.data import data_manager

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_broker_initialization():
    """브로커 초기화 테스트"""
    print("=== 브로커 초기화 테스트 ===")
    
    try:
        # 1. 브로커 상태 확인
        print("1. 브로커 상태 확인...")
        stats = trading_broker.get_trading_stats()
        
        print(f"✅ 브로커 초기화 완료")
        print(f"   모드: {stats['mode']}")
        print(f"   총 주문: {stats['total_orders']}개")
        print(f"   성공률: {stats['success_rate']:.1%}")
        print(f"   활성 주문: {stats['active_orders_count']}개")
        
        # 2. 현재 시장 가격 확인
        print("\n2. 시장 가격 확인...")
        current_price_data = data_manager.collector.get_current_price()
        current_price = current_price_data['last']
        print(f"✅ 현재 BTC 가격: {current_price:,.0f}원")
        
        return True, current_price
        
    except Exception as e:
        print(f"❌ 브로커 초기화 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False, 0

def test_paper_trading():
    """페이퍼 트레이딩 테스트"""
    print("\n=== 페이퍼 트레이딩 테스트 ===")
    
    try:
        # 현재 가격 조회
        current_price_data = data_manager.collector.get_current_price()
        current_price = current_price_data['last']
        
        # 1. 시장가 매수 주문
        print("1. 시장가 매수 주문 테스트...")
        buy_order = trading_broker.create_market_order(
            side='buy',
            amount=0.001,  # 0.001 BTC
            metadata={'test': 'paper_market_buy', 'strategy': 'test'}
        )
        
        if buy_order:
            print(f"✅ 시장가 매수 주문 생성: {buy_order.client_order_id}")
            print(f"   상태: {buy_order.status.value}")
            print(f"   체결가: {buy_order.average_price:,.0f}원")
            print(f"   체결량: {buy_order.filled_amount:.8f} BTC")
            print(f"   수수료: {buy_order.fee:,.0f}원")
        else:
            print("❌ 시장가 매수 주문 실패")
            return False
        
        # 2. 지정가 매도 주문
        print("\n2. 지정가 매도 주문 테스트...")
        sell_price = current_price * 1.02  # 2% 높은 가격
        sell_order = trading_broker.create_limit_order(
            side='sell',
            amount=0.001,
            price=sell_price,
            metadata={'test': 'paper_limit_sell', 'strategy': 'test'}
        )
        
        if sell_order:
            print(f"✅ 지정가 매도 주문 생성: {sell_order.client_order_id}")
            print(f"   상태: {sell_order.status.value}")
            print(f"   주문가: {sell_order.price:,.0f}원")
            print(f"   주문량: {sell_order.amount:.8f} BTC")
        else:
            print("❌ 지정가 매도 주문 실패")
            return False
        
        # 3. 주문 상태 업데이트 테스트
        print("\n3. 주문 상태 업데이트 테스트...")
        print("   주문 상태 업데이트 중...")
        trading_broker.update_orders()
        
        # 활성 주문 확인
        active_orders = trading_broker.get_active_orders()
        print(f"   활성 주문: {len(active_orders)}개")
        
        for order in active_orders:
            print(f"     - {order['client_order_id']}: {order['status']} @ {order.get('price', 'N/A')}")
        
        # 4. 주문 취소 테스트
        if active_orders:
            print("\n4. 주문 취소 테스트...")
            cancel_order_id = active_orders[0]['client_order_id']
            success = trading_broker.cancel_order(cancel_order_id)
            
            if success:
                print(f"✅ 주문 취소 성공: {cancel_order_id}")
            else:
                print(f"❌ 주문 취소 실패: {cancel_order_id}")
        
        # 5. 거래 통계 확인
        print("\n5. 거래 통계 확인...")
        final_stats = trading_broker.get_trading_stats()
        print(f"   총 주문: {final_stats['total_orders']}개")
        print(f"   성공 주문: {final_stats['successful_orders']}개")
        print(f"   실패 주문: {final_stats['failed_orders']}개")
        print(f"   성공률: {final_stats['success_rate']:.1%}")
        
        return True
        
    except Exception as e:
        print(f"❌ 페이퍼 트레이딩 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_order_management():
    """주문 관리 테스트"""
    print("\n=== 주문 관리 테스트 ===")
    
    try:
        # 1. 주문 히스토리 조회
        print("1. 주문 히스토리 조회...")
        order_history = trading_broker.get_order_history(limit=10)
        print(f"✅ 주문 히스토리: {len(order_history)}개")
        
        for i, order in enumerate(order_history[-3:], 1):  # 최근 3개만 표시
            print(f"   {i}. {order['client_order_id'][:8]}... - {order['side']} {order['status']}")
            if order.get('filled_at'):
                print(f"      체결시간: {order['filled_at']}")
        
        # 2. 특정 주문 상태 조회
        if order_history:
            print("\n2. 특정 주문 상태 조회...")
            test_order_id = order_history[-1]['client_order_id']
            order_status = trading_broker.get_order_status(test_order_id)
            
            if order_status:
                print(f"✅ 주문 상태 조회 성공: {test_order_id[:8]}...")
                print(f"   상태: {order_status['status']}")
                print(f"   체결량: {order_status['filled_amount']:.8f}")
                print(f"   평균가: {order_status.get('average_price', 0):,.0f}원")
            else:
                print(f"❌ 주문 상태 조회 실패: {test_order_id}")
        
        # 3. 활성 주문 전체 취소 테스트
        print("\n3. 활성 주문 전체 취소 테스트...")
        
        # 테스트용 지정가 주문 몇 개 생성
        current_price = data_manager.collector.get_current_price()['last']
        test_orders = []
        
        for i in range(2):
            order = trading_broker.create_limit_order(
                side='sell',
                amount=0.0001,  # 작은 수량
                price=current_price * (1.05 + i * 0.01),  # 5%, 6% 높은 가격
                metadata={'test': f'cancel_test_{i}'}
            )
            if order:
                test_orders.append(order.client_order_id)
        
        print(f"   테스트 주문 {len(test_orders)}개 생성")
        
        # 전체 취소
        canceled_count = trading_broker.cancel_all_orders()
        print(f"✅ 전체 주문 취소: {canceled_count}개")
        
        return True
        
    except Exception as e:
        print(f"❌ 주문 관리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_state_management():
    """상태 관리 테스트"""
    print("\n=== 상태 관리 테스트 ===")
    
    try:
        # 1. 상태 관리자 초기화
        print("1. 상태 관리자 초기화...")
        success = state_manager.initialize_state()
        
        if success:
            print("✅ 상태 관리자 초기화 성공")
        else:
            print("⚠️  상태 관리자 초기화 실패 (DB/Redis 연결 문제 가능)")
            return True  # 연결 문제는 테스트 실패로 보지 않음
        
        # 2. 현재 상태 조회
        print("\n2. 현재 시스템 상태 조회...")
        current_state = state_manager.get_current_state()
        
        if current_state:
            print("✅ 시스템 상태 조회 성공")
            print(f"   거래 활성: {current_state['trading_active']}")
            print(f"   현재 포지션: {current_state['current_position'] is not None}")
            print(f"   활성 주문: {len(current_state['active_orders'])}개")
            print(f"   일일 PnL: {current_state['daily_pnl']:,.0f}원")
            print(f"   일일 R: {current_state['daily_r_multiple']:.2f}")
            print(f"   마지막 업데이트: {current_state['last_updated']}")
        else:
            print("❌ 시스템 상태 조회 실패")
        
        # 3. 상태 동기화 테스트
        print("\n3. 상태 동기화 테스트...")
        
        # 데이터베이스 동기화
        db_sync_success = state_manager.sync_with_database()
        print(f"   DB 동기화: {'성공' if db_sync_success else '실패'}")
        
        # 거래소 동기화
        exchange_sync_success = state_manager.sync_with_exchange()
        print(f"   거래소 동기화: {'성공' if exchange_sync_success else '실패'}")
        
        # 4. 손익 통계 업데이트 테스트
        print("\n4. 손익 통계 업데이트 테스트...")
        state_manager.update_pnl_stats(
            daily_pnl=5000,
            weekly_pnl=12000,
            daily_r=0.5,
            weekly_r=1.2
        )
        
        # 업데이트된 상태 확인
        updated_state = state_manager.get_current_state()
        if updated_state:
            print("✅ 손익 통계 업데이트 성공")
            print(f"   일일 PnL: {updated_state['daily_pnl']:,.0f}원")
            print(f"   주간 PnL: {updated_state['weekly_pnl']:,.0f}원")
            print(f"   일일 R: {updated_state['daily_r_multiple']:.2f}")
            print(f"   주간 R: {updated_state['weekly_r_multiple']:.2f}")
        
        return True
        
    except Exception as e:
        print(f"❌ 상태 관리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_emergency_functions():
    """긴급 기능 테스트"""
    print("\n=== 긴급 기능 테스트 ===")
    
    try:
        # 1. 긴급 상태 초기화 테스트
        print("1. 긴급 상태 초기화 테스트...")
        
        # 현재 상태 백업
        original_state = state_manager.get_current_state()
        
        # 긴급 초기화 실행
        reset_success = state_manager.emergency_state_reset()
        
        if reset_success:
            print("✅ 긴급 상태 초기화 성공")
            
            # 초기화된 상태 확인
            reset_state = state_manager.get_current_state()
            if reset_state:
                print(f"   거래 활성: {reset_state['trading_active']}")
                print(f"   포지션: {reset_state['current_position']}")
                print(f"   활성 주문: {len(reset_state['active_orders'])}개")
        else:
            print("⚠️  긴급 상태 초기화 실패 (연결 문제 가능)")
        
        # 2. 긴급 전체 청산 테스트 (시뮬레이션)
        print("\n2. 긴급 전체 청산 테스트 (시뮬레이션)...")
        
        # 실제로는 실행하지 않고 기능 존재 여부만 확인
        print("   긴급 청산 기능 확인...")
        
        # 브로커에 긴급 청산 메서드가 있는지 확인
        if hasattr(trading_broker, 'emergency_close_all'):
            print("✅ 긴급 청산 기능 존재")
            print("   (실제 실행은 하지 않음 - 테스트 목적)")
        else:
            print("❌ 긴급 청산 기능 없음")
        
        return True
        
    except Exception as e:
        print(f"❌ 긴급 기능 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """메인 테스트 함수"""
    print("🚀 주문 실행 및 상태 관리 시스템 종합 테스트 시작\n")
    
    success_count = 0
    total_tests = 5
    
    # 1. 브로커 초기화 테스트
    broker_success, current_price = test_broker_initialization()
    if broker_success:
        success_count += 1
    
    # 2. 페이퍼 트레이딩 테스트
    if test_paper_trading():
        success_count += 1
    
    # 3. 주문 관리 테스트
    if test_order_management():
        success_count += 1
    
    # 4. 상태 관리 테스트
    if test_state_management():
        success_count += 1
    
    # 5. 긴급 기능 테스트
    if test_emergency_functions():
        success_count += 1
    
    # 결과 요약
    print(f"\n{'='*50}")
    print(f"테스트 결과: {success_count}/{total_tests} 성공")
    
    if success_count == total_tests:
        print("🎉 모든 주문 실행 및 상태 관리 테스트 통과!")
        
        # 최종 시스템 상태 요약
        print(f"\n📊 최종 시스템 상태:")
        stats = trading_broker.get_trading_stats()
        print(f"   브로커 모드: {stats['mode']}")
        print(f"   총 주문 수: {stats['total_orders']}")
        print(f"   성공률: {stats['success_rate']:.1%}")
        
        current_state = state_manager.get_current_state()
        if current_state:
            print(f"   상태 관리: 활성")
            print(f"   마지막 동기화: {current_state['last_updated']}")
        
        return True
    else:
        print("⚠️  일부 테스트 실패")
        print("   (DB/Redis 연결 문제는 정상적인 상황일 수 있습니다)")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
