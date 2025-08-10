"""
FastAPI 기반 REST API 서버
봇의 상태 조회, 제어, 메트릭 노출을 위한 HTTP 인터페이스 제공
"""

import asyncio
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

from .config import config
from .metrics import get_metrics, TradingBotMetrics
from .state import StateManager

logger = logging.getLogger(__name__)

# === Pydantic 모델 정의 ===

class HealthResponse(BaseModel):
    """헬스체크 응답 모델"""
    status: str
    timestamp: str
    uptime_seconds: float
    version: str = "1.0.0"

class StatusResponse(BaseModel):
    """봇 상태 응답 모델"""
    bot_status: str
    trading_active: bool
    last_update: Optional[str]
    current_position: Optional[Dict[str, Any]]
    active_orders: List[Dict[str, Any]]
    balance: Dict[str, float]
    pnl: Dict[str, float]
    price: Dict[str, float]
    system_info: Dict[str, Any]

class KillswitchRequest(BaseModel):
    """킬스위치 요청 모델"""
    reason: str = "Manual killswitch activation"
    force: bool = False

class KillswitchResponse(BaseModel):
    """킬스위치 응답 모델"""
    success: bool
    message: str
    timestamp: str

class ErrorResponse(BaseModel):
    """에러 응답 모델"""
    error: str
    detail: str
    timestamp: str

# === API 서버 클래스 ===

class TradingBotAPI:
    """비트코인 자동매매 봇 API 서버"""
    
    def __init__(self, bot_instance=None, state_manager: Optional[StateManager] = None):
        """
        API 서버 초기화
        
        Args:
            bot_instance: TradingBot 인스턴스 (runner.py의 TradingBot)
            state_manager: StateManager 인스턴스
        """
        self.bot_instance = bot_instance
        self.state_manager = state_manager
        self.metrics = get_metrics()
        self.start_time = time.time()
        
        # FastAPI 앱 생성
        self.app = self._create_app()
        
        # 서버 상태
        self.server = None
        self.server_thread = None
        self.running = False
        
        logger.info("TradingBotAPI 초기화 완료")
    
    def _create_app(self) -> FastAPI:
        """FastAPI 앱 생성 및 라우트 설정"""
        
        @asynccontextmanager
        async def lifespan(app: FastAPI):
            """앱 생명주기 관리"""
            logger.info("API 서버 시작")
            yield
            logger.info("API 서버 종료")
        
        app = FastAPI(
            title="Bitcoin Trading Bot API",
            description="비트코인 자동매매 봇 모니터링 및 제어 API",
            version="1.0.0",
            lifespan=lifespan
        )
        
        # 라우트 등록
        self._register_routes(app)
        
        return app
    
    def _register_routes(self, app: FastAPI):
        """API 라우트 등록"""
        
        @app.get("/", response_model=Dict[str, str])
        async def root():
            """루트 엔드포인트"""
            return {
                "message": "Bitcoin Trading Bot API",
                "version": "1.0.0",
                "docs": "/docs",
                "health": "/healthz",
                "status": "/status",
                "metrics": "/metrics"
            }
        
        @app.get("/healthz", response_model=HealthResponse)
        async def health_check():
            """헬스체크 엔드포인트"""
            try:
                uptime = time.time() - self.start_time
                
                # 기본 헬스체크
                health_status = "healthy"
                
                # 봇 인스턴스가 있으면 상태 확인
                if self.bot_instance:
                    if hasattr(self.bot_instance, 'running') and not self.bot_instance.running:
                        health_status = "stopped"
                    elif hasattr(self.bot_instance, 'error_count') and self.bot_instance.error_count > 5:
                        health_status = "degraded"
                
                return HealthResponse(
                    status=health_status,
                    timestamp=datetime.now().isoformat(),
                    uptime_seconds=uptime
                )
                
            except Exception as e:
                logger.error(f"헬스체크 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Health check failed: {e}")
        
        @app.get("/status", response_model=StatusResponse)
        async def get_status():
            """봇 상태 조회 엔드포인트"""
            try:
                # 기본 상태 정보
                bot_status = "unknown"
                trading_active = False
                last_update = None
                
                if self.bot_instance:
                    if hasattr(self.bot_instance, 'running'):
                        bot_status = "running" if self.bot_instance.running else "stopped"
                        trading_active = self.bot_instance.running
                    
                    if hasattr(self.bot_instance, 'last_update_time') and self.bot_instance.last_update_time:
                        last_update = self.bot_instance.last_update_time.isoformat()
                
                # 상태 관리자에서 정보 수집
                current_position = None
                active_orders = []
                
                if self.state_manager:
                    try:
                        current_position = self.state_manager.get_current_position()
                        active_orders = self.state_manager.get_active_orders()
                    except Exception as e:
                        logger.warning(f"상태 정보 조회 실패: {e}")
                
                # 메트릭에서 정보 수집
                metrics_data = self.metrics.get_metrics_dict()
                
                return StatusResponse(
                    bot_status=bot_status,
                    trading_active=trading_active,
                    last_update=last_update,
                    current_position=current_position,
                    active_orders=active_orders,
                    balance=metrics_data.get('balance', {}),
                    pnl=metrics_data.get('pnl', {}),
                    price=metrics_data.get('price', {}),
                    system_info=metrics_data.get('system', {})
                )
                
            except Exception as e:
                logger.error(f"상태 조회 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Status retrieval failed: {e}")
        
        @app.get("/metrics", response_class=PlainTextResponse)
        async def get_metrics_endpoint():
            """Prometheus 메트릭 노출 엔드포인트"""
            try:
                metrics_text = self.metrics.get_metrics_text()
                return Response(
                    content=metrics_text,
                    media_type="text/plain; version=0.0.4; charset=utf-8"
                )
                
            except Exception as e:
                logger.error(f"메트릭 조회 실패: {e}")
                return Response(
                    content=f"# ERROR: {e}\n",
                    media_type="text/plain",
                    status_code=500
                )
        
        @app.post("/killswitch", response_model=KillswitchResponse)
        async def activate_killswitch(request: KillswitchRequest, background_tasks: BackgroundTasks):
            """킬스위치 활성화 엔드포인트"""
            try:
                timestamp = datetime.now().isoformat()
                
                # 상태 관리자에 킬스위치 설정
                if self.state_manager:
                    self.state_manager.activate_killswitch(request.reason)
                    logger.warning(f"킬스위치 활성화: {request.reason}")
                
                # 봇 인스턴스가 있으면 즉시 중단
                if self.bot_instance and request.force:
                    background_tasks.add_task(self._force_stop_bot)
                    message = f"Killswitch activated and bot force stopped: {request.reason}"
                else:
                    message = f"Killswitch activated: {request.reason}"
                
                # 메트릭 기록
                self.metrics.record_error("killswitch", "api")
                self.metrics.update_bot_status("stopped")
                
                return KillswitchResponse(
                    success=True,
                    message=message,
                    timestamp=timestamp
                )
                
            except Exception as e:
                logger.error(f"킬스위치 활성화 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Killswitch activation failed: {e}")
        
        @app.delete("/killswitch", response_model=KillswitchResponse)
        async def deactivate_killswitch():
            """킬스위치 비활성화 엔드포인트"""
            try:
                timestamp = datetime.now().isoformat()
                
                # 상태 관리자에서 킬스위치 해제
                if self.state_manager:
                    self.state_manager.deactivate_killswitch()
                    logger.info("킬스위치 비활성화")
                
                # 메트릭 상태를 running으로 복구
                if hasattr(self, 'metrics') and self.metrics:
                    self.metrics.update_bot_status('running')
                    logger.info("봇 상태 메트릭을 running으로 복구")
                
                return KillswitchResponse(
                    success=True,
                    message="Killswitch deactivated",
                    timestamp=timestamp
                )
                
            except Exception as e:
                logger.error(f"킬스위치 비활성화 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Killswitch deactivation failed: {e}")
        
        @app.get("/positions", response_model=Dict[str, Any])
        async def get_positions():
            """현재 포지션 조회 엔드포인트"""
            try:
                if not self.state_manager:
                    raise HTTPException(status_code=503, detail="State manager not available")
                
                current_position = self.state_manager.get_current_position()
                
                return {
                    "current_position": current_position,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"포지션 조회 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Position retrieval failed: {e}")
        
        @app.get("/orders", response_model=Dict[str, Any])
        async def get_orders():
            """활성 주문 조회 엔드포인트"""
            try:
                if not self.state_manager:
                    raise HTTPException(status_code=503, detail="State manager not available")
                
                active_orders = self.state_manager.get_active_orders()
                
                return {
                    "active_orders": active_orders,
                    "count": len(active_orders),
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"주문 조회 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Orders retrieval failed: {e}")
        
        @app.get("/pnl", response_model=Dict[str, Any])
        async def get_pnl():
            """손익 정보 조회 엔드포인트"""
            try:
                if not self.state_manager:
                    raise HTTPException(status_code=503, detail="State manager not available")
                
                daily_pnl = self.state_manager.get_daily_pnl()
                weekly_pnl = self.state_manager.get_weekly_pnl()
                daily_r = self.state_manager.get_daily_r_multiple()
                weekly_r = self.state_manager.get_weekly_r_multiple()
                
                return {
                    "daily_pnl": daily_pnl,
                    "weekly_pnl": weekly_pnl,
                    "daily_r_multiple": daily_r,
                    "weekly_r_multiple": weekly_r,
                    "risk_limits": {
                        "daily_limit": config.risk.get('daily_stop_R', -2),
                        "weekly_limit": config.risk.get('weekly_stop_R', -5)
                    },
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"손익 조회 실패: {e}")
                raise HTTPException(status_code=500, detail=f"P&L retrieval failed: {e}")
        
        @app.get("/config", response_model=Dict[str, Any])
        async def get_config():
            """봇 설정 조회 엔드포인트"""
            try:
                # 민감한 정보 제외하고 설정 반환
                safe_config = {
                    "exchange": {
                        "name": config.exchange.get('name'),
                        "market": config.exchange.get('market'),
                        "taker_fee_bps": config.exchange.get('taker_fee_bps'),
                        "slippage_bps": config.exchange.get('slippage_bps')
                    },
                    "risk": config.risk,
                    "strategy": config.strategy,
                    "data": config.data,
                    "monitoring": {
                        "metrics_port": config.monitoring.get('metrics_port'),
                        "log_level": config.monitoring.get('log_level')
                    }
                }
                
                return {
                    "config": safe_config,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as e:
                logger.error(f"설정 조회 실패: {e}")
                raise HTTPException(status_code=500, detail=f"Config retrieval failed: {e}")
        
        # 에러 핸들러
        @app.exception_handler(HTTPException)
        async def http_exception_handler(request, exc):
            """HTTP 예외 핸들러"""
            return JSONResponse(
                status_code=exc.status_code,
                content=ErrorResponse(
                    error=f"HTTP {exc.status_code}",
                    detail=str(exc.detail),
                    timestamp=datetime.now().isoformat()
                ).dict()
            )
        
        @app.exception_handler(Exception)
        async def general_exception_handler(request, exc):
            """일반 예외 핸들러"""
            logger.error(f"API 예외 발생: {exc}")
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    error="Internal Server Error",
                    detail=str(exc),
                    timestamp=datetime.now().isoformat()
                ).dict()
            )
    
    async def _force_stop_bot(self):
        """봇 강제 중단 및 포지션 즉시청산 (백그라운드 태스크)"""
        try:
            logger.warning("킬스위치 활성화: 즉시청산 및 봇 중단 시작")
            
            # 1. 현재 포지션 확인 및 즉시청산
            if self.state_manager:
                try:
                    current_positions = await self.state_manager.get_all_positions()
                    
                    if current_positions:
                        logger.warning(f"즉시청산 대상 포지션: {len(current_positions)}개")
                        
                        # 브로커 인스턴스 확인
                        if hasattr(self.bot_instance, 'broker') and self.bot_instance.broker:
                            broker = self.bot_instance.broker
                            
                            for symbol, position in current_positions.items():
                                if position.get('size', 0) != 0:
                                    try:
                                        # 시장가 매도 주문으로 즉시청산
                                        size = abs(position['size'])
                                        side = 'sell' if position['size'] > 0 else 'buy'
                                        
                                        logger.warning(f"긴급청산 주문: {symbol} {side} {size}")
                                        
                                        order_result = await broker.create_market_order(
                                            symbol=symbol,
                                            side=side,
                                            amount=size,
                                            emergency=True  # 긴급 주문 플래그
                                        )
                                        
                                        if order_result:
                                            logger.info(f"긴급청산 성공: {symbol} - {order_result.get('id', 'N/A')}")
                                            
                                            # 포지션 상태 즉시 업데이트
                                            await self.state_manager.clear_position(symbol)
                                            
                                            # 메트릭 기록
                                            self.metrics.record_trade(
                                                symbol=symbol,
                                                side=side,
                                                amount=size,
                                                price=order_result.get('price', 0),
                                                status='emergency_close'
                                            )
                                        else:
                                            logger.error(f"긴급청산 실패: {symbol}")
                                            
                                    except Exception as e:
                                        logger.error(f"포지션 {symbol} 긴급청산 중 오류: {e}")
                                        
                        else:
                            logger.error("브로커 인스턴스를 찾을 수 없어 긴급청산 불가")
                    else:
                        logger.info("청산할 포지션이 없습니다")
                        
                except Exception as e:
                    logger.error(f"포지션 조회 및 청산 중 오류: {e}")
            
            # 2. 모든 미체결 주문 취소
            try:
                if hasattr(self.bot_instance, 'broker') and self.bot_instance.broker:
                    broker = self.bot_instance.broker
                    open_orders = await broker.get_open_orders()
                    
                    if open_orders:
                        logger.warning(f"미체결 주문 취소: {len(open_orders)}개")
                        
                        for order in open_orders:
                            try:
                                cancel_result = await broker.cancel_order(order['id'], order['symbol'])
                                if cancel_result:
                                    logger.info(f"주문 취소 성공: {order['id']}")
                                else:
                                    logger.error(f"주문 취소 실패: {order['id']}")
                            except Exception as e:
                                logger.error(f"주문 {order['id']} 취소 중 오류: {e}")
                                
            except Exception as e:
                logger.error(f"미체결 주문 취소 중 오류: {e}")
            
            # 3. 봇 인스턴스 중단
            if self.bot_instance and hasattr(self.bot_instance, 'shutdown'):
                logger.warning("봇 인스턴스 중단 실행")
                self.bot_instance.shutdown()
                
                # 잠시 대기 후 상태 확인
                await asyncio.sleep(3)
                
                if hasattr(self.bot_instance, 'running') and self.bot_instance.running:
                    logger.error("봇이 정상적으로 중단되지 않음")
                else:
                    logger.info("봇 중단 완료")
            
            # 4. 최종 상태 업데이트
            if self.state_manager:
                await self.state_manager.set_emergency_stop(True)
                
            logger.warning("킬스위치 긴급중단 절차 완료")
                    
        except Exception as e:
            logger.error(f"킬스위치 긴급중단 실패: {e}")
            # 긴급상황이므로 메트릭에도 기록
            if hasattr(self, 'metrics'):
                self.metrics.record_error("killswitch_emergency_stop", str(e))
    
    def start_server(self, host: str = "0.0.0.0", port: int = None, background: bool = True):
        """API 서버 시작"""
        try:
            if port is None:
                port = config.monitoring.get('metrics_port', 8000)
            
            if background:
                # 백그라운드 스레드에서 서버 실행
                self.server_thread = threading.Thread(
                    target=self._run_server,
                    args=(host, port),
                    daemon=True
                )
                self.server_thread.start()
                logger.info(f"API 서버 백그라운드 시작: http://{host}:{port}")
            else:
                # 메인 스레드에서 서버 실행
                self._run_server(host, port)
                
        except Exception as e:
            logger.error(f"API 서버 시작 실패: {e}")
            raise
    
    def _run_server(self, host: str, port: int):
        """서버 실행 (내부 메서드)"""
        try:
            self.running = True
            uvicorn.run(
                self.app,
                host=host,
                port=port,
                log_level="info",
                access_log=False  # 액세스 로그 비활성화 (성능상 이유)
            )
        except Exception as e:
            logger.error(f"서버 실행 중 오류: {e}")
        finally:
            self.running = False
    
    def stop_server(self):
        """API 서버 중단"""
        try:
            self.running = False
            
            if self.server:
                self.server.shutdown()
                logger.info("API 서버 중단됨")
            
            if self.server_thread and self.server_thread.is_alive():
                self.server_thread.join(timeout=5)
                logger.info("API 서버 스레드 종료됨")
                
        except Exception as e:
            logger.error(f"API 서버 중단 실패: {e}")
    
    def is_running(self) -> bool:
        """서버 실행 상태 확인"""
        return self.running

# === 편의 함수 ===

def create_api_server(bot_instance=None, state_manager: Optional[StateManager] = None) -> TradingBotAPI:
    """API 서버 생성 편의 함수"""
    return TradingBotAPI(bot_instance=bot_instance, state_manager=state_manager)

def start_api_server(bot_instance=None, state_manager: Optional[StateManager] = None, 
                    host: str = "0.0.0.0", port: int = None, background: bool = True) -> TradingBotAPI:
    """API 서버 시작 편의 함수"""
    api_server = create_api_server(bot_instance, state_manager)
    api_server.start_server(host, port, background)
    return api_server

# === 메인 실행 (테스트용) ===

if __name__ == "__main__":
    # 테스트용 서버 실행
    logging.basicConfig(level=logging.INFO)
    
    api = TradingBotAPI()
    
    try:
        logger.info("테스트 API 서버 시작...")
        api.start_server(background=False)
    except KeyboardInterrupt:
        logger.info("서버 중단됨")
    except Exception as e:
        logger.error(f"서버 실행 실패: {e}")
    finally:
        api.stop_server()
