"""
리스크 관리 및 포지션 사이징 모듈
R 기반 포지션 사이징, ATR 기반 스탑로스/트레일링, 일일/주간 손실 제한 구현
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
import logging

from .config import config

logger = logging.getLogger(__name__)

class PositionSide(Enum):
    """포지션 방향"""
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"

class RiskLevel(Enum):
    """리스크 레벨"""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class Position:
    """포지션 정보 클래스"""
    
    def __init__(self, side: PositionSide, entry_price: float, volume: float,
                 stop_loss: float, timestamp: datetime, metadata: Optional[Dict] = None):
        self.side = side
        self.entry_price = entry_price
        self.volume = volume
        self.stop_loss = stop_loss
        self.trail_price = stop_loss  # 초기 트레일링 가격
        self.timestamp = timestamp
        self.metadata = metadata or {}
        
        # 손익 추적
        self.unrealized_pnl = 0.0
        self.realized_pnl = 0.0
        self.max_favorable_excursion = 0.0  # MFE
        self.max_adverse_excursion = 0.0    # MAE
        
        # R-multiple 추적
        self.initial_risk = abs(entry_price - stop_loss) * volume
        self.r_multiple = 0.0
    
    def update_unrealized_pnl(self, current_price: float):
        """미실현 손익 업데이트"""
        if self.side == PositionSide.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.volume
        elif self.side == PositionSide.SHORT:
            self.unrealized_pnl = (self.entry_price - current_price) * self.volume
        
        # MFE/MAE 업데이트
        if self.unrealized_pnl > self.max_favorable_excursion:
            self.max_favorable_excursion = self.unrealized_pnl
        if self.unrealized_pnl < self.max_adverse_excursion:
            self.max_adverse_excursion = self.unrealized_pnl
        
        # R-multiple 계산
        if self.initial_risk > 0:
            self.r_multiple = self.unrealized_pnl / self.initial_risk
    
    def update_trailing_stop(self, current_price: float, atr: float, multiplier: float = 3.0):
        """트레일링 스탑 업데이트"""
        if self.side == PositionSide.LONG:
            new_stop = current_price - (atr * multiplier)
            if new_stop > self.trail_price:
                self.trail_price = new_stop
                logger.info(f"롱 포지션 트레일링 스탑 업데이트: {self.trail_price:,.0f}원")
        elif self.side == PositionSide.SHORT:
            new_stop = current_price + (atr * multiplier)
            if new_stop < self.trail_price:
                self.trail_price = new_stop
                logger.info(f"숏 포지션 트레일링 스탑 업데이트: {self.trail_price:,.0f}원")
    
    def should_close(self, current_price: float) -> bool:
        """포지션 청산 여부 판단"""
        if self.side == PositionSide.LONG:
            return current_price <= self.trail_price
        elif self.side == PositionSide.SHORT:
            return current_price >= self.trail_price
        return False
    
    def close_position(self, exit_price: float, timestamp: datetime) -> float:
        """포지션 청산 및 실현손익 계산"""
        if self.side == PositionSide.LONG:
            self.realized_pnl = (exit_price - self.entry_price) * self.volume
        elif self.side == PositionSide.SHORT:
            self.realized_pnl = (self.entry_price - exit_price) * self.volume
        
        # 최종 R-multiple 계산
        if self.initial_risk > 0:
            self.r_multiple = self.realized_pnl / self.initial_risk
        
        self.side = PositionSide.FLAT
        logger.info(f"포지션 청산: 실현손익 {self.realized_pnl:,.0f}원 (R: {self.r_multiple:.2f})")
        
        return self.realized_pnl
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'side': self.side.value,
            'entry_price': self.entry_price,
            'volume': self.volume,
            'stop_loss': self.stop_loss,
            'trail_price': self.trail_price,
            'timestamp': self.timestamp.isoformat(),
            'unrealized_pnl': self.unrealized_pnl,
            'realized_pnl': self.realized_pnl,
            'r_multiple': self.r_multiple,
            'mfe': self.max_favorable_excursion,
            'mae': self.max_adverse_excursion,
            'metadata': self.metadata
        }

class PositionSizer:
    """포지션 사이징 클래스"""
    
    def __init__(self):
        self.risk_config = config.risk
        self.r_per_trade_bps = self.risk_config.get('r_per_trade_bps', 50)  # 0.5%
        self.max_position = self.risk_config.get('max_position', 1)
        
        logger.info(f"포지션 사이저 초기화: R={self.r_per_trade_bps}bps, 최대포지션={self.max_position}")
    
    def calculate_position_size(self, equity: float, entry_price: float, 
                              stop_loss: float, confidence: float = 1.0) -> Tuple[float, Dict[str, Any]]:
        """
        R 기반 포지션 사이징 계산
        
        Args:
            equity: 현재 계좌 잔고
            entry_price: 진입 가격
            stop_loss: 손절 가격
            confidence: 시그널 신뢰도 (0.0 ~ 1.0)
            
        Returns:
            (포지션 크기, 계산 정보)
        """
        try:
            # 기본 리스크 계산
            risk_per_trade = equity * (self.r_per_trade_bps / 10000.0)
            
            # 신뢰도에 따른 리스크 조정
            adjusted_risk = risk_per_trade * confidence
            
            # 스탑 거리 계산
            stop_distance = abs(entry_price - stop_loss)
            
            if stop_distance <= 0:
                logger.warning("스탑 거리가 0 이하입니다")
                return 0.0, {}
            
            # 포지션 크기 계산
            position_size = adjusted_risk / stop_distance
            
            # 최대 포지션 제한 적용
            max_position_value = equity * 0.95  # 95% 제한
            max_position_size = max_position_value / entry_price
            
            if position_size > max_position_size:
                position_size = max_position_size
                logger.warning(f"포지션 크기가 최대 한도로 제한됨: {position_size:.8f}")
            
            # 최소 거래 단위 적용 (Upbit BTC 최소: 0.00008)
            min_order_size = 0.00008
            if position_size < min_order_size:
                logger.warning(f"포지션 크기가 최소 거래 단위보다 작음: {position_size:.8f}")
                return 0.0, {}
            
            # 소수점 정리 (Upbit BTC는 8자리)
            position_size = round(position_size, 8)
            
            calculation_info = {
                'equity': equity,
                'risk_per_trade': risk_per_trade,
                'adjusted_risk': adjusted_risk,
                'stop_distance': stop_distance,
                'confidence': confidence,
                'position_size': position_size,
                'position_value': position_size * entry_price,
                'risk_percentage': (adjusted_risk / equity) * 100
            }
            
            logger.info(f"포지션 사이징: {position_size:.8f} BTC "
                       f"(리스크: {adjusted_risk:,.0f}원, {calculation_info['risk_percentage']:.2f}%)")
            
            return position_size, calculation_info
            
        except Exception as e:
            logger.error(f"포지션 사이징 계산 실패: {e}")
            return 0.0, {}
    
    def calculate_stop_loss(self, entry_price: float, atr: float, 
                           side: PositionSide, multiplier: float = 2.5) -> float:
        """
        ATR 기반 스탑로스 계산
        
        Args:
            entry_price: 진입 가격
            atr: ATR 값
            side: 포지션 방향
            multiplier: ATR 배수
            
        Returns:
            스탑로스 가격
        """
        try:
            if side == PositionSide.LONG:
                stop_loss = entry_price - (atr * multiplier)
            elif side == PositionSide.SHORT:
                stop_loss = entry_price + (atr * multiplier)
            else:
                return entry_price
            
            # 가격 단위 정리 (Upbit KRW는 1원 단위)
            stop_loss = round(stop_loss)
            
            logger.info(f"ATR 스탑로스 계산: {stop_loss:,.0f}원 "
                       f"(ATR: {atr:,.0f}, 배수: {multiplier})")
            
            return stop_loss
            
        except Exception as e:
            logger.error(f"스탑로스 계산 실패: {e}")
            return entry_price

class RiskManager:
    """리스크 관리자"""
    
    def __init__(self, broker=None):
        self.risk_config = config.risk
        self.daily_stop_r = self.risk_config.get('daily_stop_R', -2)
        self.weekly_stop_r = self.risk_config.get('weekly_stop_R', -5)
        
        # 브로커 인스턴스 (잔고 조회용)
        self.broker = broker
        
        # 손실 추적
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.daily_r_multiple = 0.0
        self.weekly_r_multiple = 0.0
        
        # 거래 중단 플래그
        self.trading_halted = False
        self.halt_reason = ""
        self.halt_until = None
        
        # 현재 포지션
        self.current_position: Optional[Position] = None
        
        # 거래 통계
        self.trade_history = []
        self.daily_trades = 0
        self.weekly_trades = 0
        
        # 포지션 사이저 인스턴스
        self.position_sizer = PositionSizer()
        
        logger.info(f"리스크 매니저 초기화: 일일한도 {self.daily_stop_r}R, 주간한도 {self.weekly_stop_r}R")
    
    def can_open_position(self) -> Tuple[bool, str]:
        """새 포지션 개설 가능 여부 확인"""
        
        # 거래 중단 상태 확인
        if self.trading_halted:
            if self.halt_until and datetime.now() < self.halt_until:
                return False, f"거래 중단 중: {self.halt_reason}"
            else:
                # 중단 시간이 지나면 해제
                self.resume_trading()
        
        # 기존 포지션 확인
        if self.current_position and self.current_position.side != PositionSide.FLAT:
            return False, "기존 포지션이 존재합니다"
        
        # 일일 손실 한도 확인
        if self.daily_r_multiple <= self.daily_stop_r:
            self.halt_trading("일일 손실 한도 도달", hours=24)
            return False, f"일일 손실 한도 도달: {self.daily_r_multiple:.2f}R"
        
        # 주간 손실 한도 확인
        if self.weekly_r_multiple <= self.weekly_stop_r:
            self.halt_trading("주간 손실 한도 도달", hours=168)  # 7일
            return False, f"주간 손실 한도 도달: {self.weekly_r_multiple:.2f}R"
        
        return True, "포지션 개설 가능"
    
    def should_close_position(self, position: Position, current_price: float) -> bool:
        """포지션 청산 여부 판단"""
        try:
            if not position or position.side == PositionSide.FLAT:
                return False
            
            # 트레일링 스탑 확인
            if position.trail_price:
                if position.side == PositionSide.LONG and current_price <= position.trail_price:
                    logger.info(f"롱 포지션 트레일링 스탑 도달: {current_price:,.0f} <= {position.trail_price:,.0f}")
                    return True
                elif position.side == PositionSide.SHORT and current_price >= position.trail_price:
                    logger.info(f"숏 포지션 트레일링 스탑 도달: {current_price:,.0f} >= {position.trail_price:,.0f}")
                    return True
            
            # 고정 스탑로스 확인
            if position.stop_loss:
                if position.side == PositionSide.LONG and current_price <= position.stop_loss:
                    logger.info(f"롱 포지션 스탑로스 도달: {current_price:,.0f} <= {position.stop_loss:,.0f}")
                    return True
                elif position.side == PositionSide.SHORT and current_price >= position.stop_loss:
                    logger.info(f"숏 포지션 스탑로스 도달: {current_price:,.0f} >= {position.stop_loss:,.0f}")
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"포지션 청산 판단 실패: {e}")
            return False
    
    def update_trailing_stop(self, position: Position, current_price: float, atr: float = None, multiplier: float = 3.0) -> Position:
        """트레일링 스탑 업데이트"""
        try:
            if not position or position.side == PositionSide.FLAT:
                return position
            
            # ATR이 없으면 기본값 사용
            if atr is None:
                atr = abs(current_price - position.entry_price) * 0.02  # 2% 기본값
            
            # 포지션의 트레일링 스탑 업데이트
            position.update_trailing_stop(current_price, atr, multiplier)
            
            return position
            
        except Exception as e:
            logger.error(f"트레일링 스탑 업데이트 실패: {e}")
            return position
    
    def calculate_position_size(self, signal: Dict[str, Any], current_price: float) -> float:
        """
        시그널과 현재 가격을 기반으로 포지션 사이즈 계산
        
        Args:
            signal: 전략에서 생성된 시그널 (confidence, atr 등 포함)
            current_price: 현재 시장 가격
            
        Returns:
            계산된 포지션 사이즈 (BTC 단위)
        """
        try:
            # 현재 계좌 잔고 가져오기
            if self.broker:
                try:
                    account_info = self.broker.get_account_info()
                    if self.broker.mode == "paper":
                        # 페이퍼 트레이딩에서는 기본 잔고 사용
                        balance_info = account_info.get('balance', {})
                        if isinstance(balance_info.get('KRW'), dict):
                            equity = balance_info['KRW'].get('balance', 1000000.0)
                        else:
                            equity = balance_info.get('KRW', 1000000.0)
                    else:
                        # 실거래에서는 실제 KRW 잔고 사용
                        balance_info = account_info.get('balance', {})
                        krw_info = balance_info.get('KRW', {})
                        
                        if isinstance(krw_info, dict):
                            # 새로운 구조: {'balance': 0.47, 'locked': 0.0, 'total': 0.47}
                            equity = krw_info.get('balance', 0.0)
                        else:
                            # 기존 구조: 숫자 직접
                            equity = krw_info if isinstance(krw_info, (int, float)) else 0.0
                        
                        if equity <= 0:
                            logger.warning("KRW 잔고가 0원 이하입니다")
                            return 0.0
                            
                except Exception as e:
                    logger.error(f"잔고 조회 실패: {e}, 기본값 사용")
                    equity = 1000000.0  # 기본값으로 폴백
            else:
                logger.warning("브로커 인스턴스가 없습니다. 기본값 사용")
                equity = 1000000.0  # 기본값
            
            # 시그널에서 필요한 정보 추출
            confidence = signal.get('confidence', 1.0)
            atr = signal.get('atr', current_price * 0.02)  # ATR이 없으면 2% 기본값
            
            # PositionSizer를 통해 포지션 사이즈 계산
            entry_price = current_price
            stop_loss = self.position_sizer.calculate_stop_loss(
                entry_price, atr, PositionSide.LONG
            )
            
            position_size, calc_info = self.position_sizer.calculate_position_size(
                equity, entry_price, stop_loss, confidence
            )
            
            logger.info(f"포지션 사이즈 계산 완료: {position_size:.8f} BTC "
                       f"(잔고: {equity:,.0f}원, 신뢰도: {confidence:.2f}, ATR: {atr:,.0f})")
            
            return position_size
            
        except Exception as e:
            logger.error(f"포지션 사이즈 계산 실패: {e}")
            return 0.0

    def create_position_from_order(self, order) -> Optional[Position]:
        """주문으로부터 포지션 생성"""
        try:
            if not order or not hasattr(order, 'side') or not hasattr(order, 'filled_amount'):
                logger.warning("유효하지 않은 주문으로 포지션 생성 불가")
                return None
            
            # 주문 타입에 따른 포지션 사이드 결정
            if order.side.lower() == 'buy':
                position_side = PositionSide.LONG
            elif order.side.lower() == 'sell':
                position_side = PositionSide.SHORT
            else:
                logger.warning(f"알 수 없는 주문 사이드: {order.side}")
                return None
            
            # 포지션 생성
            position = Position(
                side=position_side,
                entry_price=order.average_price or order.price,
                volume=order.filled_amount,
                stop_loss=getattr(order, 'stop_loss', None),
                timestamp=datetime.now(),
                metadata=getattr(order, 'metadata', {})
            )
            
            # 현재 포지션으로 설정
            self.current_position = position
            
            logger.info(f"주문으로부터 포지션 생성: {position_side.value} {position.volume:.8f} @ {position.entry_price:,.0f}")
            
            return position
            
        except Exception as e:
            logger.error(f"주문으로부터 포지션 생성 실패: {e}")
            return None

    def open_position(self, side: PositionSide, entry_price: float, volume: float,
                     stop_loss: float, metadata: Optional[Dict] = None) -> bool:
        """포지션 개설"""
        try:
            can_open, reason = self.can_open_position()
            if not can_open:
                logger.warning(f"포지션 개설 불가: {reason}")
                return False
            
            self.current_position = Position(
                side=side,
                entry_price=entry_price,
                volume=volume,
                stop_loss=stop_loss,
                timestamp=datetime.now(),
                metadata=metadata
            )
            
            self.daily_trades += 1
            self.weekly_trades += 1
            
            logger.info(f"포지션 개설: {side.value} {volume:.8f} BTC @ {entry_price:,.0f}원")
            return True
            
        except Exception as e:
            logger.error(f"포지션 개설 실패: {e}")
            return False
    
    def update_position(self, current_price: float, atr: float):
        """포지션 업데이트 (손익, 트레일링 스탑)"""
        if not self.current_position or self.current_position.side == PositionSide.FLAT:
            return
        
        try:
            # 미실현 손익 업데이트
            self.current_position.update_unrealized_pnl(current_price)
            
            # 트레일링 스탑 업데이트
            trail_multiplier = config.strategy.get('params', {}).get('trail_atr_mult', 3.0)
            self.current_position.update_trailing_stop(current_price, atr, trail_multiplier)
            
            # 청산 조건 확인
            if self.current_position.should_close(current_price):
                self.close_position(current_price, "트레일링 스탑")
            
        except Exception as e:
            logger.error(f"포지션 업데이트 실패: {e}")
    
    def close_position(self, exit_price: float, reason: str = "수동 청산") -> Optional[float]:
        """포지션 청산"""
        if not self.current_position or self.current_position.side == PositionSide.FLAT:
            logger.warning("청산할 포지션이 없습니다")
            return None
        
        try:
            # 포지션 청산
            realized_pnl = self.current_position.close_position(exit_price, datetime.now())
            
            # 거래 기록 저장
            trade_record = {
                'timestamp': datetime.now(),
                'side': self.current_position.side.value,
                'entry_price': self.current_position.entry_price,
                'exit_price': exit_price,
                'volume': self.current_position.volume,
                'realized_pnl': realized_pnl,
                'r_multiple': self.current_position.r_multiple,
                'mfe': self.current_position.max_favorable_excursion,
                'mae': self.current_position.max_adverse_excursion,
                'reason': reason
            }
            self.trade_history.append(trade_record)
            
            # 손익 누적
            self.daily_pnl += realized_pnl
            self.weekly_pnl += realized_pnl
            self.daily_r_multiple += self.current_position.r_multiple
            self.weekly_r_multiple += self.current_position.r_multiple
            
            logger.info(f"포지션 청산 완료: {reason}, PnL: {realized_pnl:,.0f}원, "
                       f"R: {self.current_position.r_multiple:.2f}")
            
            # 포지션 초기화
            self.current_position = None
            
            return realized_pnl
            
        except Exception as e:
            logger.error(f"포지션 청산 실패: {e}")
            return None
    
    def halt_trading(self, reason: str, hours: int = 24):
        """거래 중단"""
        self.trading_halted = True
        self.halt_reason = reason
        self.halt_until = datetime.now() + timedelta(hours=hours)
        
        logger.warning(f"거래 중단: {reason} ({hours}시간)")
        
        # 기존 포지션이 있으면 즉시 청산
        if self.current_position and self.current_position.side != PositionSide.FLAT:
            logger.warning("긴급 포지션 청산 실행")
            # 실제로는 현재 시장가로 청산해야 하지만, 여기서는 진입가로 가정
            self.close_position(self.current_position.entry_price, f"긴급청산: {reason}")
    
    def resume_trading(self):
        """거래 재개"""
        self.trading_halted = False
        self.halt_reason = ""
        self.halt_until = None
        logger.info("거래 재개")
    
    def reset_daily_stats(self):
        """일일 통계 초기화"""
        self.daily_pnl = 0.0
        self.daily_r_multiple = 0.0
        self.daily_trades = 0
        logger.info("일일 통계 초기화")
    
    def reset_weekly_stats(self):
        """주간 통계 초기화"""
        self.weekly_pnl = 0.0
        self.weekly_r_multiple = 0.0
        self.weekly_trades = 0
        logger.info("주간 통계 초기화")
    
    def get_risk_status(self) -> Dict[str, Any]:
        """리스크 상태 정보 반환"""
        return {
            'trading_halted': self.trading_halted,
            'halt_reason': self.halt_reason,
            'halt_until': self.halt_until.isoformat() if self.halt_until else None,
            'daily_pnl': self.daily_pnl,
            'weekly_pnl': self.weekly_pnl,
            'daily_r_multiple': self.daily_r_multiple,
            'weekly_r_multiple': self.weekly_r_multiple,
            'daily_trades': self.daily_trades,
            'weekly_trades': self.weekly_trades,
            'current_position': self.current_position.to_dict() if self.current_position else None,
            'total_trades': len(self.trade_history)
        }
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """성과 통계 반환"""
        if not self.trade_history:
            return {}
        
        try:
            trades_df = pd.DataFrame(self.trade_history)
            
            # 기본 통계
            total_trades = len(trades_df)
            winning_trades = len(trades_df[trades_df['realized_pnl'] > 0])
            losing_trades = len(trades_df[trades_df['realized_pnl'] < 0])
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            # 손익 통계
            total_pnl = trades_df['realized_pnl'].sum()
            avg_win = trades_df[trades_df['realized_pnl'] > 0]['realized_pnl'].mean() if winning_trades > 0 else 0
            avg_loss = trades_df[trades_df['realized_pnl'] < 0]['realized_pnl'].mean() if losing_trades > 0 else 0
            profit_factor = abs(avg_win * winning_trades / (avg_loss * losing_trades)) if avg_loss != 0 else float('inf')
            
            # R-multiple 통계
            avg_r = trades_df['r_multiple'].mean()
            expectancy = win_rate * avg_win + (1 - win_rate) * avg_loss
            
            return {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': profit_factor,
                'avg_r_multiple': avg_r,
                'expectancy': expectancy
            }
            
        except Exception as e:
            logger.error(f"성과 통계 계산 실패: {e}")
            return {}

# 전역 리스크 관리자 인스턴스 (broker는 나중에 설정)
risk_manager = RiskManager(broker=None)
position_sizer = PositionSizer()
