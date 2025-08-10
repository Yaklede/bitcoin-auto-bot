#!/usr/bin/env python3
"""
리스크 관리 시스템 테스트 스크립트
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import logging
import pandas as pd
from datetime import datetime, timedelta
from app.data import data_manager
from app.risk import risk_manager, position_sizer, PositionSide, Position

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def test_position_sizing():
    """포지션 사이징 테스트"""
    print("=== 포지션 사이징 테스트 ===")
    
    try:
        # 1. 현재 계좌 잔고 조회
        print("1. 계좌 잔고 조회...")
        try:
            balance = data_manager.collector.get_account_balance()
            equity = balance['krw']['total']
            print(f"✅ 현재 잔고: {equity:,.0f}원")
        except:
            # API 키 문제로 실패하면 가상 잔고 사용
            equity = 1000000  # 100만원
            print(f"⚠️  가상 잔고 사용: {equity:,.0f}원")
        
        # 2. 현재 가격 및 ATR 조회
        print("\n2. 시장 데이터 조회...")
        current_price_data = data_manager.collector.get_current_price()
        current_price = current_price_data['last']
        print(f"✅ 현재 BTC 가격: {current_price:,.0f}원")
        
        # ATR 계산을 위한 데이터 조회
        ohlcv_data = data_manager.collector.get_ohlcv_data(timeframe='1h', limit=50)
        if not ohlcv_data.empty:
            # 간단한 ATR 계산 (14일 평균)
            high_low = ohlcv_data['high'] - ohlcv_data['low']
            high_close = abs(ohlcv_data['high'] - ohlcv_data['close'].shift(1))
            low_close = abs(ohlcv_data['low'] - ohlcv_data['close'].shift(1))
            true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
            atr = true_range.rolling(window=14).mean().iloc[-1]
            print(f"✅ ATR: {atr:,.0f}원")
        else:
            atr = current_price * 0.02  # 2% 가정
            print(f"⚠️  ATR 추정값 사용: {atr:,.0f}원")
        
        # 3. 포지션 사이징 계산
        print("\n3. 포지션 사이징 계산...")
        
        # 롱 포지션 스탑로스 계산
        stop_loss = position_sizer.calculate_stop_loss(
            entry_price=current_price,
            atr=atr,
            side=PositionSide.LONG,
            multiplier=2.5
        )
        
        # 다양한 신뢰도로 포지션 사이징 테스트
        confidence_levels = [0.5, 0.7, 1.0]
        
        for confidence in confidence_levels:
            position_size, calc_info = position_sizer.calculate_position_size(
                equity=equity,
                entry_price=current_price,
                stop_loss=stop_loss,
                confidence=confidence
            )
            
            print(f"\n   신뢰도 {confidence:.1f}:")
            print(f"     포지션 크기: {position_size:.8f} BTC")
            print(f"     포지션 가치: {calc_info.get('position_value', 0):,.0f}원")
            print(f"     리스크 금액: {calc_info.get('adjusted_risk', 0):,.0f}원")
            print(f"     리스크 비율: {calc_info.get('risk_percentage', 0):.2f}%")
        
        return True
        
    except Exception as e:
        print(f"❌ 포지션 사이징 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_position_management():
    """포지션 관리 테스트"""
    print("\n=== 포지션 관리 테스트 ===")
    
    try:
        # 1. 포지션 개설 가능 여부 확인
        print("1. 포지션 개설 가능 여부 확인...")
        can_open, reason = risk_manager.can_open_position()
        print(f"   결과: {can_open} - {reason}")
        
        if not can_open:
            print("⚠️  포지션 개설 불가능")
            return True
        
        # 2. 가상 포지션 개설
        print("\n2. 가상 포지션 개설...")
        current_price = 160000000  # 1억 6천만원
        atr = 3000000  # 300만원
        
        stop_loss = position_sizer.calculate_stop_loss(
            entry_price=current_price,
            atr=atr,
            side=PositionSide.LONG,
            multiplier=2.5
        )
        
        success = risk_manager.open_position(
            side=PositionSide.LONG,
            entry_price=current_price,
            volume=0.001,  # 0.001 BTC
            stop_loss=stop_loss,
            metadata={'strategy': 'test', 'confidence': 0.8}
        )
        
        if success:
            print(f"✅ 포지션 개설 성공")
            print(f"   진입가: {current_price:,.0f}원")
            print(f"   수량: 0.001 BTC")
            print(f"   손절가: {stop_loss:,.0f}원")
        else:
            print("❌ 포지션 개설 실패")
            return False
        
        # 3. 포지션 업데이트 시뮬레이션
        print("\n3. 포지션 업데이트 시뮬레이션...")
        
        # 가격 변동 시나리오
        price_scenarios = [
            (162000000, "2% 상승"),
            (165000000, "3.1% 상승"),
            (158000000, "1.25% 하락"),
            (155000000, "3.1% 하락 (손절 근처)")
        ]
        
        for price, description in price_scenarios:
            print(f"\n   시나리오: {description} ({price:,.0f}원)")
            risk_manager.update_position(price, atr)
            
            if risk_manager.current_position:
                pos = risk_manager.current_position
                print(f"     미실현 손익: {pos.unrealized_pnl:,.0f}원")
                print(f"     R-multiple: {pos.r_multiple:.2f}")
                print(f"     트레일링 스탑: {pos.trail_price:,.0f}원")
                print(f"     청산 필요: {pos.should_close(price)}")
                
                if pos.should_close(price):
                    print("     → 트레일링 스탑 청산 실행됨")
                    break
            else:
                print("     → 포지션이 청산되었습니다")
                break
        
        # 4. 수동 청산 (아직 포지션이 있는 경우)
        if risk_manager.current_position and risk_manager.current_position.side != PositionSide.FLAT:
            print("\n4. 수동 청산...")
            final_pnl = risk_manager.close_position(165000000, "수동 청산")
            print(f"✅ 최종 실현손익: {final_pnl:,.0f}원")
        
        return True
        
    except Exception as e:
        print(f"❌ 포지션 관리 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_risk_limits():
    """리스크 한도 테스트"""
    print("\n=== 리스크 한도 테스트 ===")
    
    try:
        # 1. 현재 리스크 상태 확인
        print("1. 현재 리스크 상태...")
        risk_status = risk_manager.get_risk_status()
        
        print(f"   거래 중단: {risk_status['trading_halted']}")
        print(f"   일일 R: {risk_status['daily_r_multiple']:.2f}")
        print(f"   주간 R: {risk_status['weekly_r_multiple']:.2f}")
        print(f"   일일 거래: {risk_status['daily_trades']}회")
        print(f"   주간 거래: {risk_status['weekly_trades']}회")
        
        # 2. 손실 시나리오 시뮬레이션
        print("\n2. 손실 시나리오 시뮬레이션...")
        
        # 가상의 연속 손실 거래 생성
        print("   연속 손실 거래 시뮬레이션...")
        
        for i in range(3):
            # 포지션 개설
            can_open, reason = risk_manager.can_open_position()
            if not can_open:
                print(f"   거래 {i+1}: 개설 불가 - {reason}")
                break
            
            success = risk_manager.open_position(
                side=PositionSide.LONG,
                entry_price=160000000,
                volume=0.001,
                stop_loss=155000000,
                metadata={'test': f'loss_trade_{i+1}'}
            )
            
            if success:
                # 손실로 청산
                pnl = risk_manager.close_position(155000000, f"손실 거래 {i+1}")
                print(f"   거래 {i+1}: 손실 {pnl:,.0f}원, R: {risk_manager.current_position.r_multiple if risk_manager.current_position else 'N/A'}")
            
            # 현재 누적 R 확인
            current_status = risk_manager.get_risk_status()
            print(f"     누적 일일 R: {current_status['daily_r_multiple']:.2f}")
            
            # 일일 한도 도달 확인
            if current_status['daily_r_multiple'] <= -2:
                print("     → 일일 손실 한도 도달!")
                break
        
        # 3. 최종 상태 확인
        print("\n3. 최종 리스크 상태...")
        final_status = risk_manager.get_risk_status()
        print(f"   거래 중단: {final_status['trading_halted']}")
        if final_status['trading_halted']:
            print(f"   중단 사유: {final_status['halt_reason']}")
            print(f"   중단 해제: {final_status['halt_until']}")
        
        # 4. 성과 통계
        print("\n4. 성과 통계...")
        perf_stats = risk_manager.get_performance_stats()
        if perf_stats:
            print(f"   총 거래: {perf_stats['total_trades']}회")
            print(f"   승률: {perf_stats['win_rate']:.1%}")
            print(f"   총 손익: {perf_stats['total_pnl']:,.0f}원")
            print(f"   평균 R: {perf_stats['avg_r_multiple']:.2f}")
            print(f"   기댓값: {perf_stats['expectancy']:,.0f}원")
        else:
            print("   거래 기록 없음")
        
        return True
        
    except Exception as e:
        print(f"❌ 리스크 한도 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_trailing_stop():
    """트레일링 스탑 테스트"""
    print("\n=== 트레일링 스탑 테스트 ===")
    
    try:
        # 리스크 매니저 초기화 (이전 테스트 영향 제거)
        risk_manager.reset_daily_stats()
        risk_manager.resume_trading()
        
        # 1. 포지션 개설
        print("1. 테스트 포지션 개설...")
        entry_price = 160000000
        atr = 2000000
        
        stop_loss = position_sizer.calculate_stop_loss(
            entry_price=entry_price,
            atr=atr,
            side=PositionSide.LONG,
            multiplier=2.5
        )
        
        success = risk_manager.open_position(
            side=PositionSide.LONG,
            entry_price=entry_price,
            volume=0.001,
            stop_loss=stop_loss,
            metadata={'test': 'trailing_stop'}
        )
        
        if not success:
            print("❌ 포지션 개설 실패")
            return False
        
        print(f"✅ 포지션 개설: {entry_price:,.0f}원")
        print(f"   초기 스탑: {stop_loss:,.0f}원")
        
        # 2. 가격 상승 시나리오로 트레일링 테스트
        print("\n2. 트레일링 스탑 업데이트 테스트...")
        
        price_sequence = [
            162000000,  # +1.25%
            165000000,  # +3.1%
            168000000,  # +5%
            170000000,  # +6.25%
            167000000,  # -1.8% (트레일링 테스트)
            164000000,  # -3.5% (트레일링 청산 가능)
        ]
        
        for i, price in enumerate(price_sequence):
            print(f"\n   단계 {i+1}: 가격 {price:,.0f}원")
            
            # 포지션 업데이트
            risk_manager.update_position(price, atr)
            
            if risk_manager.current_position:
                pos = risk_manager.current_position
                print(f"     미실현 손익: {pos.unrealized_pnl:,.0f}원")
                print(f"     R-multiple: {pos.r_multiple:.2f}")
                print(f"     트레일링 스탑: {pos.trail_price:,.0f}원")
                print(f"     MFE: {pos.max_favorable_excursion:,.0f}원")
                print(f"     MAE: {pos.max_adverse_excursion:,.0f}원")
                
                if pos.should_close(price):
                    print("     → 트레일링 스탑 청산!")
                    break
            else:
                print("     → 포지션 청산됨")
                break
        
        # 3. 최종 결과
        print("\n3. 트레일링 스탑 테스트 결과...")
        if risk_manager.current_position and risk_manager.current_position.side == PositionSide.FLAT:
            print("✅ 트레일링 스탑이 정상적으로 작동했습니다")
        elif risk_manager.current_position:
            print("⚠️  포지션이 아직 열려있습니다")
            # 수동 청산
            risk_manager.close_position(price_sequence[-1], "테스트 종료")
        else:
            print("✅ 포지션이 청산되었습니다")
        
        return True
        
    except Exception as e:
        print(f"❌ 트레일링 스탑 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """메인 테스트 함수"""
    print("🚀 리스크 관리 시스템 종합 테스트 시작\n")
    
    success_count = 0
    total_tests = 4
    
    # 1. 포지션 사이징 테스트
    if test_position_sizing():
        success_count += 1
    
    # 2. 포지션 관리 테스트
    if test_position_management():
        success_count += 1
    
    # 3. 리스크 한도 테스트
    if test_risk_limits():
        success_count += 1
    
    # 4. 트레일링 스탑 테스트
    if test_trailing_stop():
        success_count += 1
    
    # 결과 요약
    print(f"\n{'='*50}")
    print(f"테스트 결과: {success_count}/{total_tests} 성공")
    
    if success_count == total_tests:
        print("🎉 모든 리스크 관리 테스트 통과!")
        return True
    else:
        print("⚠️  일부 테스트 실패")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
