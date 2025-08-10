"""
주문 실행 및 브로커 모듈
실제 거래소 주문 처리, 체결 상태 추적, 포지션 관리
완전한 Upbit API 구현 사용
"""

import ccxt
import uuid
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from enum import Enum
import logging
import asyncio

from .config import config, env_config
from .data import data_manager
from .risk import PositionSide
from .upbit_api import upbit_api

logger = logging.getLogger(__name__)

class OrderType(Enum):
    """주문 타입"""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"

class OrderStatus(Enum):
    """주문 상태"""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

class Order:
    """주문 정보 클래스"""
    
    def __init__(self, symbol: str, side: str, order_type: OrderType, 
                 amount: float, price: Optional[float] = None, 
                 stop_price: Optional[float] = None, client_order_id: Optional[str] = None):
        self.id = None  # 거래소에서 할당받는 ID
        self.client_order_id = client_order_id or str(uuid.uuid4())
        self.symbol = symbol
        self.side = side  # 'buy' or 'sell'
        self.order_type = order_type
        self.amount = amount
        self.price = price
        self.stop_price = stop_price
        
        # 상태 정보
        self.status = OrderStatus.PENDING
        self.filled_amount = 0.0
        self.remaining_amount = amount
        self.average_price = 0.0
        self.fee = 0.0
        self.fee_currency = ""
        
        # 시간 정보
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.filled_at = None
        
        # 메타데이터
        self.metadata = {}
        
        logger.info(f"주문 생성: {self.client_order_id} - {side} {amount} {symbol}")
    
    def is_active(self) -> bool:
        """활성 주문 여부 확인"""
        return self.status in [OrderStatus.PENDING, OrderStatus.OPEN]
    
    def is_filled(self) -> bool:
        """체결 완료 여부 확인"""
        return self.status == OrderStatus.FILLED
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'id': self.id,
            'client_order_id': self.client_order_id,
            'symbol': self.symbol,
            'side': self.side,
            'order_type': self.order_type.value,
            'amount': self.amount,
            'price': self.price,
            'stop_price': self.stop_price,
            'status': self.status.value,
            'filled_amount': self.filled_amount,
            'remaining_amount': self.remaining_amount,
            'average_price': self.average_price,
            'fee': self.fee,
            'fee_currency': self.fee_currency,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'filled_at': self.filled_at.isoformat() if self.filled_at else None,
            'metadata': self.metadata
        }

class TradingBroker:
    """거래 브로커 - 실제 주문 실행 및 관리"""
    
    def __init__(self):
        self.api = upbit_api  # 새로운 완전한 API 사용
        self.exchange = upbit_api.exchange  # CCXT 백업용
        self.symbol = config.exchange['market']  # BTC/KRW -> KRW-BTC 변환 필요
        self.mode = env_config.get_mode()  # paper or live
        
        # Upbit 마켓 형식으로 변환 (BTC/KRW -> KRW-BTC)
        if '/' in self.symbol:
            base, quote = self.symbol.split('/')
            self.upbit_market = f"{quote}-{base}"
        else:
            self.upbit_market = self.symbol
        
        # 주문 관리
        self.active_orders: Dict[str, Order] = {}  # client_order_id -> Order
        self.order_history: List[Order] = []
        
        # 거래 통계
        self.total_orders = 0
        self.successful_orders = 0
        self.failed_orders = 0
        
        # 재시도 설정
        self.max_retries = 3
        self.retry_delay = 1.0  # seconds
        
        logger.info(f"거래 브로커 초기화 완료: {self.mode} 모드, 마켓: {self.upbit_market}")
    
    def create_market_order(self, side: str, amount: float, 
                           metadata: Optional[Dict] = None) -> Optional[Order]:
        """시장가 주문 생성"""
        try:
            order = Order(
                symbol=self.upbit_market,
                side=side,
                order_type=OrderType.MARKET,
                amount=amount,
                client_order_id=f"market_{side}_{int(time.time())}"
            )
            
            if metadata:
                order.metadata = metadata
            
            if self.mode == "paper":
                return self._execute_paper_order(order)
            else:
                return self._execute_live_order(order)
                
        except Exception as e:
            logger.error(f"시장가 주문 생성 실패: {e}")
            return None
    
    def create_limit_order(self, side: str, amount: float, price: float,
                          metadata: Optional[Dict] = None) -> Optional[Order]:
        """지정가 주문 생성"""
        try:
            order = Order(
                symbol=self.upbit_market,
                side=side,
                order_type=OrderType.LIMIT,
                amount=amount,
                price=price,
                client_order_id=f"limit_{side}_{int(time.time())}"
            )
            
            if metadata:
                order.metadata = metadata
            
            if self.mode == "paper":
                return self._execute_paper_order(order)
            else:
                return self._execute_live_order(order)
                
        except Exception as e:
            logger.error(f"지정가 주문 생성 실패: {e}")
            return None
    
    def _execute_live_order(self, order: Order) -> Optional[Order]:
        """실제 거래소에 주문 전송"""
        try:
            if not self.api.access_key or not self.api.secret_key:
                logger.error("API 키가 설정되지 않았습니다")
                return None
            
            # 주문 실행
            for attempt in range(self.max_retries):
                try:
                    if order.order_type == OrderType.MARKET:
                        if order.side == 'buy':
                            # 시장가 매수: 금액 지정 (KRW)
                            current_price = data_manager.collector.get_current_price()['last']
                            cost = order.amount * current_price
                            upbit_order = self.api.place_buy_order(
                                market=self.upbit_market,
                                price=str(int(cost)),  # KRW 금액
                                ord_type='price'  # 시장가 매수는 금액 지정
                            )
                        else:
                            # 시장가 매도: 수량 지정 (BTC)
                            upbit_order = self.api.place_sell_order(
                                market=self.upbit_market,
                                volume=str(order.amount),
                                ord_type='market'
                            )
                    else:  # LIMIT
                        if order.side == 'buy':
                            upbit_order = self.api.place_buy_order(
                                market=self.upbit_market,
                                volume=str(order.amount),
                                price=str(int(order.price)),
                                ord_type='limit'
                            )
                        else:
                            upbit_order = self.api.place_sell_order(
                                market=self.upbit_market,
                                volume=str(order.amount),
                                price=str(int(order.price)),
                                ord_type='limit'
                            )
                    
                    # 주문 정보 업데이트
                    order.id = upbit_order['uuid']
                    order.status = OrderStatus.OPEN
                    
                    # 주문 등록
                    self.active_orders[order.client_order_id] = order
                    self.total_orders += 1
                    
                    logger.info(f"실거래 주문 성공: {order.client_order_id} - {order.id}")
                    return order
                    
                except Exception as e:
                    logger.warning(f"주문 시도 {attempt + 1} 실패: {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay)
                    else:
                        raise
            
            return None
            
        except Exception as e:
            logger.error(f"실거래 주문 실패: {e}")
            self.failed_orders += 1
            return None
    
    def _execute_paper_order(self, order: Order) -> Order:
        """페이퍼 트레이딩 주문 시뮬레이션"""
        try:
            # 현재 시장 가격 조회
            current_price_data = data_manager.collector.get_current_price()
            current_price = current_price_data['last']
            
            # 시장가 주문은 즉시 체결
            if order.order_type == OrderType.MARKET:
                order.status = OrderStatus.FILLED
                order.average_price = current_price
                order.filled_amount = order.amount
                order.remaining_amount = 0.0
                order.filled_at = datetime.now()
                order.id = f"paper_{order.client_order_id}"  # ID 설정 추가
                
                # 수수료 계산 (0.05%)
                order.fee = order.amount * current_price * 0.0005
                order.fee_currency = 'KRW'
                
                logger.info(f"페이퍼 시장가 주문 체결: {order.client_order_id} @ {current_price:,.0f}원")
            
            # 지정가 주문은 OPEN 상태로 등록
            else:
                order.status = OrderStatus.OPEN
                order.id = f"paper_{order.client_order_id}"
                self.active_orders[order.client_order_id] = order
                logger.info(f"페이퍼 지정가 주문 등록: {order.client_order_id} @ {order.price:,.0f}원")
            
            self.total_orders += 1
            self.successful_orders += 1
            
            return order
            
        except Exception as e:
            logger.error(f"페이퍼 주문 실행 실패: {e}")
            order.status = OrderStatus.REJECTED
            self.failed_orders += 1
            return order
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """주문 상태 조회"""
        try:
            if self.mode == "paper":
                # 페이퍼 트레이딩에서는 로컬 상태 반환
                for order in self.active_orders.values():
                    if order.id == order_id or order.client_order_id == order_id:
                        return order
                return None
            
            # 실거래에서는 거래소에서 조회
            upbit_order = self.api.get_order(uuid=order_id)
            
            # 로컬 주문 찾기
            local_order = None
            for order in self.active_orders.values():
                if order.id == order_id:
                    local_order = order
                    break
            
            if local_order:
                # 상태 업데이트
                local_order.status = self._map_upbit_status(upbit_order['state'])
                local_order.filled_amount = float(upbit_order.get('executed_volume', 0))
                local_order.remaining_amount = float(upbit_order.get('remaining_volume', local_order.amount))
                local_order.average_price = float(upbit_order.get('avg_price', 0)) if upbit_order.get('avg_price') else 0
                local_order.updated_at = datetime.now()
                
                if local_order.status == OrderStatus.FILLED:
                    local_order.filled_at = local_order.updated_at
                
                return local_order
            
            return None
            
        except Exception as e:
            logger.error(f"주문 상태 조회 실패: {e}")
            return None
    
    def _map_upbit_status(self, upbit_status: str) -> OrderStatus:
        """Upbit 주문 상태를 내부 상태로 매핑"""
        status_mapping = {
            'wait': OrderStatus.OPEN,
            'done': OrderStatus.FILLED,
            'cancel': OrderStatus.CANCELED,
        }
        return status_mapping.get(upbit_status, OrderStatus.PENDING)
    
    def get_open_orders(self) -> List[Order]:
        """미체결 주문 조회"""
        try:
            if self.mode == "paper":
                return [order for order in self.active_orders.values() if order.is_active()]
            
            # 실거래에서는 거래소에서 조회
            upbit_orders = self.api.get_orders_open(market=self.upbit_market)
            
            open_orders = []
            for upbit_order in upbit_orders:
                # 기존 로컬 주문 찾기 또는 새로 생성
                local_order = None
                for order in self.active_orders.values():
                    if order.id == upbit_order['uuid']:
                        local_order = order
                        break
                
                if not local_order:
                    # 새 주문 객체 생성
                    local_order = Order(
                        symbol=self.upbit_market,
                        side=upbit_order['side'],
                        order_type=OrderType.LIMIT if upbit_order['ord_type'] == 'limit' else OrderType.MARKET,
                        amount=float(upbit_order['volume'])
                    )
                    local_order.id = upbit_order['uuid']
                    local_order.price = float(upbit_order.get('price', 0)) if upbit_order.get('price') else None
                    self.active_orders[local_order.client_order_id] = local_order
                
                # 상태 업데이트
                local_order.status = self._map_upbit_status(upbit_order['state'])
                local_order.filled_amount = float(upbit_order.get('executed_volume', 0))
                local_order.remaining_amount = float(upbit_order.get('remaining_volume', local_order.amount))
                
                open_orders.append(local_order)
            
            return open_orders
            
        except Exception as e:
            logger.error(f"미체결 주문 조회 실패: {e}")
            return []
    
    def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        try:
            if self.mode == "paper":
                # 페이퍼 트레이딩에서는 로컬 상태만 변경
                for order in self.active_orders.values():
                    if order.id == order_id or order.client_order_id == order_id:
                        order.status = OrderStatus.CANCELED
                        order.updated_at = datetime.now()
                        logger.info(f"페이퍼 주문 취소: {order.client_order_id}")
                        return True
                return False
            
            # 실거래에서는 거래소에 취소 요청
            result = self.api.cancel_order(uuid=order_id)
            
            if result:
                # 로컬 주문 상태 업데이트
                for order in self.active_orders.values():
                    if order.id == order_id:
                        order.status = OrderStatus.CANCELED
                        order.updated_at = datetime.now()
                        logger.info(f"주문 취소 성공: {order.client_order_id}")
                        return True
            
            return False
            
        except Exception as e:
            logger.error(f"주문 취소 실패: {e}")
            return False
    
    def get_order_history(self, limit: int = 100) -> List[Order]:
        """주문 내역 조회"""
        try:
            if self.mode == "paper":
                return self.order_history[-limit:]
            
            # 실거래에서는 거래소에서 조회
            upbit_orders = self.api.get_orders_closed(market=self.upbit_market, limit=limit)
            
            history = []
            for upbit_order in upbit_orders:
                order = Order(
                    symbol=self.upbit_market,
                    side=upbit_order['side'],
                    order_type=OrderType.LIMIT if upbit_order['ord_type'] == 'limit' else OrderType.MARKET,
                    amount=float(upbit_order['volume'])
                )
                order.id = upbit_order['uuid']
                order.price = float(upbit_order.get('price', 0)) if upbit_order.get('price') else None
                order.status = self._map_upbit_status(upbit_order['state'])
                order.filled_amount = float(upbit_order.get('executed_volume', 0))
                order.average_price = float(upbit_order.get('avg_price', 0)) if upbit_order.get('avg_price') else 0
                
                # 시간 정보
                if upbit_order.get('created_at'):
                    order.created_at = datetime.fromisoformat(upbit_order['created_at'].replace('Z', '+00:00'))
                if upbit_order.get('updated_at'):
                    order.updated_at = datetime.fromisoformat(upbit_order['updated_at'].replace('Z', '+00:00'))
                
                history.append(order)
            
            return history
            
        except Exception as e:
            logger.error(f"주문 내역 조회 실패: {e}")
            return []
    
    # ========== 편의 메소드들 ==========
    
    def place_buy_order(self, amount: float, price: Optional[float] = None, 
                       order_type: str = 'limit', metadata: Optional[Dict] = None) -> Optional[Order]:
        """매수 주문 (기존 호환성)"""
        if order_type == 'market':
            return self.create_market_order('buy', amount, metadata)
        else:
            return self.create_limit_order('buy', amount, price, metadata)
    
    def place_sell_order(self, amount: float, price: Optional[float] = None,
                        order_type: str = 'limit', metadata: Optional[Dict] = None) -> Optional[Order]:
        """매도 주문 (기존 호환성)"""
        if order_type == 'market':
            return self.create_market_order('sell', amount, metadata)
        else:
            return self.create_limit_order('sell', amount, price, metadata)
    
    def get_account_info(self) -> Dict[str, Any]:
        """계좌 정보 조회"""
        try:
            if self.mode == "paper":
                return {
                    'mode': 'paper',
                    'balance': {
                        'KRW': {'balance': 1000000.0, 'locked': 0.0, 'total': 1000000.0},
                        'BTC': {'balance': 0.0, 'locked': 0.0, 'total': 0.0}
                    },
                    'orders': len(self.active_orders)
                }
            
            # 공식 API를 통한 계좌 조회
            accounts = self.api.get_accounts()
            balance = {}
            
            for account in accounts:
                currency = account['currency']
                account_balance = float(account['balance'])
                locked_balance = float(account['locked'])
                total_balance = account_balance + locked_balance
                
                balance[currency] = {
                    'balance': account_balance,      # 사용 가능한 잔고
                    'locked': locked_balance,        # 주문에 사용 중인 잔고
                    'total': total_balance          # 전체 잔고
                }
                
                logger.debug(f"{currency} 잔고: 사용가능 {account_balance}, 사용중 {locked_balance}, 총 {total_balance}")
            
            return {
                'mode': 'live',
                'balance': balance,
                'orders': len(self.active_orders)
            }
            
        except Exception as e:
            logger.error(f"계좌 정보 조회 실패: {e}")
            # 에러 발생 시 기본 구조 반환
            return {
                'mode': self.mode,
                'balance': {
                    'KRW': {'balance': 0.0, 'locked': 0.0, 'total': 0.0},
                    'BTC': {'balance': 0.0, 'locked': 0.0, 'total': 0.0}
                },
                'orders': 0,
                'error': str(e)
            }
    
    def update_orders(self):
        """활성 주문들의 상태를 업데이트"""
        try:
            updated_orders = {}
            
            for order_id, order in list(self.active_orders.items()):
                if order.is_active():
                    # 주문 상태 조회
                    updated_order = self.get_order_status(order_id)
                    if updated_order:
                        updated_orders[order_id] = updated_order
                        
                        # 상태 변경 로깅
                        if updated_order.status != order.status:
                            logger.info(f"주문 상태 변경: {order_id} {order.status.value} -> {updated_order.status.value}")
                    else:
                        # 조회 실패한 주문은 유지
                        updated_orders[order_id] = order
                else:
                    # 비활성 주문은 그대로 유지
                    updated_orders[order_id] = order
            
            self.active_orders = updated_orders
            logger.debug(f"주문 상태 업데이트 완료: {len(self.active_orders)}개 주문")
            
        except Exception as e:
            logger.error(f"주문 상태 업데이트 실패: {e}")
    
    def get_active_orders(self) -> Dict[str, Order]:
        """활성 주문 목록 반환"""
        try:
            # 실제로 활성 상태인 주문들만 필터링
            active_orders = {}
            for order_id, order in self.active_orders.items():
                if order.is_active():
                    active_orders[order_id] = order
            
            logger.debug(f"활성 주문 조회: {len(active_orders)}개")
            return active_orders
            
        except Exception as e:
            logger.error(f"활성 주문 조회 실패: {e}")
            return {}

    def get_trading_fees(self) -> Dict[str, float]:
        """거래 수수료 정보"""
        # Upbit 기본 수수료 (실제로는 API에서 조회해야 함)
        return {
            'maker': 0.0005,  # 0.05%
            'taker': 0.0005   # 0.05%
        }
    
    def cleanup(self):
        """정리 작업"""
        try:
            logger.info("브로커 정리 작업 시작...")
            
            # 활성 주문 상태 업데이트
            for order in list(self.active_orders.values()):
                if order.is_active():
                    updated_order = self.get_order_status(order.id or order.client_order_id)
                    if updated_order:
                        logger.info(f"주문 상태 업데이트: {updated_order.client_order_id} - {updated_order.status.value}")
            
            logger.info(f"브로커 정리 완료. 총 주문: {self.total_orders}, 성공: {self.successful_orders}, 실패: {self.failed_orders}")
            
        except Exception as e:
            logger.error(f"브로커 정리 작업 실패: {e}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """거래 통계 조회"""
        active_count = len([o for o in self.active_orders.values() if o.is_active()])
        filled_count = len([o for o in self.active_orders.values() if o.is_filled()])
        
        return {
            'total_orders': self.total_orders,
            'successful_orders': self.successful_orders,
            'failed_orders': self.failed_orders,
            'active_orders': active_count,
            'filled_orders': filled_count,
            'success_rate': (self.successful_orders / max(self.total_orders, 1)) * 100
        }
    
    async def create_market_order(self, symbol: str, side: str, amount: float, 
                                 emergency: bool = False) -> Optional[Dict[str, Any]]:
        """
        시장가 주문 생성 (긴급청산용)
        
        Args:
            symbol: 거래 심볼
            side: 'buy' or 'sell'
            amount: 주문 수량
            emergency: 긴급 주문 여부
            
        Returns:
            주문 결과 딕셔너리
        """
        try:
            if emergency:
                logger.warning(f"긴급 시장가 주문: {side} {amount} {symbol}")
            
            if self.mode == 'paper':
                # 페이퍼 트레이딩 모드
                current_price = await self._get_current_price(symbol)
                if not current_price:
                    logger.error("현재 가격 조회 실패")
                    return None
                
                order_result = {
                    'id': f'paper_{uuid.uuid4().hex[:8]}',
                    'symbol': symbol,
                    'side': side,
                    'amount': amount,
                    'price': current_price,
                    'status': 'filled',
                    'timestamp': datetime.now().isoformat(),
                    'emergency': emergency
                }
                
                logger.info(f"페이퍼 시장가 주문 완료: {order_result}")
                return order_result
            
            else:
                # 실제 거래 모드
                upbit_symbol = self._convert_symbol_to_upbit(symbol)
                
                if side == 'buy':
                    # 매수: 금액 기준 주문
                    current_price = await self._get_current_price(symbol)
                    if not current_price:
                        return None
                    
                    total_amount = amount * current_price
                    order_result = await self.api.create_market_buy_order(upbit_symbol, total_amount)
                    
                else:
                    # 매도: 수량 기준 주문
                    order_result = await self.api.create_market_sell_order(upbit_symbol, amount)
                
                if order_result:
                    logger.info(f"시장가 주문 성공: {order_result.get('uuid', 'N/A')}")
                    
                    # 주문 정보 정리
                    return {
                        'id': order_result.get('uuid'),
                        'symbol': symbol,
                        'side': side,
                        'amount': amount,
                        'price': order_result.get('price', 0),
                        'status': 'pending',
                        'timestamp': datetime.now().isoformat(),
                        'emergency': emergency,
                        'raw': order_result
                    }
                else:
                    logger.error(f"시장가 주문 실패: {symbol} {side} {amount}")
                    return None
                    
        except Exception as e:
            logger.error(f"시장가 주문 생성 실패: {e}")
            return None
    
    async def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """
        미체결 주문 조회
        
        Args:
            symbol: 특정 심볼 (None이면 전체)
            
        Returns:
            미체결 주문 리스트
        """
        try:
            if self.mode == 'paper':
                # 페이퍼 트레이딩: 활성 주문 반환
                open_orders = []
                for order in self.active_orders.values():
                    if order.is_active():
                        if symbol is None or order.symbol == symbol:
                            open_orders.append(order.to_dict())
                return open_orders
            
            else:
                # 실제 거래: API 조회
                if symbol:
                    upbit_symbol = self._convert_symbol_to_upbit(symbol)
                    orders = await self.api.get_orders(market=upbit_symbol, state='wait')
                else:
                    orders = await self.api.get_orders(state='wait')
                
                # 형식 변환
                open_orders = []
                for order in orders:
                    open_orders.append({
                        'id': order.get('uuid'),
                        'symbol': self._convert_symbol_from_upbit(order.get('market', '')),
                        'side': order.get('side'),
                        'amount': float(order.get('volume', 0)),
                        'price': float(order.get('price', 0)),
                        'status': 'open',
                        'created_at': order.get('created_at')
                    })
                
                return open_orders
                
        except Exception as e:
            logger.error(f"미체결 주문 조회 실패: {e}")
            return []
    
    async def cancel_order(self, order_id: str, symbol: str = None) -> bool:
        """
        주문 취소
        
        Args:
            order_id: 주문 ID
            symbol: 심볼 (선택사항)
            
        Returns:
            취소 성공 여부
        """
        try:
            if self.mode == 'paper':
                # 페이퍼 트레이딩: 로컬 주문 취소
                if order_id in self.active_orders:
                    order = self.active_orders[order_id]
                    order.status = OrderStatus.CANCELED
                    order.updated_at = datetime.now()
                    logger.info(f"페이퍼 주문 취소: {order_id}")
                    return True
                else:
                    logger.warning(f"취소할 주문을 찾을 수 없음: {order_id}")
                    return False
            
            else:
                # 실제 거래: API 호출
                result = await self.api.cancel_order(order_id)
                
                if result:
                    logger.info(f"주문 취소 성공: {order_id}")
                    
                    # 로컬 주문 상태도 업데이트
                    if order_id in self.active_orders:
                        self.active_orders[order_id].status = OrderStatus.CANCELED
                        self.active_orders[order_id].updated_at = datetime.now()
                    
                    return True
                else:
                    logger.error(f"주문 취소 실패: {order_id}")
                    return False
                    
        except Exception as e:
            logger.error(f"주문 취소 중 오류: {e}")
            return False
    
    async def emergency_close_all_positions(self) -> Dict[str, Any]:
        """
        모든 포지션 긴급청산
        
        Returns:
            청산 결과 딕셔너리
        """
        try:
            logger.warning("모든 포지션 긴급청산 시작")
            
            results = {
                'success': [],
                'failed': [],
                'cancelled_orders': [],
                'total_positions': 0,
                'total_orders': 0
            }
            
            # 1. 모든 미체결 주문 취소
            open_orders = await self.get_open_orders()
            results['total_orders'] = len(open_orders)
            
            for order in open_orders:
                try:
                    cancel_success = await self.cancel_order(order['id'], order['symbol'])
                    if cancel_success:
                        results['cancelled_orders'].append(order['id'])
                        logger.info(f"주문 취소 완료: {order['id']}")
                    else:
                        logger.error(f"주문 취소 실패: {order['id']}")
                except Exception as e:
                    logger.error(f"주문 {order['id']} 취소 중 오류: {e}")
            
            # 2. 현재 잔고 조회 및 포지션 청산
            account_info = await self.get_account_info()
            
            if 'balance' in account_info:
                for currency, balance_info in account_info['balance'].items():
                    if currency != 'KRW' and balance_info['balance'] > 0:
                        try:
                            symbol = f"{currency}/KRW"
                            amount = balance_info['balance']
                            
                            logger.warning(f"포지션 긴급청산: {symbol} {amount}")
                            
                            # 시장가 매도 주문
                            order_result = await self.create_market_order(
                                symbol=symbol,
                                side='sell',
                                amount=amount,
                                emergency=True
                            )
                            
                            if order_result:
                                results['success'].append({
                                    'symbol': symbol,
                                    'amount': amount,
                                    'order_id': order_result.get('id')
                                })
                                logger.info(f"긴급청산 성공: {symbol}")
                            else:
                                results['failed'].append({
                                    'symbol': symbol,
                                    'amount': amount,
                                    'error': 'order_creation_failed'
                                })
                                logger.error(f"긴급청산 실패: {symbol}")
                                
                            results['total_positions'] += 1
                            
                        except Exception as e:
                            logger.error(f"포지션 {currency} 청산 중 오류: {e}")
                            results['failed'].append({
                                'symbol': f"{currency}/KRW",
                                'amount': balance_info['balance'],
                                'error': str(e)
                            })
            
            logger.warning(f"긴급청산 완료: 성공 {len(results['success'])}개, 실패 {len(results['failed'])}개")
            return results
            
        except Exception as e:
            logger.error(f"긴급청산 중 치명적 오류: {e}")
            return {
                'success': [],
                'failed': [],
                'cancelled_orders': [],
                'total_positions': 0,
                'total_orders': 0,
                'error': str(e)
            }
    
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """현재 가격 조회 (내부 메서드)"""
        try:
            upbit_symbol = self._convert_symbol_to_upbit(symbol)
            ticker = await self.api.get_ticker(upbit_symbol)
            
            if ticker and len(ticker) > 0:
                return float(ticker[0].get('trade_price', 0))
            else:
                return None
                
        except Exception as e:
            logger.error(f"현재 가격 조회 실패: {e}")
            return None

# 전역 브로커 인스턴스
trading_broker = TradingBroker()
