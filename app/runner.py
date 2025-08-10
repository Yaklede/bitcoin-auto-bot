"""
비트코인 자동매매 봇 메인 실행 모듈
전체 시스템의 오케스트레이션을 담당하는 핵심 모듈
"""

import asyncio
import logging
import signal
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import threading
from functools import wraps

from .config import config, env_config
from .data import UpbitDataCollector
from .indicators import TechnicalIndicators
from .strategy import StrategyEngine
from .risk import RiskManager
from .broker import TradingBroker
from .state import StateManager, SystemState
from .api import start_api_server
from .metrics import get_metrics, update_bot_status, update_balance, update_price, record_signal, record_trade, record_error

# 로깅 설정
logging.basicConfig(
    level=getattr(logging, config.monitoring.get('log_level', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

def retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    재시도 데코레이터
    
    Args:
        max_retries: 최대 재시도 횟수
        delay: 초기 지연 시간 (초)
        backoff: 지연 시간 증가 배수
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        logger.warning(f"{func.__name__} 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}")
                        logger.warning(f"{current_delay:.1f}초 후 재시도...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"{func.__name__} 최종 실패: {e}")
                        record_error(f'{func.__name__}_retry_exhausted', 'runner')
            
            raise last_exception
        return wrapper
    return decorator

def async_retry_on_failure(max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """
    비동기 재시도 데코레이터
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        logger.warning(f"{func.__name__} 실패 (시도 {attempt + 1}/{max_retries + 1}): {e}")
                        logger.warning(f"{current_delay:.1f}초 후 재시도...")
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"{func.__name__} 최종 실패: {e}")
                        record_error(f'{func.__name__}_retry_exhausted', 'runner')
            
            raise last_exception
        return wrapper
    return decorator

class TradingBot:
    """비트코인 자동매매 봇 메인 클래스"""
    
    def __init__(self):
        self.running = False
        self.shutdown_event = threading.Event()
        
        # 컴포넌트 초기화
        self.data_collector = None
        self.indicators = None
        self.strategy_engine = None
        self.risk_manager = None
        self.broker = None
        self.state_manager = None
        self.api_server = None
        
        # 설정값
        self.update_interval = config.data.get('update_interval_seconds', 60)
        self.market = config.exchange['market']
        
        # 상태 변수
        self.last_update_time = None
        self.error_count = 0
        self.max_errors = 10
        
    def initialize(self):
        """모든 컴포넌트 초기화"""
        try:
            logger.info("=== 비트코인 자동매매 봇 초기화 시작 ===")
            
            # 메트릭 초기화
            get_metrics().update_bot_status('initializing')
            
            # 1. 데이터 수집기 초기화
            logger.info("데이터 수집기 초기화...")
            self.data_collector = UpbitDataCollector()
            
            # 2. 기술적 지표 계산기 초기화
            logger.info("기술적 지표 계산기 초기화...")
            self.indicators = TechnicalIndicators()
            
            # 3. 전략 엔진 초기화
            logger.info("전략 엔진 초기화...")
            self.strategy_engine = StrategyEngine()
            
            # 4. 리스크 관리자 초기화
            logger.info("리스크 관리자 초기화...")
            self.risk_manager = RiskManager()
            
            # 5. 브로커 초기화
            logger.info("거래 브로커 초기화...")
            self.broker = TradingBroker()
            
            # 리스크 관리자에 브로커 설정
            self.risk_manager.broker = self.broker
            
            # 6. 상태 관리자 초기화
            logger.info("상태 관리자 초기화...")
            self.state_manager = StateManager()
            
            # 상태 관리자 초기화 실행
            if not self.state_manager.initialize_state():
                raise Exception("상태 관리자 초기화 실패")
            
            # 7. 초기 상태 동기화
            logger.info("초기 상태 동기화...")
            self._sync_initial_state()
            
            # 8. API 서버 시작
            logger.info("API 서버 시작...")
            try:
                self.api_server = start_api_server(
                    bot_instance=self,
                    state_manager=self.state_manager,
                    host="0.0.0.0",
                    port=8000,
                    background=True
                )
                logger.info("API 서버 시작 완료: http://0.0.0.0:8000")
            except Exception as e:
                logger.warning(f"API 서버 시작 실패: {e}")
                # API 서버 실패는 치명적이지 않으므로 계속 진행
            
            logger.info("=== 모든 컴포넌트 초기화 완료 ===")
            
            # 봇 상태를 실행 중으로 변경
            get_metrics().update_bot_status('running')
            
        except Exception as e:
            logger.error(f"초기화 실패: {e}")
            logger.error(traceback.format_exc())
            get_metrics().update_bot_status('error')
            record_error('initialization', 'runner')
            raise
    
    def _sync_initial_state(self):
        """시작 시 초기 상태 동기화"""
        try:
            # 계좌 잔고 조회
            balance = self.data_collector.get_account_balance()
            logger.info(f"현재 잔고: KRW {balance['krw']['total']:,.0f}원, BTC {balance['btc']['total']:.8f}")
            
            # 현재 시스템 상태 확인
            current_state = self.state_manager.get_current_state()
            if current_state:
                current_position = current_state.get('current_position')
                if current_position:
                    logger.info(f"기존 포지션 발견: {current_position}")
                else:
                    logger.info("현재 포지션 없음")
                
                # 미체결 주문 확인
                active_orders = current_state.get('active_orders', [])
                if active_orders:
                    logger.info(f"미체결 주문 {len(active_orders)}개 발견")
                    for order in active_orders:
                        logger.info(f"  - {order}")
                
                # 일일/주간 손익 확인
                daily_r = current_state.get('daily_r_multiple', 0.0)
                weekly_r = current_state.get('weekly_r_multiple', 0.0)
                logger.info(f"일일 손익: {daily_r:.2f}R, 주간 손익: {weekly_r:.2f}R")
            else:
                logger.info("시스템 상태 정보 없음")
            
        except Exception as e:
            logger.error(f"초기 상태 동기화 실패: {e}")
            raise
    
    def _setup_signal_handlers(self):
        """시그널 핸들러 설정"""
        def signal_handler(signum, frame):
            logger.info(f"종료 시그널 수신: {signum}")
            self.shutdown()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    def run(self):
        """메인 실행 루프"""
        try:
            self._setup_signal_handlers()
            self.running = True
            
            logger.info("=== 비트코인 자동매매 봇 시작 ===")
            logger.info(f"업데이트 주기: {self.update_interval}초")
            logger.info(f"거래 마켓: {self.market}")
            logger.info(f"운영 모드: {env_config.get_mode()}")
            
            while self.running and not self.shutdown_event.is_set():
                try:
                    # 메인 로직 실행
                    self._execute_main_loop()
                    
                    # 에러 카운트 리셋
                    self.error_count = 0
                    
                    # 다음 업데이트까지 대기
                    if not self.shutdown_event.wait(self.update_interval):
                        continue
                    else:
                        break
                        
                except Exception as e:
                    self.error_count += 1
                    logger.error(f"메인 루프 에러 ({self.error_count}/{self.max_errors}): {e}")
                    logger.error(traceback.format_exc())
                    
                    if self.error_count >= self.max_errors:
                        logger.critical("최대 에러 횟수 초과. 봇을 종료합니다.")
                        break
                    
                    # 에러 발생 시 짧은 대기 후 재시도
                    time.sleep(10)
            
            logger.info("=== 비트코인 자동매매 봇 종료 ===")
            
        except KeyboardInterrupt:
            logger.info("사용자에 의한 종료")
        except Exception as e:
            logger.critical(f"치명적 오류: {e}")
            logger.critical(traceback.format_exc())
        finally:
            self._cleanup()
    
    def _execute_main_loop(self):
        """메인 로직 실행"""
        start_time = time.time()
        
        try:
            # 1. 킬스위치 및 손실 한도 확인
            if not self._check_safety_conditions():
                logger.warning("안전 조건 미충족. 거래 중단")
                return
            
            # 2. 최신 데이터 수집
            market_data = self._collect_market_data()
            if not market_data:
                logger.warning("시장 데이터 수집 실패")
                return
            
            # 3. 기술적 지표 계산
            indicators_data = self._calculate_indicators(market_data)
            if not indicators_data:
                logger.warning("기술적 지표 계산 실패")
                return
            
            # 4. 전략 신호 생성
            signal = self._generate_signal(market_data, indicators_data)
            
            # 5. 포지션 및 주문 관리
            self._manage_positions_and_orders(signal, market_data)
            
            # 6. 상태 업데이트
            self._update_system_state(market_data, signal)
            
            execution_time = time.time() - start_time
            logger.debug(f"메인 루프 실행 시간: {execution_time:.2f}초")
            self.last_update_time = datetime.now()
            
            # 메인 루프 실행 시간 메트릭 기록
            get_metrics().record_main_loop_duration(execution_time)
            
        except Exception as e:
            logger.error(f"메인 루프 실행 실패: {e}")
            record_error('main_loop', 'runner')
            raise
    
    def _check_safety_conditions(self) -> bool:
        """안전 조건 확인"""
        try:
            # 킬스위치 확인
            if self.state_manager.is_killswitch_active():
                logger.warning("킬스위치 활성화됨")
                return False
            
            # 일일 손실 한도 확인
            daily_r = self.state_manager.get_daily_r_multiple()
            daily_limit = config.risk.get('daily_stop_R', -2)
            if daily_r <= daily_limit:
                logger.warning(f"일일 손실 한도 초과: {daily_r:.2f}R <= {daily_limit}R")
                return False
            
            # 주간 손실 한도 확인
            weekly_r = self.state_manager.get_weekly_r_multiple()
            weekly_limit = config.risk.get('weekly_stop_R', -5)
            if weekly_r <= weekly_limit:
                logger.warning(f"주간 손실 한도 초과: {weekly_r:.2f}R <= {weekly_limit}R")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"안전 조건 확인 실패: {e}")
            return False
    
    def _collect_market_data(self) -> Optional[Dict[str, Any]]:
        """시장 데이터 수집"""
        try:
            # 현재 가격 조회
            ticker = self.data_collector.get_ticker(self.market)
            current_price = ticker['last']
            
            # 가격 메트릭 업데이트
            price_change_24h = ticker.get('change_rate', 0.0) * 100  # 24시간 변화율 (%)
            update_price(current_price, price_change_24h)
            
            # 캔들 데이터 수집
            candles = {}
            for interval in config.data['candle_intervals']:
                candle_data = self.data_collector.get_candles(self.market, interval, limit=200)
                if candle_data is not None and len(candle_data) > 0:
                    candles[interval] = candle_data
                else:
                    logger.warning(f"{interval} 캔들 데이터 수집 실패")
            
            if not candles:
                logger.error("모든 캔들 데이터 수집 실패")
                return None
            
            return {
                'current_price': current_price,
                'ticker': ticker,
                'candles': candles,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            logger.error(f"시장 데이터 수집 실패: {e}")
            return None
    
    def _calculate_indicators(self, market_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """기술적 지표 계산"""
        try:
            # 주요 캔들 데이터 (1시간) 사용
            main_candles = market_data['candles'].get('1h')
            if main_candles is None:
                logger.error("1시간 캔들 데이터 없음")
                return None
            
            # 기술적 지표 계산
            indicators = self.indicators.calculate_all_indicators(main_candles)
            
            return indicators
            
        except Exception as e:
            logger.error(f"기술적 지표 계산 실패: {e}")
            return None
    
    def _generate_signal(self, market_data: Dict[str, Any], indicators_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """전략 신호 생성"""
        try:
            # 현재 포지션 정보
            current_position = self.state_manager.get_current_position()
            
            # 전략 신호 생성
            signal = self.strategy_engine.generate_signal(
                market_data=market_data,
                indicators=indicators_data,
                current_position=current_position
            )
            
            if signal:
                logger.info(f"전략 신호: {signal['action']} (신뢰도: {signal.get('confidence', 0):.2f})")
                
                # 신호 메트릭 기록
                action = signal.get('action', 'hold')
                strategy = signal.get('strategy', 'unknown')
                confidence = signal.get('confidence', 0.0)
                record_signal(action, strategy, confidence)
            
            return signal
            
        except Exception as e:
            logger.error(f"전략 신호 생성 실패: {e}")
            record_error('signal_generation', 'strategy')
            return None
    
    def _manage_positions_and_orders(self, signal: Optional[Dict[str, Any]], market_data: Dict[str, Any]):
        """포지션 및 주문 관리"""
        try:
            current_price = market_data['current_price']
            
            # 1. 기존 주문 상태 업데이트
            self._update_order_status()
            
            # 2. 포지션 관리 (트레일링 스탑 등)
            self._manage_existing_positions(current_price)
            
            # 3. 새로운 신호 처리
            if signal and signal.get('action') != 'hold':
                self._process_new_signal(signal, market_data)
            
        except Exception as e:
            logger.error(f"포지션/주문 관리 실패: {e}")
    
    def _update_order_status(self):
        """미체결 주문 상태 업데이트"""
        try:
            active_orders = self.state_manager.get_active_orders()
            
            for order_data in active_orders:
                # 거래소에서 주문 상태 조회
                updated_order = self.broker.get_order_status(order_data['id'])
                
                if updated_order and updated_order.status != order_data['status']:
                    logger.info(f"주문 상태 변경: {order_data['id']} {order_data['status']} -> {updated_order.status}")
                    
                    # 상태 업데이트
                    self.state_manager.update_order_status(updated_order)
                    
                    # 체결된 경우 포지션 업데이트
                    if updated_order.status == 'filled':
                        self._handle_order_filled(updated_order)
            
        except Exception as e:
            logger.error(f"주문 상태 업데이트 실패: {e}")
    
    def _manage_existing_positions(self, current_price: float):
        """기존 포지션 관리 (트레일링 스탑 등)"""
        try:
            current_position = self.state_manager.get_current_position()
            
            if not current_position:
                return
            
            # 트레일링 스탑 업데이트
            updated_position = self.risk_manager.update_trailing_stop(
                current_position, current_price
            )
            
            if updated_position != current_position:
                logger.info(f"트레일링 스탑 업데이트: {updated_position['trailing_stop']}")
                self.state_manager.update_position(updated_position)
            
            # 스탑로스 체크
            if self.risk_manager.should_close_position(updated_position, current_price):
                logger.info("스탑로스 조건 충족. 포지션 청산")
                self._close_position(updated_position, "stop_loss")
            
        except Exception as e:
            logger.error(f"기존 포지션 관리 실패: {e}")
    
    def _process_new_signal(self, signal: Dict[str, Any], market_data: Dict[str, Any]):
        """새로운 신호 처리"""
        try:
            action = signal['action']
            current_price = market_data['current_price']
            current_position = self.state_manager.get_current_position()
            
            if action == 'buy' and not current_position:
                # 매수 신호 처리
                self._execute_buy_signal(signal, current_price)
                
            elif action == 'sell' and current_position:
                # 매도 신호 처리
                self._execute_sell_signal(signal, current_position, current_price)
            
        except Exception as e:
            logger.error(f"신호 처리 실패: {e}")
    
    def _execute_buy_signal(self, signal: Dict[str, Any], current_price: float):
        """매수 신호 실행"""
        try:
            # 포지션 사이즈 계산
            position_size = self.risk_manager.calculate_position_size(
                signal, current_price
            )
            
            if position_size <= 0:
                logger.warning("포지션 사이즈가 0 이하. 매수 취소")
                return
            
            # 매수 주문 실행
            order = self.broker.place_buy_order(
                amount=position_size,
                price=current_price,
                order_type='market'
            )
            
            if order:
                logger.info(f"매수 주문 실행: {order.id} ({position_size:.8f} BTC)")
                self.state_manager.add_order(order)
            
        except Exception as e:
            logger.error(f"매수 신호 실행 실패: {e}")
    
    def _execute_sell_signal(self, signal: Dict[str, Any], position: Dict[str, Any], current_price: float):
        """매도 신호 실행"""
        try:
            # 매도 주문 실행
            order = self.broker.place_sell_order(
                amount=position['amount'],
                price=current_price,
                order_type='market'
            )
            
            if order:
                logger.info(f"매도 주문 실행: {order.id} ({position['amount']:.8f} BTC)")
                self.state_manager.add_order(order)
            
        except Exception as e:
            logger.error(f"매도 신호 실행 실패: {e}")
    
    def _close_position(self, position: Dict[str, Any], reason: str):
        """포지션 강제 청산"""
        try:
            # 현재 가격 조회
            ticker = self.data_collector.get_ticker(self.market)
            current_price = ticker['last']
            
            # 매도 주문 실행
            order = self.broker.place_sell_order(
                amount=position['amount'],
                price=current_price,
                order_type='market'
            )
            
            if order:
                logger.info(f"포지션 청산: {order.id} (사유: {reason})")
                self.state_manager.add_order(order)
            
        except Exception as e:
            logger.error(f"포지션 청산 실패: {e}")
    
    def _handle_order_filled(self, order):
        """주문 체결 처리"""
        try:
            if order.side == 'buy':
                # 매수 체결 - 새 포지션 생성
                position = self.risk_manager.create_position_from_order(order)
                self.state_manager.set_current_position(position)
                logger.info(f"새 포지션 생성: {position}")
                
            elif order.side == 'sell':
                # 매도 체결 - 포지션 청산
                self.state_manager.close_current_position(order)
                logger.info("포지션 청산 완료")
            
        except Exception as e:
            logger.error(f"주문 체결 처리 실패: {e}")
    
    def _update_system_state(self, market_data: Dict[str, Any], signal: Optional[Dict[str, Any]]):
        """시스템 상태 업데이트"""
        try:
            # 현재 상태 정보 수집
            current_position = self.state_manager.get_current_position()
            active_orders = self.state_manager.get_active_orders()
            daily_pnl = self.state_manager.get_daily_pnl()
            weekly_pnl = self.state_manager.get_weekly_pnl()
            daily_r = self.state_manager.get_daily_r_multiple()
            weekly_r = self.state_manager.get_weekly_r_multiple()
            total_trades = self.state_manager.get_total_trades()
            
            # 시스템 상태 객체 생성
            system_state = SystemState(
                last_updated=datetime.now(),
                trading_active=self.running,
                current_position=current_position,
                active_orders=active_orders,
                daily_pnl=daily_pnl,
                weekly_pnl=weekly_pnl,
                daily_r_multiple=daily_r,
                weekly_r_multiple=weekly_r,
                total_trades=total_trades,
                last_price=market_data['current_price'],
                last_signal=signal
            )
            
            # 상태 저장
            self.state_manager.update_system_state(system_state)
            
        except Exception as e:
            logger.error(f"시스템 상태 업데이트 실패: {e}")
    
    def _cleanup(self):
        """정리 작업"""
        try:
            logger.info("정리 작업 시작...")
            
            # 미체결 주문 취소 (선택사항)
            # self._cancel_all_orders()
            
            # 연결 종료
            if self.state_manager:
                self.state_manager.close()
            
            logger.info("정리 작업 완료")
            
        except Exception as e:
            logger.error(f"정리 작업 실패: {e}")
    
    def shutdown(self):
        """봇 종료"""
        logger.info("봇 종료 요청됨")
        self.running = False
        self.shutdown_event.set()
        
        # 봇 상태를 중단됨으로 변경
        get_metrics().update_bot_status('stopped')
        
        # API 서버 종료
        if self.api_server:
            try:
                self.api_server.stop_server()
                logger.info("API 서버 종료됨")
            except Exception as e:
                logger.error(f"API 서버 종료 실패: {e}")
    
    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회"""
        try:
            return {
                'running': self.running,
                'last_update': self.last_update_time.isoformat() if self.last_update_time else None,
                'error_count': self.error_count,
                'system_state': self.state_manager.get_system_state().to_dict() if self.state_manager else None
            }
        except Exception as e:
            logger.error(f"상태 조회 실패: {e}")
            return {'error': str(e)}

def main():
    """메인 함수"""
    bot = TradingBot()
    
    try:
        # 초기화
        bot.initialize()
        
        # 실행
        bot.run()
        
    except Exception as e:
        logger.critical(f"봇 실행 실패: {e}")
        logger.critical(traceback.format_exc())
        sys.exit(1)

if __name__ == "__main__":
    main()
