"""
Upbit API 연동 및 데이터 수집 모듈
완전한 Upbit API 구현과 ccxt 라이브러리를 함께 사용하여 시세 데이터를 수집
"""

import ccxt
import pandas as pd
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import time

from .config import config, env_config
from .upbit_api import upbit_api

logger = logging.getLogger(__name__)

class UpbitDataCollector:
    """Upbit 데이터 수집기 - 완전한 API 구현과 CCXT 백업 지원"""
    
    def __init__(self):
        self.api = upbit_api  # 새로운 완전한 API 사용
        self.exchange = upbit_api.exchange  # CCXT 백업용
        self.market = config.exchange['market']
        self.candle_intervals = config.data['candle_intervals']
        self.history_days = config.data['history_days']
        
        logger.info("UpbitDataCollector 초기화 완료")
    
    def _initialize_exchange(self):
        """거래소 객체 초기화 (호환성 유지)"""
        # 이미 upbit_api에서 초기화됨
        pass
    
    def get_account_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회"""
        return self.api.get_account_balance()
    
    def get_candles(self, market: str = None, interval: str = '1m', limit: int = 200) -> List[Dict[str, Any]]:
        """캔들 데이터 조회 (호환성 메서드)"""
        return self.api.get_candles(market, interval, limit)

    def get_ticker(self, market: str = None) -> Dict[str, Any]:
        """티커 데이터 조회 (호환성 메서드)"""
        return self.api.get_current_price(market)

    def get_current_price(self) -> Dict[str, Any]:
        """현재 가격 조회"""
        return self.api.get_current_price(self.market)
    
    def get_orderbook(self, limit: int = 10) -> Dict[str, Any]:
        """호가 정보 조회"""
        try:
            orderbooks = self.api.get_orderbook(self.market)
            if orderbooks:
                orderbook = orderbooks[0]
                units = orderbook['orderbook_units'][:limit]
                
                # 매수/매도 호가를 분리하여 처리
                bids = []
                asks = []
                
                for unit in units:
                    bids.append([unit['bid_price'], unit['bid_size']])
                    asks.append([unit['ask_price'], unit['ask_size']])
                
                return {
                    'symbol': self.market,
                    'bids': bids,
                    'asks': asks,
                    'timestamp': int(datetime.now().timestamp() * 1000),
                    'datetime': datetime.now().isoformat()
                }
            else:
                raise ValueError("호가 정보를 가져올 수 없습니다")
        except Exception as e:
            logger.error(f"호가 정보 조회 실패: {e}")
            # CCXT 백업 사용
            if self.exchange:
                try:
                    orderbook = self.exchange.fetch_order_book(self.market, limit)
                    return {
                        'symbol': self.market,
                        'bids': orderbook['bids'][:limit],
                        'asks': orderbook['asks'][:limit],
                        'timestamp': orderbook['timestamp'],
                        'datetime': orderbook['datetime']
                    }
                except Exception as ccxt_error:
                    logger.error(f"CCXT 백업도 실패: {ccxt_error}")
            raise
    
    def get_ohlcv_data(self, timeframe: str = '1m', limit: int = 200, 
                       since: Optional[int] = None) -> pd.DataFrame:
        """OHLCV 데이터 조회"""
        try:
            # since가 없으면 현재 시간에서 limit만큼 이전 데이터 조회
            if since is None:
                since = self.exchange.milliseconds() - (limit * self._timeframe_to_ms(timeframe))
            
            ohlcv = self.exchange.fetch_ohlcv(
                symbol=self.market,
                timeframe=timeframe,
                since=since,
                limit=limit
            )
            
            if not ohlcv:
                return pd.DataFrame()
            
            # DataFrame으로 변환
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('datetime', inplace=True)
            
            logger.info(f"{timeframe} OHLCV 데이터 {len(df)}개 조회 완료")
            return df
            
        except Exception as e:
            logger.error(f"OHLCV 데이터 조회 실패: {e}")
            raise
    
    def get_historical_data(self, timeframe: str = '1m', days: int = None) -> pd.DataFrame:
        """과거 데이터 대량 조회"""
        try:
            if days is None:
                days = self.history_days
            
            # 시작 시간 계산
            end_time = datetime.now()
            start_time = end_time - timedelta(days=days)
            since = int(start_time.timestamp() * 1000)
            
            all_data = []
            current_since = since
            
            while current_since < int(end_time.timestamp() * 1000):
                try:
                    ohlcv = self.exchange.fetch_ohlcv(
                        symbol=self.market,
                        timeframe=timeframe,
                        since=current_since,
                        limit=200  # Upbit 최대 200개
                    )
                    
                    if not ohlcv:
                        break
                    
                    all_data.extend(ohlcv)
                    
                    # 다음 요청을 위한 시간 업데이트
                    current_since = ohlcv[-1][0] + self._timeframe_to_ms(timeframe)
                    
                    # API 제한 준수를 위한 대기
                    time.sleep(0.1)
                    
                except Exception as e:
                    logger.warning(f"데이터 조회 중 오류 (since: {current_since}): {e}")
                    break
            
            if not all_data:
                return pd.DataFrame()
            
            # DataFrame으로 변환 및 중복 제거
            df = pd.DataFrame(all_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('datetime', inplace=True)
            
            logger.info(f"{timeframe} 과거 데이터 {len(df)}개 조회 완료 ({days}일)")
            return df
            
        except Exception as e:
            logger.error(f"과거 데이터 조회 실패: {e}")
            raise
    
    def get_recent_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """최근 체결 내역 조회"""
        try:
            trades = self.api.get_trades_ticks(self.market, count=limit)
            
            result = []
            for trade in trades:
                result.append({
                    'id': trade.get('sequential_id', ''),
                    'timestamp': int(datetime.fromisoformat(trade['trade_date_utc'] + 'T' + trade['trade_time_utc'] + 'Z').timestamp() * 1000),
                    'datetime': trade['trade_date_utc'] + 'T' + trade['trade_time_utc'] + 'Z',
                    'symbol': self.market,
                    'side': 'buy' if trade['ask_bid'] == 'BID' else 'sell',
                    'amount': trade['trade_volume'],
                    'price': trade['trade_price'],
                    'cost': trade['trade_price'] * trade['trade_volume']
                })
            
            return result
            
        except Exception as e:
            logger.error(f"최근 체결 내역 조회 실패: {e}")
            # CCXT 백업 사용
            if self.exchange:
                try:
                    trades = self.exchange.fetch_trades(self.market, limit=limit)
                    return [{
                        'id': trade['id'],
                        'timestamp': trade['timestamp'],
                        'datetime': trade['datetime'],
                        'symbol': trade['symbol'],
                        'side': trade['side'],
                        'amount': trade['amount'],
                        'price': trade['price'],
                        'cost': trade['cost']
                    } for trade in trades]
                except Exception as ccxt_error:
                    logger.error(f"CCXT 백업도 실패: {ccxt_error}")
            raise
    
    def _timeframe_to_ms(self, timeframe: str) -> int:
        """시간프레임을 밀리초로 변환"""
        timeframes = {
            '1m': 60 * 1000,
            '3m': 3 * 60 * 1000,
            '5m': 5 * 60 * 1000,
            '15m': 15 * 60 * 1000,
            '30m': 30 * 60 * 1000,
            '1h': 60 * 60 * 1000,
            '2h': 2 * 60 * 60 * 1000,
            '4h': 4 * 60 * 60 * 1000,
            '6h': 6 * 60 * 60 * 1000,
            '8h': 8 * 60 * 60 * 1000,
            '12h': 12 * 60 * 60 * 1000,
            '1d': 24 * 60 * 60 * 1000,
            '3d': 3 * 24 * 60 * 60 * 1000,
            '1w': 7 * 24 * 60 * 60 * 1000,
        }
        return timeframes.get(timeframe, 60 * 1000)
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        return self.api.test_connection()

class DataManager:
    """데이터 관리자 - 수집된 데이터를 관리하고 캐싱"""
    
    def __init__(self):
        self.collector = UpbitDataCollector()
        self._cache = {}
        self._cache_timeout = 60  # 1분 캐시
    
    def get_latest_data(self, timeframe: str = '1m', use_cache: bool = True) -> pd.DataFrame:
        """최신 데이터 조회 (캐싱 지원)"""
        cache_key = f"ohlcv_{timeframe}"
        
        if use_cache and cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if time.time() - cached_time < self._cache_timeout:
                return cached_data
        
        # 새 데이터 조회
        data = self.collector.get_ohlcv_data(timeframe=timeframe, limit=200)
        
        # 캐시 업데이트
        self._cache[cache_key] = (data, time.time())
        
        return data
    
    def get_market_data(self) -> Dict[str, Any]:
        """종합 마켓 데이터 조회"""
        try:
            return {
                'price': self.collector.get_current_price(),
                'orderbook': self.collector.get_orderbook(),
                'balance': self.collector.get_account_balance(),
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"마켓 데이터 조회 실패: {e}")
            raise
    
    def clear_cache(self):
        """캐시 초기화"""
        self._cache.clear()
        logger.info("데이터 캐시 초기화 완료")

# 전역 데이터 관리자 인스턴스
data_manager = DataManager()
