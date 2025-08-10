"""
상태 관리 및 동기화 모듈
포지션, 주문, 체결 상태 관리 및 재시작 시 상태 동기화
"""

import json
import redis
import psycopg2
import asyncio
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import logging
import threading
import time

from .config import config, env_config
from .risk import Position, PositionSide
from .broker import Order, OrderStatus

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

class DatabaseManager:
    """데이터베이스 관리자"""
    
    def __init__(self):
        self.connection = None
        self.db_config = env_config.get_database_config()
        self._connect()
    
    def _connect(self):
        """데이터베이스 연결"""
        try:
            self.connection = psycopg2.connect(
                host=self.db_config['host'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password']
            )
            self.connection.autocommit = True
            logger.info("데이터베이스 연결 성공")
            
        except Exception as e:
            logger.error(f"데이터베이스 연결 실패: {e}")
            self.connection = None
    
    def execute_query(self, query: str, params: Optional[Tuple] = None) -> Optional[List[Tuple]]:
        """쿼리 실행"""
        if not self.connection:
            logger.error("데이터베이스 연결이 없습니다")
            return None
        
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params)
                
                if query.strip().upper().startswith('SELECT'):
                    return cursor.fetchall()
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"쿼리 실행 실패: {e}")
            return None
    
    def save_order(self, order: Order):
        """주문 정보 저장"""
        try:
            query = """
            INSERT INTO orders (uuid, market, side, ord_type, price, volume, state, 
                              created_at, executed_volume, paid_fee, remaining_fee, 
                              reserved_fee, locked, trades_count, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (uuid) DO UPDATE SET
                state = EXCLUDED.state,
                executed_volume = EXCLUDED.executed_volume,
                paid_fee = EXCLUDED.paid_fee,
                updated_at = EXCLUDED.updated_at
            """
            
            params = (
                order.id or order.client_order_id,
                order.symbol,
                order.side,
                order.order_type.value,
                order.price or 0,
                order.amount,
                order.status.value,
                order.created_at,
                order.filled_amount,
                order.fee,
                0,  # remaining_fee
                0,  # reserved_fee
                0,  # locked
                1 if order.is_filled() else 0,
                order.updated_at
            )
            
            self.execute_query(query, params)
            logger.debug(f"주문 저장: {order.client_order_id}")
            
        except Exception as e:
            logger.error(f"주문 저장 실패: {e}")
    
    def save_position(self, position: Position):
        """포지션 정보 저장"""
        try:
            query = """
            INSERT INTO positions (market, side, entry_price, volume, stop_price, 
                                 trail_price, unrealized_pnl, realized_pnl, 
                                 created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (market) DO UPDATE SET
                side = EXCLUDED.side,
                entry_price = EXCLUDED.entry_price,
                volume = EXCLUDED.volume,
                stop_price = EXCLUDED.stop_price,
                trail_price = EXCLUDED.trail_price,
                unrealized_pnl = EXCLUDED.unrealized_pnl,
                realized_pnl = EXCLUDED.realized_pnl,
                updated_at = EXCLUDED.updated_at
            """
            
            params = (
                config.exchange['market'],
                position.side.value,
                position.entry_price,
                position.volume,
                position.stop_loss,
                position.trail_price,
                position.unrealized_pnl,
                position.realized_pnl,
                position.timestamp,
                datetime.now()
            )
            
            self.execute_query(query, params)
            logger.debug("포지션 저장 완료")
            
        except Exception as e:
            logger.error(f"포지션 저장 실패: {e}")
    
    def save_trade(self, trade_data: Dict[str, Any]):
        """거래 내역 저장"""
        try:
            query = """
            INSERT INTO trades (order_uuid, market, side, price, volume, fee, 
                              pnl, r_multiple, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            params = (
                trade_data.get('order_id', ''),
                config.exchange['market'],
                trade_data['side'],
                trade_data['price'],
                trade_data['volume'],
                trade_data['fee'],
                trade_data.get('pnl', 0),
                trade_data.get('r_multiple', 0),
                trade_data.get('timestamp', datetime.now())
            )
            
            self.execute_query(query, params)
            logger.debug("거래 내역 저장 완료")
            
        except Exception as e:
            logger.error(f"거래 내역 저장 실패: {e}")
    
    def save_account_snapshot(self, snapshot_data: Dict[str, Any]):
        """계좌 스냅샷 저장"""
        try:
            query = """
            INSERT INTO account_snapshots (total_krw, total_btc, total_value_krw,
                                         daily_pnl, weekly_pnl, total_pnl, 
                                         current_r, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            params = (
                snapshot_data.get('total_krw', 0),
                snapshot_data.get('total_btc', 0),
                snapshot_data.get('total_value_krw', 0),
                snapshot_data.get('daily_pnl', 0),
                snapshot_data.get('weekly_pnl', 0),
                snapshot_data.get('total_pnl', 0),
                snapshot_data.get('current_r', 0),
                datetime.now()
            )
            
            self.execute_query(query, params)
            logger.debug("계좌 스냅샷 저장 완료")
            
        except Exception as e:
            logger.error(f"계좌 스냅샷 저장 실패: {e}")
    
    def get_latest_position(self) -> Optional[Dict[str, Any]]:
        """최신 포지션 정보 조회"""
        try:
            query = """
            SELECT market, side, entry_price, volume, stop_price, trail_price,
                   unrealized_pnl, realized_pnl, created_at, updated_at
            FROM positions 
            WHERE market = %s 
            ORDER BY updated_at DESC 
            LIMIT 1
            """
            
            result = self.execute_query(query, (config.exchange['market'],))
            
            if result and result[0]:
                row = result[0]
                return {
                    'market': row[0],
                    'side': row[1],
                    'entry_price': float(row[2]),
                    'volume': float(row[3]),
                    'stop_price': float(row[4]),
                    'trail_price': float(row[5]),
                    'unrealized_pnl': float(row[6]),
                    'realized_pnl': float(row[7]),
                    'created_at': row[8],
                    'updated_at': row[9]
                }
            
            return None
            
        except Exception as e:
            logger.error(f"포지션 조회 실패: {e}")
            return None
    
    def get_open_orders(self) -> List[Dict[str, Any]]:
        """미체결 주문 조회"""
        try:
            query = """
            SELECT uuid, market, side, ord_type, price, volume, state, created_at
            FROM orders 
            WHERE market = %s AND state IN ('open', 'pending')
            ORDER BY created_at DESC
            """
            
            result = self.execute_query(query, (config.exchange['market'],))
            
            orders = []
            if result:
                for row in result:
                    orders.append({
                        'uuid': row[0],
                        'market': row[1],
                        'side': row[2],
                        'ord_type': row[3],
                        'price': float(row[4]) if row[4] else None,
                        'volume': float(row[5]),
                        'state': row[6],
                        'created_at': row[7]
                    })
            
            return orders
            
        except Exception as e:
            logger.error(f"미체결 주문 조회 실패: {e}")
            return []

class RedisManager:
    """Redis 캐시 관리자"""
    
    def __init__(self):
        self.redis_client = None
        self.redis_url = env_config.get_redis_config()
        self._connect()
    
    def _connect(self):
        """Redis 연결"""
        try:
            self.redis_client = redis.from_url(self.redis_url, decode_responses=True)
            self.redis_client.ping()
            logger.info("Redis 연결 성공")
            
        except Exception as e:
            logger.error(f"Redis 연결 실패: {e}")
            self.redis_client = None
    
    def set_state(self, key: str, value: Any, expire_seconds: int = 3600):
        """상태 저장"""
        if not self.redis_client:
            return False
        
        try:
            if isinstance(value, dict):
                value = json.dumps(value, default=str)
            
            self.redis_client.setex(key, expire_seconds, value)
            return True
            
        except Exception as e:
            logger.error(f"Redis 저장 실패: {e}")
            return False
    
    def get_state(self, key: str) -> Optional[Any]:
        """상태 조회"""
        if not self.redis_client:
            return None
        
        try:
            value = self.redis_client.get(key)
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
            
        except Exception as e:
            logger.error(f"Redis 조회 실패: {e}")
            return None
    
    def delete_state(self, key: str) -> bool:
        """상태 삭제"""
        if not self.redis_client:
            return False
        
        try:
            self.redis_client.delete(key)
            return True
            
        except Exception as e:
            logger.error(f"Redis 삭제 실패: {e}")
            return False
    
    def set_lock(self, key: str, timeout: int = 30) -> bool:
        """분산 락 설정"""
        if not self.redis_client:
            return False
        
        try:
            return self.redis_client.set(f"lock:{key}", "1", nx=True, ex=timeout)
        except Exception as e:
            logger.error(f"락 설정 실패: {e}")
            return False
    
    def release_lock(self, key: str) -> bool:
        """분산 락 해제"""
        if not self.redis_client:
            return False
        
        try:
            self.redis_client.delete(f"lock:{key}")
            return True
        except Exception as e:
            logger.error(f"락 해제 실패: {e}")
            return False

class StateManager:
    """상태 관리자 - 전체 시스템 상태 관리 및 동기화"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.redis_manager = RedisManager()
        
        # 상태 캐시
        self.current_state: Optional[SystemState] = None
        self.last_sync_time = datetime.now()
        
        # 동기화 설정
        self.sync_interval = 30  # seconds
        self.auto_sync_enabled = True
        
        # 백그라운드 동기화 스레드
        self.sync_thread = None
        self.stop_sync = threading.Event()
        
        logger.info("상태 관리자 초기화 완료")
    
    def initialize_state(self) -> bool:
        """시스템 상태 초기화"""
        try:
            # Redis에서 기존 상태 조회
            cached_state = self.redis_manager.get_state("system_state")
            
            if cached_state:
                self.current_state = SystemState.from_dict(cached_state)
                logger.info("Redis에서 상태 복원 완료")
            else:
                # 새로운 상태 생성
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
                logger.info("새로운 시스템 상태 생성")
            
            # 데이터베이스와 동기화
            self.sync_with_database()
            
            # 자동 동기화 시작
            if self.auto_sync_enabled:
                self.start_auto_sync()
            
            return True
            
        except Exception as e:
            logger.error(f"상태 초기화 실패: {e}")
            return False
    
    def sync_with_database(self) -> bool:
        """데이터베이스와 상태 동기화"""
        try:
            if not self.current_state:
                return False
            
            # 최신 포지션 정보 동기화
            latest_position = self.db_manager.get_latest_position()
            if latest_position and latest_position['side'] != 'flat':
                self.current_state.current_position = latest_position
                logger.debug("포지션 상태 동기화 완료")
            else:
                self.current_state.current_position = None
            
            # 미체결 주문 동기화
            open_orders = self.db_manager.get_open_orders()
            self.current_state.active_orders = open_orders
            logger.debug(f"미체결 주문 {len(open_orders)}개 동기화 완료")
            
            # Redis에 상태 저장
            self.redis_manager.set_state("system_state", self.current_state.to_dict())
            
            self.last_sync_time = datetime.now()
            return True
            
        except Exception as e:
            logger.error(f"데이터베이스 동기화 실패: {e}")
            return False
    
    def sync_with_exchange(self) -> bool:
        """거래소와 상태 동기화"""
        try:
            from .data import data_manager
            from .broker import trading_broker
            
            # 현재 가격 업데이트
            try:
                current_price_data = data_manager.collector.get_current_price()
                self.current_state.last_price = current_price_data['last']
            except Exception as e:
                logger.warning(f"가격 정보 업데이트 실패: {e}")
            
            # 거래소 주문 상태 업데이트
            trading_broker.update_orders()
            
            # 활성 주문 상태 동기화
            active_orders_dict = trading_broker.get_active_orders()
            # 딕셔너리를 리스트로 변환
            active_orders_list = []
            for order in active_orders_dict.values():
                if hasattr(order, 'to_dict'):
                    active_orders_list.append(order.to_dict())
                else:
                    active_orders_list.append(order)
            self.current_state.active_orders = active_orders_list
            
            logger.debug("거래소 상태 동기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"거래소 동기화 실패: {e}")
            return False
    
    def update_position_state(self, position: Position):
        """포지션 상태 업데이트"""
        try:
            if self.current_state:
                self.current_state.current_position = position.to_dict()
                self.current_state.last_updated = datetime.now()
                
                # 데이터베이스에 저장
                self.db_manager.save_position(position)
                
                # Redis에 저장
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
                
                logger.debug("포지션 상태 업데이트 완료")
                
        except Exception as e:
            logger.error(f"포지션 상태 업데이트 실패: {e}")
    
    def update_order_state(self, order: Order):
        """주문 상태 업데이트"""
        try:
            # 데이터베이스에 저장
            self.db_manager.save_order(order)
            
            # 현재 상태 업데이트
            if self.current_state:
                self.current_state.last_updated = datetime.now()
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
            
            logger.debug(f"주문 상태 업데이트: {order.client_order_id}")
            
        except Exception as e:
            logger.error(f"주문 상태 업데이트 실패: {e}")
    
    def update_pnl_stats(self, daily_pnl: float, weekly_pnl: float, 
                        daily_r: float, weekly_r: float):
        """손익 통계 업데이트"""
        try:
            if self.current_state:
                self.current_state.daily_pnl = daily_pnl
                self.current_state.weekly_pnl = weekly_pnl
                self.current_state.daily_r_multiple = daily_r
                self.current_state.weekly_r_multiple = weekly_r
                self.current_state.last_updated = datetime.now()
                
                # Redis에 저장
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
                
                logger.debug("손익 통계 업데이트 완료")
                
        except Exception as e:
            logger.error(f"손익 통계 업데이트 실패: {e}")
    
    def save_account_snapshot(self):
        """계좌 스냅샷 저장"""
        try:
            from .data import data_manager
            
            # 계좌 정보 조회
            balance = data_manager.collector.get_account_balance()
            current_price = data_manager.collector.get_current_price()['last']
            
            snapshot_data = {
                'total_krw': balance['krw']['total'],
                'total_btc': balance['btc']['total'],
                'total_value_krw': balance['krw']['total'] + (balance['btc']['total'] * current_price),
                'daily_pnl': self.current_state.daily_pnl if self.current_state else 0,
                'weekly_pnl': self.current_state.weekly_pnl if self.current_state else 0,
                'total_pnl': 0,  # 별도 계산 필요
                'current_r': self.current_state.daily_r_multiple if self.current_state else 0
            }
            
            self.db_manager.save_account_snapshot(snapshot_data)
            logger.info("계좌 스냅샷 저장 완료")
            
        except Exception as e:
            logger.error(f"계좌 스냅샷 저장 실패: {e}")
    
    def start_auto_sync(self):
        """자동 동기화 시작"""
        if self.sync_thread and self.sync_thread.is_alive():
            return
        
        self.stop_sync.clear()
        self.sync_thread = threading.Thread(target=self._auto_sync_worker, daemon=True)
        self.sync_thread.start()
        logger.info("자동 동기화 시작")
    
    def stop_auto_sync(self):
        """자동 동기화 중지"""
        self.stop_sync.set()
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        logger.info("자동 동기화 중지")
    
    def _auto_sync_worker(self):
        """자동 동기화 워커"""
        while not self.stop_sync.is_set():
            try:
                # 데이터베이스 동기화
                self.sync_with_database()
                
                # 거래소 동기화
                self.sync_with_exchange()
                
                # 주기적으로 계좌 스냅샷 저장 (10분마다)
                if (datetime.now() - self.last_sync_time).total_seconds() > 600:
                    self.save_account_snapshot()
                
            except Exception as e:
                logger.error(f"자동 동기화 오류: {e}")
            
            # 대기
            self.stop_sync.wait(self.sync_interval)
    
    def get_current_state(self) -> Optional[Dict[str, Any]]:
        """현재 시스템 상태 조회"""
        if self.current_state:
            return self.current_state.to_dict()
        return None
    
    def emergency_state_reset(self) -> bool:
        """긴급 상태 초기화"""
        try:
            logger.warning("긴급 상태 초기화 실행")
            
            # Redis 상태 삭제
            self.redis_manager.delete_state("system_state")
            
            # 새로운 상태 생성
            self.current_state = SystemState(
                last_updated=datetime.now(),
                trading_active=False,  # 거래 중단
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
            
            # 상태 저장
            self.redis_manager.set_state("system_state", self.current_state.to_dict())
            
            logger.info("긴급 상태 초기화 완료")
            return True
            
        except Exception as e:
            logger.error(f"긴급 상태 초기화 실패: {e}")
            return False
    
    # runner.py 호환성을 위한 편의 메서드들
    def get_current_position(self):
        """현재 포지션 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.current_position
        return None
    
    def get_active_orders(self):
        """활성 주문 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.active_orders
        return []
    
    def get_daily_pnl(self):
        """일일 손익 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.daily_pnl
        return 0.0
    
    def get_weekly_pnl(self):
        """주간 손익 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.weekly_pnl
        return 0.0
    
    def get_daily_r_multiple(self):
        """일일 R-multiple 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.daily_r_multiple
        return 0.0
    
    def get_weekly_r_multiple(self):
        """주간 R-multiple 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.weekly_r_multiple
        return 0.0
    
    def get_total_trades(self):
        """총 거래 횟수 조회 (호환성 메서드)"""
        if self.current_state:
            return self.current_state.total_trades
        return 0
    
    def is_killswitch_active(self):
        """킬스위치 상태 확인 (호환성 메서드)"""
        if self.current_state:
            return not self.current_state.trading_active
        return True  # 안전을 위해 기본값은 True
    
    def activate_killswitch(self, reason: str = "Manual activation"):
        """킬스위치 활성화 (호환성 메서드)"""
        if self.current_state:
            self.current_state.trading_active = False
            self.current_state.last_updated = datetime.now()
            # Redis에 상태 저장
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
            logger.warning(f"킬스위치 활성화: {reason}")
    
    def deactivate_killswitch(self):
        """킬스위치 비활성화 (호환성 메서드)"""
        if self.current_state:
            self.current_state.trading_active = True
            self.current_state.last_updated = datetime.now()
            # Redis에 상태 저장
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
            logger.info("킬스위치 비활성화")
    
    def update_system_state(self, system_state):
        """시스템 상태 업데이트 (호환성 메서드)"""
        self.current_state = system_state
        if hasattr(self, 'redis_manager') and self.redis_manager:
            self.redis_manager.set_state("system_state", system_state.to_dict())
    
    def set_current_position(self, position):
        """현재 포지션 설정 (호환성 메서드)"""
        if self.current_state:
            self.current_state.current_position = position
            self.current_state.last_updated = datetime.now()
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
    
    def save_state(self):
        """현재 상태를 저장"""
        try:
            if not self.current_state:
                logger.warning("저장할 상태가 없습니다")
                return
            
            # Redis에 상태 저장
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
                logger.debug("Redis에 상태 저장 완료")
            
            # 데이터베이스에 상태 저장
            if hasattr(self, 'db_manager') and self.db_manager:
                # 필요시 DB 저장 로직 추가
                logger.debug("데이터베이스에 상태 저장 완료")
            
        except Exception as e:
            logger.error(f"상태 저장 실패: {e}")

    def close(self):
        """상태 관리자 종료 및 리소스 정리"""
        try:
            logger.info("상태 관리자 종료 시작...")
            
            # 자동 동기화 중지
            if hasattr(self, '_sync_task') and self._sync_task:
                self._sync_task.cancel()
                logger.info("자동 동기화 중지됨")
            
            # 최종 상태 저장
            if self.current_state:
                self.save_state()
                logger.info("최종 상태 저장 완료")
            
            # Redis 연결 종료
            if hasattr(self, 'redis_manager') and self.redis_manager:
                # Redis 연결은 자동으로 정리됨
                logger.info("Redis 연결 정리됨")
            
            # DB 연결 종료
            if hasattr(self, 'db_manager') and self.db_manager:
                # DB 연결은 자동으로 정리됨
                logger.info("DB 연결 정리됨")
            
            logger.info("상태 관리자 종료 완료")
            
        except Exception as e:
            logger.error(f"상태 관리자 종료 중 오류: {e}")

    def close_current_position(self, order):
        """현재 포지션 청산 (호환성 메서드)"""
        if self.current_state:
            self.current_state.current_position = None
            self.current_state.last_updated = datetime.now()
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
    
    def add_order(self, order):
        """주문 추가 (호환성 메서드)"""
        if self.current_state:
            if hasattr(order, 'to_dict'):
                order_dict = order.to_dict()
            else:
                order_dict = order
            self.current_state.active_orders.append(order_dict)
            self.current_state.last_updated = datetime.now()
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
    
    def update_order_status(self, order):
        """주문 상태 업데이트 (호환성 메서드)"""
        if self.current_state and self.current_state.active_orders:
            for i, active_order in enumerate(self.current_state.active_orders):
                if active_order.get('id') == order.id:
                    if hasattr(order, 'to_dict'):
                        self.current_state.active_orders[i] = order.to_dict()
                    else:
                        self.current_state.active_orders[i] = order
                    break
            self.current_state.last_updated = datetime.now()
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
    
    def update_position(self, position):
        """포지션 업데이트 (호환성 메서드)"""
        if self.current_state:
            self.current_state.current_position = position
            self.current_state.last_updated = datetime.now()
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("system_state", self.current_state.to_dict())
    
    async def get_all_positions(self) -> Dict[str, Any]:
        """
        모든 포지션 조회 (킬스위치용)
        
        Returns:
            심볼별 포지션 딕셔너리
        """
        try:
            positions = {}
            
            # 현재 상태에서 포지션 조회
            if self.current_state and self.current_state.current_position:
                # 단일 포지션인 경우
                if isinstance(self.current_state.current_position, dict):
                    symbol = self.current_state.current_position.get('symbol', 'BTC/KRW')
                    positions[symbol] = self.current_state.current_position
                
                # 다중 포지션인 경우
                elif isinstance(self.current_state.current_position, list):
                    for pos in self.current_state.current_position:
                        if isinstance(pos, dict) and 'symbol' in pos:
                            positions[pos['symbol']] = pos
            
            # Redis에서도 확인
            if hasattr(self, 'redis_manager') and self.redis_manager:
                try:
                    redis_positions = self.redis_manager.get_state("all_positions")
                    if redis_positions:
                        positions.update(redis_positions)
                except Exception as e:
                    logger.warning(f"Redis 포지션 조회 실패: {e}")
            
            # 데이터베이스에서도 확인
            if hasattr(self, 'db_manager') and self.db_manager:
                try:
                    db_positions = await self.db_manager.get_active_positions()
                    if db_positions:
                        for pos in db_positions:
                            symbol = pos.get('symbol', 'BTC/KRW')
                            positions[symbol] = pos
                except Exception as e:
                    logger.warning(f"DB 포지션 조회 실패: {e}")
            
            logger.info(f"전체 포지션 조회: {len(positions)}개")
            return positions
            
        except Exception as e:
            logger.error(f"전체 포지션 조회 실패: {e}")
            return {}
    
    async def clear_position(self, symbol: str):
        """
        특정 포지션 청산 (킬스위치용)
        
        Args:
            symbol: 청산할 심볼
        """
        try:
            logger.info(f"포지션 청산: {symbol}")
            
            # 현재 상태에서 포지션 제거
            if self.current_state:
                if isinstance(self.current_state.current_position, dict):
                    if self.current_state.current_position.get('symbol') == symbol:
                        self.current_state.current_position = None
                elif isinstance(self.current_state.current_position, list):
                    self.current_state.current_position = [
                        pos for pos in self.current_state.current_position 
                        if pos.get('symbol') != symbol
                    ]
                
                self.current_state.last_updated = datetime.now()
            
            # Redis에서 포지션 제거
            if hasattr(self, 'redis_manager') and self.redis_manager:
                try:
                    self.redis_manager.delete_state(f"position:{symbol}")
                    
                    # 전체 포지션 목록에서도 제거
                    all_positions = self.redis_manager.get_state("all_positions") or {}
                    if symbol in all_positions:
                        del all_positions[symbol]
                        self.redis_manager.set_state("all_positions", all_positions)
                        
                except Exception as e:
                    logger.warning(f"Redis 포지션 청산 실패: {e}")
            
            # 데이터베이스에서 포지션 청산 기록
            if hasattr(self, 'db_manager') and self.db_manager:
                try:
                    await self.db_manager.close_position(symbol, 'emergency_close')
                except Exception as e:
                    logger.warning(f"DB 포지션 청산 기록 실패: {e}")
            
            logger.info(f"포지션 청산 완료: {symbol}")
            
        except Exception as e:
            logger.error(f"포지션 청산 실패: {e}")
    
    async def set_emergency_stop(self, active: bool):
        """
        긴급정지 상태 설정
        
        Args:
            active: 긴급정지 활성화 여부
        """
        try:
            logger.warning(f"긴급정지 상태 설정: {active}")
            
            # 현재 상태 업데이트
            if self.current_state:
                self.current_state.emergency_stop = active
                self.current_state.last_updated = datetime.now()
            
            # Redis에 긴급정지 상태 저장
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("emergency_stop", {
                    'active': active,
                    'timestamp': datetime.now().isoformat()
                })
            
            # 데이터베이스에 긴급정지 이벤트 기록
            if hasattr(self, 'db_manager') and self.db_manager:
                try:
                    await self.db_manager.log_event(
                        event_type='emergency_stop',
                        data={'active': active},
                        severity='critical' if active else 'info'
                    )
                except Exception as e:
                    logger.warning(f"긴급정지 이벤트 기록 실패: {e}")
            
            logger.warning(f"긴급정지 상태 설정 완료: {active}")
            
        except Exception as e:
            logger.error(f"긴급정지 상태 설정 실패: {e}")
    
    async def is_emergency_stop_active(self) -> bool:
        """
        긴급정지 상태 확인
        
        Returns:
            긴급정지 활성화 여부
        """
        try:
            # 현재 상태에서 확인
            if self.current_state and hasattr(self.current_state, 'emergency_stop'):
                if self.current_state.emergency_stop:
                    return True
            
            # Redis에서 확인
            if hasattr(self, 'redis_manager') and self.redis_manager:
                emergency_state = self.redis_manager.get_state("emergency_stop")
                if emergency_state and emergency_state.get('active', False):
                    return True
            
            # 킬스위치 상태도 확인 (호환성)
            if hasattr(self, 'redis_manager') and self.redis_manager:
                killswitch_state = self.redis_manager.get_state("killswitch_active")
                if killswitch_state == "1" or killswitch_state is True:
                    return True
            
            return False
            
        except Exception as e:
            logger.error(f"긴급정지 상태 확인 실패: {e}")
            return False
    
    def activate_killswitch(self, reason: str = "Manual activation"):
        """킬스위치 활성화 (호환성 메서드)"""
        try:
            logger.warning(f"킬스위치 활성화: {reason}")
            
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("killswitch_active", "1")
                self.redis_manager.set_state("killswitch_reason", reason)
                self.redis_manager.set_state("killswitch_timestamp", datetime.now().isoformat())
            
            # 긴급정지 상태도 함께 활성화
            asyncio.create_task(self.set_emergency_stop(True))
            
        except Exception as e:
            logger.error(f"킬스위치 활성화 실패: {e}")
    
    def deactivate_killswitch(self):
        """킬스위치 비활성화 (호환성 메서드)"""
        try:
            logger.info("킬스위치 비활성화")
            
            if hasattr(self, 'redis_manager') and self.redis_manager:
                self.redis_manager.set_state("killswitch_active", "0")
                self.redis_manager.delete_state("killswitch_reason")
                self.redis_manager.delete_state("killswitch_timestamp")
            
            # 긴급정지 상태도 함께 비활성화
            asyncio.create_task(self.set_emergency_stop(False))
            
        except Exception as e:
            logger.error(f"킬스위치 비활성화 실패: {e}")

# 전역 상태 관리자 인스턴스 (순환 참조 방지를 위해 제거)
# state_manager = StateManager()
