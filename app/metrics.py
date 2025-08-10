"""
Prometheus 메트릭 수집 및 노출 모듈
봇의 모든 상태와 성능 지표를 수집하고 Prometheus 형식으로 노출
"""

import logging
import time
from typing import Dict, Any, Optional
from prometheus_client import (
    Counter, Gauge, Histogram, Summary, Info, Enum,
    CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST,
    start_http_server, make_wsgi_app
)
from datetime import datetime

from .config import config

logger = logging.getLogger(__name__)

class TradingBotMetrics:
    """비트코인 자동매매 봇 메트릭 수집기"""
    
    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        메트릭 수집기 초기화
        
        Args:
            registry: 사용할 CollectorRegistry (None이면 기본 레지스트리 사용)
        """
        # registry가 None이면 기본 레지스트리 사용 (None을 전달하면 prometheus_client가 기본 레지스트리 사용)
        self.registry = registry
        self._initialize_metrics()
        
        logger.info("TradingBotMetrics 초기화 완료")
    
    def _initialize_metrics(self):
        """모든 메트릭 정의 및 초기화"""
        
        # === 기본 정보 메트릭 ===
        self.bot_info = Info(
            'trading_bot_info',
            'Trading bot build and configuration information',
            registry=self.registry
        )
        
        # 봇 상태 (running, stopped, error)
        self.bot_status = Enum(
            'trading_bot_status',
            'Current status of the trading bot',
            states=['running', 'stopped', 'error', 'initializing'],
            registry=self.registry
        )
        
        # === 잔고 관련 메트릭 ===
        self.balance_krw = Gauge(
            'account_balance_krw',
            'Current KRW balance in the account',
            registry=self.registry
        )
        
        self.balance_btc = Gauge(
            'account_balance_btc',
            'Current BTC balance in the account',
            registry=self.registry
        )
        
        self.total_balance_krw = Gauge(
            'account_total_balance_krw',
            'Total account balance in KRW (KRW + BTC converted)',
            registry=self.registry
        )
        
        # === 손익 관련 메트릭 ===
        self.profit_loss_total = Gauge(
            'profit_loss_total_krw',
            'Total profit/loss in KRW',
            registry=self.registry
        )
        
        self.daily_pnl = Gauge(
            'daily_pnl_krw',
            'Daily profit/loss in KRW',
            registry=self.registry
        )
        
        self.weekly_pnl = Gauge(
            'weekly_pnl_krw',
            'Weekly profit/loss in KRW',
            registry=self.registry
        )
        
        # R-multiple 메트릭
        self.daily_r_multiple = Gauge(
            'daily_r_multiple',
            'Daily R-multiple (risk-adjusted return)',
            registry=self.registry
        )
        
        self.weekly_r_multiple = Gauge(
            'weekly_r_multiple',
            'Weekly R-multiple (risk-adjusted return)',
            registry=self.registry
        )
        
        # === 거래 관련 메트릭 ===
        self.trades_total = Counter(
            'trades_total',
            'Total number of trades executed',
            ['side', 'status'],  # side: buy/sell, status: filled/cancelled/failed
            registry=self.registry
        )
        
        self.trade_volume_btc = Counter(
            'trade_volume_btc_total',
            'Total trading volume in BTC',
            ['side'],  # buy/sell
            registry=self.registry
        )
        
        self.trade_volume_krw = Counter(
            'trade_volume_krw_total',
            'Total trading volume in KRW',
            ['side'],  # buy/sell
            registry=self.registry
        )
        
        # === 포지션 관련 메트릭 ===
        self.current_position_size = Gauge(
            'current_position_size_btc',
            'Current position size in BTC',
            registry=self.registry
        )
        
        self.current_position_value = Gauge(
            'current_position_value_krw',
            'Current position value in KRW',
            registry=self.registry
        )
        
        self.position_unrealized_pnl = Gauge(
            'position_unrealized_pnl_krw',
            'Unrealized P&L of current position in KRW',
            registry=self.registry
        )
        
        # === 가격 관련 메트릭 ===
        self.btc_price = Gauge(
            'btc_price_krw',
            'Current BTC price in KRW',
            registry=self.registry
        )
        
        self.price_change_24h = Gauge(
            'btc_price_change_24h_percent',
            'BTC price change in last 24 hours (%)',
            registry=self.registry
        )
        
        # === 전략 관련 메트릭 ===
        self.signals_total = Counter(
            'strategy_signals_total',
            'Total number of strategy signals generated',
            ['action', 'strategy'],  # action: buy/sell/hold, strategy: trend_follow/etc
            registry=self.registry
        )
        
        self.signal_confidence = Histogram(
            'strategy_signal_confidence',
            'Distribution of strategy signal confidence scores',
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            registry=self.registry
        )
        
        # === API 및 에러 관련 메트릭 ===
        self.api_requests_total = Counter(
            'api_requests_total',
            'Total number of API requests made',
            ['endpoint', 'status'],  # endpoint: ticker/balance/order, status: success/error
            registry=self.registry
        )
        
        self.api_request_duration = Histogram(
            'api_request_duration_seconds',
            'API request duration in seconds',
            ['endpoint'],
            buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
            registry=self.registry
        )
        
        self.errors_total = Counter(
            'errors_total',
            'Total number of errors encountered',
            ['type', 'component'],  # type: api/strategy/risk, component: broker/data/etc
            registry=self.registry
        )
        
        # === 시스템 관련 메트릭 ===
        self.main_loop_duration = Histogram(
            'main_loop_duration_seconds',
            'Duration of main trading loop execution',
            buckets=[1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
            registry=self.registry
        )
        
        self.last_update_timestamp = Gauge(
            'last_update_timestamp',
            'Timestamp of last successful update',
            registry=self.registry
        )
        
        # === 리스크 관리 메트릭 ===
        self.risk_limit_breaches = Counter(
            'risk_limit_breaches_total',
            'Number of risk limit breaches',
            ['type'],  # daily/weekly/position
            registry=self.registry
        )
        
        self.stop_loss_triggers = Counter(
            'stop_loss_triggers_total',
            'Number of stop loss triggers',
            ['type'],  # initial/trailing
            registry=self.registry
        )
        
        # 초기값 설정
        self._set_initial_values()
    
    def _set_initial_values(self):
        """메트릭 초기값 설정"""
        try:
            # 봇 정보 설정
            self.bot_info.info({
                'version': '1.0.0',
                'exchange': config.exchange.get('name', 'upbit'),
                'market': config.exchange.get('market', 'BTC/KRW'),
                'strategy': config.strategy.get('main', 'trend_follow'),
                'mode': 'paper',  # 환경변수에서 가져올 수 있음
                'build_time': datetime.now().isoformat()
            })
            
            # 초기 상태 설정
            self.bot_status.state('initializing')
            
            # 초기 타임스탬프 설정
            self.last_update_timestamp.set_to_current_time()
            
            logger.info("메트릭 초기값 설정 완료")
            
        except Exception as e:
            logger.error(f"메트릭 초기값 설정 실패: {e}")
    
    # === 잔고 업데이트 메서드 ===
    def update_balance(self, krw_balance: float, btc_balance: float, btc_price: float):
        """잔고 메트릭 업데이트"""
        try:
            self.balance_krw.set(krw_balance)
            self.balance_btc.set(btc_balance)
            
            total_krw = krw_balance + (btc_balance * btc_price)
            self.total_balance_krw.set(total_krw)
            
            logger.debug(f"잔고 업데이트: KRW {krw_balance:,.0f}, BTC {btc_balance:.8f}")
            
        except Exception as e:
            logger.error(f"잔고 메트릭 업데이트 실패: {e}")
    
    def update_pnl(self, total_pnl: float, daily_pnl: float, weekly_pnl: float, 
                   daily_r: float, weekly_r: float):
        """손익 메트릭 업데이트"""
        try:
            self.profit_loss_total.set(total_pnl)
            self.daily_pnl.set(daily_pnl)
            self.weekly_pnl.set(weekly_pnl)
            self.daily_r_multiple.set(daily_r)
            self.weekly_r_multiple.set(weekly_r)
            
            logger.debug(f"손익 업데이트: 총 {total_pnl:,.0f}원, 일일 {daily_r:.2f}R")
            
        except Exception as e:
            logger.error(f"손익 메트릭 업데이트 실패: {e}")
    
    # === 거래 관련 메서드 ===
    def record_trade(self, side: str, status: str, volume_btc: float, volume_krw: float):
        """거래 기록"""
        try:
            self.trades_total.labels(side=side, status=status).inc()
            self.trade_volume_btc.labels(side=side).inc(volume_btc)
            self.trade_volume_krw.labels(side=side).inc(volume_krw)
            
            logger.debug(f"거래 기록: {side} {status} {volume_btc:.8f}BTC")
            
        except Exception as e:
            logger.error(f"거래 메트릭 기록 실패: {e}")
    
    def update_position(self, size_btc: float, value_krw: float, unrealized_pnl: float):
        """포지션 메트릭 업데이트"""
        try:
            self.current_position_size.set(size_btc)
            self.current_position_value.set(value_krw)
            self.position_unrealized_pnl.set(unrealized_pnl)
            
            logger.debug(f"포지션 업데이트: {size_btc:.8f}BTC, 평가손익 {unrealized_pnl:,.0f}원")
            
        except Exception as e:
            logger.error(f"포지션 메트릭 업데이트 실패: {e}")
    
    # === 가격 관련 메서드 ===
    def update_price(self, current_price: float, change_24h: float = 0.0):
        """가격 메트릭 업데이트"""
        try:
            self.btc_price.set(current_price)
            self.price_change_24h.set(change_24h)
            
            logger.debug(f"가격 업데이트: {current_price:,.0f}원 ({change_24h:+.2f}%)")
            
        except Exception as e:
            logger.error(f"가격 메트릭 업데이트 실패: {e}")
    
    # === 전략 관련 메서드 ===
    def record_signal(self, action: str, strategy: str, confidence: float):
        """전략 신호 기록"""
        try:
            self.signals_total.labels(action=action, strategy=strategy).inc()
            self.signal_confidence.observe(confidence)
            
            logger.debug(f"신호 기록: {action} ({strategy}, 신뢰도: {confidence:.2f})")
            
        except Exception as e:
            logger.error(f"신호 메트릭 기록 실패: {e}")
    
    # === API 관련 메서드 ===
    def record_api_request(self, endpoint: str, duration: float, success: bool = True):
        """API 요청 기록"""
        try:
            status = 'success' if success else 'error'
            self.api_requests_total.labels(endpoint=endpoint, status=status).inc()
            self.api_request_duration.labels(endpoint=endpoint).observe(duration)
            
            logger.debug(f"API 요청: {endpoint} ({duration:.3f}s, {status})")
            
        except Exception as e:
            logger.error(f"API 메트릭 기록 실패: {e}")
    
    def record_error(self, error_type: str, component: str):
        """에러 기록"""
        try:
            self.errors_total.labels(type=error_type, component=component).inc()
            
            logger.debug(f"에러 기록: {error_type} in {component}")
            
        except Exception as e:
            logger.error(f"에러 메트릭 기록 실패: {e}")
    
    # === 시스템 관련 메서드 ===
    def record_main_loop_duration(self, duration: float):
        """메인 루프 실행 시간 기록"""
        try:
            self.main_loop_duration.observe(duration)
            self.last_update_timestamp.set_to_current_time()
            
            logger.debug(f"메인 루프 실행 시간: {duration:.2f}초")
            
        except Exception as e:
            logger.error(f"메인 루프 메트릭 기록 실패: {e}")
    
    def update_bot_status(self, status: str):
        """봇 상태 업데이트"""
        try:
            if status in ['running', 'stopped', 'error', 'initializing']:
                self.bot_status.state(status)
                logger.info(f"봇 상태 변경: {status}")
            else:
                logger.warning(f"알 수 없는 봇 상태: {status}")
                
        except Exception as e:
            logger.error(f"봇 상태 업데이트 실패: {e}")
    
    # === 리스크 관리 메서드 ===
    def record_risk_breach(self, breach_type: str):
        """리스크 한도 위반 기록"""
        try:
            self.risk_limit_breaches.labels(type=breach_type).inc()
            
            logger.warning(f"리스크 한도 위반: {breach_type}")
            
        except Exception as e:
            logger.error(f"리스크 위반 메트릭 기록 실패: {e}")
    
    def record_stop_loss(self, stop_type: str):
        """스탑로스 발동 기록"""
        try:
            self.stop_loss_triggers.labels(type=stop_type).inc()
            
            logger.info(f"스탑로스 발동: {stop_type}")
            
        except Exception as e:
            logger.error(f"스탑로스 메트릭 기록 실패: {e}")
    
    # === 메트릭 노출 메서드 ===
    def get_metrics_text(self) -> str:
        """Prometheus 텍스트 형식으로 메트릭 반환"""
        try:
            if self.registry:
                return generate_latest(self.registry).decode('utf-8')
            else:
                return generate_latest().decode('utf-8')
                
        except Exception as e:
            logger.error(f"메트릭 텍스트 생성 실패: {e}")
            return f"# ERROR: {e}\n"
    
    def get_metrics_dict(self) -> Dict[str, Any]:
        """메트릭을 딕셔너리 형태로 반환 (API 응답용)"""
        try:
            return {
                'balance': {
                    'krw': self.balance_krw._value._value,
                    'btc': self.balance_btc._value._value,
                    'total_krw': self.total_balance_krw._value._value
                },
                'pnl': {
                    'total': self.profit_loss_total._value._value,
                    'daily': self.daily_pnl._value._value,
                    'weekly': self.weekly_pnl._value._value,
                    'daily_r': self.daily_r_multiple._value._value,
                    'weekly_r': self.weekly_r_multiple._value._value
                },
                'position': {
                    'size_btc': self.current_position_size._value._value,
                    'value_krw': self.current_position_value._value._value,
                    'unrealized_pnl': self.position_unrealized_pnl._value._value
                },
                'price': {
                    'btc_krw': self.btc_price._value._value,
                    'change_24h': self.price_change_24h._value._value
                },
                'system': {
                    'status': self.bot_status._value,
                    'last_update': self.last_update_timestamp._value._value
                }
            }
            
        except Exception as e:
            logger.error(f"메트릭 딕셔너리 생성 실패: {e}")
            return {'error': str(e)}

# 전역 메트릭 인스턴스
_metrics_instance: Optional[TradingBotMetrics] = None
_bot_registry: Optional[CollectorRegistry] = None

def get_bot_registry() -> CollectorRegistry:
    """봇 전용 레지스트리 반환"""
    global _bot_registry
    if _bot_registry is None:
        _bot_registry = CollectorRegistry()
    return _bot_registry

def get_metrics() -> TradingBotMetrics:
    """전역 메트릭 인스턴스 반환"""
    global _metrics_instance
    if _metrics_instance is None:
        # 봇 전용 레지스트리 사용
        _metrics_instance = TradingBotMetrics(registry=get_bot_registry())
    return _metrics_instance

def initialize_metrics(registry: Optional[CollectorRegistry] = None) -> TradingBotMetrics:
    """메트릭 시스템 초기화"""
    global _metrics_instance
    if registry is None:
        registry = get_bot_registry()
    _metrics_instance = TradingBotMetrics(registry)
    return _metrics_instance

# 편의 함수들
def record_trade(side: str, status: str, volume_btc: float, volume_krw: float):
    """거래 기록 편의 함수"""
    get_metrics().record_trade(side, status, volume_btc, volume_krw)

def update_balance(krw_balance: float, btc_balance: float, btc_price: float):
    """잔고 업데이트 편의 함수"""
    get_metrics().update_balance(krw_balance, btc_balance, btc_price)

def update_price(current_price: float, change_24h: float = 0.0):
    """가격 업데이트 편의 함수"""
    get_metrics().update_price(current_price, change_24h)

def record_signal(action: str, strategy: str, confidence: float):
    """신호 기록 편의 함수"""
    get_metrics().record_signal(action, strategy, confidence)

def record_api_request(endpoint: str, duration: float, success: bool = True):
    """API 요청 기록 편의 함수"""
    get_metrics().record_api_request(endpoint, duration, success)

def record_error(error_type: str, component: str):
    """에러 기록 편의 함수"""
    get_metrics().record_error(error_type, component)

def update_bot_status(status: str):
    """봇 상태 업데이트 편의 함수"""
    get_metrics().update_bot_status(status)
