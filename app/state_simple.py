"""
간소화된 상태 관리 모듈
"""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

@dataclass
class SystemState:
    """시스템 전체 상태"""
    last_updated: datetime
    trading_active: bool
    current_position: Optional[Dict[str, Any]]
    active_orders: List[Dict[str, Any]]
    daily_pnl: float
    weekly_pnl: float
    daily_r_multiple: float
    weekly_r_multiple: float
    total_trades: int
    last_price: float
    last_signal: Optional[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        result = asdict(self)
        result['last_updated'] = self.last_updated.isoformat()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SystemState':
        """딕셔너리에서 생성"""
        data['last_updated'] = datetime.fromisoformat(data['last_updated'])
        return cls(**data)

class StateManager:
    """간소화된 상태 관리자"""
    
    def __init__(self):
        self.current_state: Optional[SystemState] = None
        logger.info("간소화된 상태 관리자 초기화 완료")
    
    def initialize_state(self) -> bool:
        """시스템 상태 초기화"""
        try:
            self.current_state = SystemState(
                last_updated=datetime.now(),
                trading_active=True,
                current_position=None,
                active_orders=[],
                daily_pnl=0.0,
                weekly_pnl=0.0,
                daily_r_multiple=0.0,
                weekly_r_multiple=0.0,
                total_trades=0,
                last_price=0.0,
                last_signal=None
            )
            logger.info("시스템 상태 초기화 완료")
            return True
        except Exception as e:
            logger.error(f"상태 초기화 실패: {e}")
            return False
    
    def get_current_state(self) -> Optional[Dict[str, Any]]:
        """현재 시스템 상태 조회"""
        if self.current_state:
            return self.current_state.to_dict()
        return None
    
    def get_current_position(self):
        """현재 포지션 조회"""
        if self.current_state:
            return self.current_state.current_position
        return None
    
    def get_active_orders(self):
        """활성 주문 조회"""
        if self.current_state:
            return self.current_state.active_orders
        return []
    
    def get_daily_pnl(self):
        """일일 손익 조회"""
        if self.current_state:
            return self.current_state.daily_pnl
        return 0.0
    
    def get_weekly_pnl(self):
        """주간 손익 조회"""
        if self.current_state:
            return self.current_state.weekly_pnl
        return 0.0
    
    def get_daily_r_multiple(self):
        """일일 R-multiple 조회"""
        if self.current_state:
            return self.current_state.daily_r_multiple
        return 0.0
    
    def get_weekly_r_multiple(self):
        """주간 R-multiple 조회"""
        if self.current_state:
            return self.current_state.weekly_r_multiple
        return 0.0
    
    def get_total_trades(self):
        """총 거래 횟수 조회"""
        if self.current_state:
            return self.current_state.total_trades
        return 0
    
    def is_killswitch_active(self):
        """킬스위치 상태 확인"""
        if self.current_state:
            return not self.current_state.trading_active
        return True
    
    def activate_killswitch(self, reason: str = "Manual activation"):
        """킬스위치 활성화"""
        if self.current_state:
            self.current_state.trading_active = False
            self.current_state.last_updated = datetime.now()
            logger.warning(f"킬스위치 활성화: {reason}")
    
    def deactivate_killswitch(self):
        """킬스위치 비활성화"""
        if self.current_state:
            self.current_state.trading_active = True
            self.current_state.last_updated = datetime.now()
            logger.info("킬스위치 비활성화")
    
    def update_system_state(self, system_state):
        """시스템 상태 업데이트"""
        self.current_state = system_state
    
    def set_current_position(self, position):
        """현재 포지션 설정"""
        if self.current_state:
            self.current_state.current_position = position
            self.current_state.last_updated = datetime.now()
    
    def close_current_position(self, order):
        """현재 포지션 청산"""
        if self.current_state:
            self.current_state.current_position = None
            self.current_state.last_updated = datetime.now()
    
    def add_order(self, order):
        """주문 추가"""
        if self.current_state:
            if hasattr(order, 'to_dict'):
                order_dict = order.to_dict()
            else:
                order_dict = order
            self.current_state.active_orders.append(order_dict)
            self.current_state.last_updated = datetime.now()
    
    def update_order_status(self, order):
        """주문 상태 업데이트"""
        if self.current_state and self.current_state.active_orders:
            for i, active_order in enumerate(self.current_state.active_orders):
                if active_order.get('id') == order.id:
                    if hasattr(order, 'to_dict'):
                        self.current_state.active_orders[i] = order.to_dict()
                    else:
                        self.current_state.active_orders[i] = order
                    break
            self.current_state.last_updated = datetime.now()
    
    def update_position(self, position):
        """포지션 업데이트"""
        if self.current_state:
            self.current_state.current_position = position
            self.current_state.last_updated = datetime.now()
    
    def close(self):
        """상태 관리자 종료"""
        logger.info("상태 관리자 종료")
