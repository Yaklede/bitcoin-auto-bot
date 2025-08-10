"""
완전한 Upbit API 구현 모듈
Upbit 개발자 센터의 모든 API 엔드포인트를 구현
"""

import ccxt
import requests
import hashlib
import hmac
import jwt
import uuid
import time
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from urllib.parse import urlencode, unquote
import json

from .config import config, env_config

logger = logging.getLogger(__name__)

class UpbitAPI:
    """완전한 Upbit API 클래스"""
    
    def __init__(self):
        self.base_url = "https://api.upbit.com"
        self.credentials = env_config.get_upbit_credentials()
        self.access_key = self.credentials.get('api_key', '')
        self.secret_key = self.credentials.get('secret', '')
        
        # CCXT 인스턴스도 유지 (기존 호환성)
        self.exchange = None
        self._initialize_ccxt()
        
        logger.info("Upbit API 초기화 완료")
    
    def _initialize_ccxt(self):
        """CCXT 인스턴스 초기화 (기존 호환성)"""
        try:
            if self.access_key and self.secret_key:
                self.exchange = ccxt.upbit({
                    'apiKey': self.access_key,
                    'secret': self.secret_key,
                    'enableRateLimit': True,
                    'timeout': 30000,
                    'options': {
                        'adjustForTimeDifference': True,
                    }
                })
                self.exchange.load_markets()
                logger.info("CCXT Upbit 인스턴스 초기화 완료")
            else:
                logger.warning("API 키가 없어 공개 API만 사용 가능")
        except Exception as e:
            logger.error(f"CCXT 초기화 실패: {e}")
    
    def _generate_jwt_token(self, query_params: Optional[Dict] = None, method: str = 'GET') -> str:
        """JWT 토큰 생성 (Upbit 공식 문서 기준)"""
        if not self.access_key or not self.secret_key:
            raise ValueError("API 키가 설정되지 않았습니다")
        
        payload = {
            'access_key': self.access_key,
            'nonce': str(uuid.uuid4())
        }
        
        if query_params:
            # 공식 문서 기준: 모든 요청에서 동일한 방식으로 query_string 생성
            query_string = unquote(urlencode(query_params, doseq=True)).encode('utf-8')
            
            m = hashlib.sha512()
            m.update(query_string)
            query_hash = m.hexdigest()
            payload['query_hash'] = query_hash
            payload['query_hash_alg'] = 'SHA512'
        
        jwt_token = jwt.encode(payload, self.secret_key, algorithm='HS256')
        return jwt_token
    
    def _make_request(self, method: str, endpoint: str, params: Optional[Dict] = None, 
                     auth_required: bool = False) -> Dict[str, Any]:
        """HTTP 요청 실행"""
        url = f"{self.base_url}{endpoint}"
        headers = {'Accept': 'application/json'}
        
        if auth_required:
            if not self.access_key or not self.secret_key:
                raise ValueError("인증이 필요한 API입니다. API 키를 설정해주세요.")
            
            # JWT 토큰 생성
            jwt_token = self._generate_jwt_token(params, method)
            headers['Authorization'] = f'Bearer {jwt_token}'
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, headers=headers, timeout=30)
            elif method == 'POST':
                headers['Content-Type'] = 'application/json'
                response = requests.post(url, json=params, headers=headers, timeout=30)
            elif method == 'DELETE':
                headers['Content-Type'] = 'application/json'
                response = requests.delete(url, json=params, headers=headers, timeout=30)
            else:
                raise ValueError(f"지원하지 않는 HTTP 메소드: {method}")
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API 요청 실패: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"응답 내용: {e.response.text}")
            raise
    
    # ========== API 키 테스트 및 권한 확인 ==========
    
    def test_api_connection(self) -> Dict[str, Any]:
        """API 연결 및 권한 테스트"""
        try:
            # 1. 계좌 조회로 기본 권한 확인
            accounts = self.get_accounts()
            logger.info("API 키 인증 성공")
            
            # 2. 주문 가능 정보 조회로 거래 권한 확인
            try:
                order_chance = self.get_order_chance('KRW-BTC')
                logger.info("거래 권한 확인 성공")
                return {
                    'status': 'success',
                    'message': 'API 키 인증 및 거래 권한 확인 완료',
                    'accounts': len(accounts),
                    'trading_enabled': True
                }
            except Exception as e:
                logger.warning(f"거래 권한 확인 실패: {e}")
                return {
                    'status': 'partial',
                    'message': 'API 키 인증 성공, 거래 권한 없음',
                    'accounts': len(accounts),
                    'trading_enabled': False
                }
                
        except Exception as e:
            logger.error(f"API 키 테스트 실패: {e}")
            return {
                'status': 'failed',
                'message': f'API 키 인증 실패: {str(e)}',
                'accounts': 0,
                'trading_enabled': False
            }
    
    def validate_api_keys(self) -> bool:
        """API 키 유효성 검증"""
        if not self.access_key or not self.secret_key:
            logger.error("API 키가 설정되지 않았습니다")
            return False
        
        if len(self.access_key) < 20 or len(self.secret_key) < 20:
            logger.error("API 키 형식이 올바르지 않습니다")
            return False
        
        return True
    
    def get_accounts(self) -> List[Dict[str, Any]]:
        """전체 계좌 조회"""
        return self._make_request('GET', '/v1/accounts', auth_required=True)
    
    # ========== Exchange API - Orders ==========
    
    def get_order_chance(self, market: str) -> Dict[str, Any]:
        """주문 가능 정보 조회"""
        params = {'market': market}
        return self._make_request('GET', '/v1/orders/chance', params, auth_required=True)
    
    def get_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None) -> Dict[str, Any]:
        """개별 주문 조회"""
        if not uuid and not identifier:
            raise ValueError("uuid 또는 identifier 중 하나는 필수입니다")
        
        params = {}
        if uuid:
            params['uuid'] = uuid
        if identifier:
            params['identifier'] = identifier
            
        return self._make_request('GET', '/v1/order', params, auth_required=True)
    
    def get_orders(self, market: Optional[str] = None, uuids: Optional[List[str]] = None,
                   identifiers: Optional[List[str]] = None, state: Optional[str] = None,
                   states: Optional[List[str]] = None, page: int = 1, limit: int = 100,
                   order_by: str = 'desc') -> List[Dict[str, Any]]:
        """주문 리스트 조회"""
        params = {
            'page': page,
            'limit': limit,
            'order_by': order_by
        }
        
        if market:
            params['market'] = market
        if uuids:
            params['uuids'] = uuids
        if identifiers:
            params['identifiers'] = identifiers
        if state:
            params['state'] = state
        if states:
            params['states'] = states
            
        return self._make_request('GET', '/v1/orders', params, auth_required=True)
    
    def get_orders_open(self, market: Optional[str] = None, page: int = 1, 
                       limit: int = 100, order_by: str = 'desc') -> List[Dict[str, Any]]:
        """미체결 주문 조회"""
        params = {
            'page': page,
            'limit': limit,
            'order_by': order_by
        }
        if market:
            params['market'] = market
            
        return self._make_request('GET', '/v1/orders/open', params, auth_required=True)
    
    def get_orders_closed(self, market: Optional[str] = None, state: Optional[str] = None,
                         start_time: Optional[str] = None, end_time: Optional[str] = None,
                         page: int = 1, limit: int = 100, order_by: str = 'desc') -> List[Dict[str, Any]]:
        """체결 완료 주문 조회"""
        params = {
            'page': page,
            'limit': limit,
            'order_by': order_by
        }
        
        if market:
            params['market'] = market
        if state:
            params['state'] = state
        if start_time:
            params['start_time'] = start_time
        if end_time:
            params['end_time'] = end_time
            
        return self._make_request('GET', '/v1/orders/closed', params, auth_required=True)
    
    def cancel_order(self, uuid: Optional[str] = None, identifier: Optional[str] = None) -> Dict[str, Any]:
        """주문 취소"""
        if not uuid and not identifier:
            raise ValueError("uuid 또는 identifier 중 하나는 필수입니다")
        
        params = {}
        if uuid:
            params['uuid'] = uuid
        if identifier:
            params['identifier'] = identifier
            
        return self._make_request('DELETE', '/v1/order', params, auth_required=True)
    
    def cancel_orders(self, uuids: Optional[List[str]] = None, 
                     identifiers: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """일괄 주문 취소"""
        if not uuids and not identifiers:
            raise ValueError("uuids 또는 identifiers 중 하나는 필수입니다")
        
        params = {}
        if uuids:
            params['uuids'] = uuids
        if identifiers:
            params['identifiers'] = identifiers
            
        return self._make_request('DELETE', '/v1/orders', params, auth_required=True)
    
    def place_order(self, market: str, side: str, volume: Optional[str] = None,
                   price: Optional[str] = None, ord_type: str = 'limit',
                   identifier: Optional[str] = None, time_in_force: Optional[str] = None) -> Dict[str, Any]:
        """주문하기"""
        params = {
            'market': market,
            'side': side,
            'ord_type': ord_type
        }
        
        if volume:
            params['volume'] = volume
        if price:
            params['price'] = price
        if identifier:
            params['identifier'] = identifier
        if time_in_force:
            params['time_in_force'] = time_in_force
            
        return self._make_request('POST', '/v1/orders', params, auth_required=True)
    
    def place_buy_order(self, market: str, volume: Optional[str] = None, 
                       price: Optional[str] = None, ord_type: str = 'limit') -> Dict[str, Any]:
        """매수 주문"""
        return self.place_order(market, 'bid', volume, price, ord_type)
    
    def place_sell_order(self, market: str, volume: str, price: Optional[str] = None, 
                        ord_type: str = 'limit') -> Dict[str, Any]:
        """매도 주문"""
        return self.place_order(market, 'ask', volume, price, ord_type)
    
    # ========== Quotation API - Market ==========
    
    def get_markets(self, is_details: bool = False) -> List[Dict[str, Any]]:
        """마켓 코드 조회"""
        params = {'isDetails': 'true' if is_details else 'false'}
        return self._make_request('GET', '/v1/market/all', params)
    
    # ========== Quotation API - Candles ==========
    
    def get_candles_seconds(self, market: str, unit: int = 1, to: Optional[str] = None,
                           count: int = 1) -> List[Dict[str, Any]]:
        """초 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
            
        return self._make_request('GET', f'/v1/candles/seconds/{unit}', params)
    
    def get_candles_minutes(self, market: str, unit: int = 1, to: Optional[str] = None,
                           count: int = 1) -> List[Dict[str, Any]]:
        """분 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
            
        return self._make_request('GET', f'/v1/candles/minutes/{unit}', params)
    
    def get_candles_days(self, market: str, to: Optional[str] = None,
                        count: int = 1, converting_price_unit: Optional[str] = None) -> List[Dict[str, Any]]:
        """일 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
        if converting_price_unit:
            params['convertingPriceUnit'] = converting_price_unit
            
        return self._make_request('GET', '/v1/candles/days', params)
    
    def get_candles_weeks(self, market: str, to: Optional[str] = None,
                         count: int = 1) -> List[Dict[str, Any]]:
        """주 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
            
        return self._make_request('GET', '/v1/candles/weeks', params)
    
    def get_candles_months(self, market: str, to: Optional[str] = None,
                          count: int = 1) -> List[Dict[str, Any]]:
        """월 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
            
        return self._make_request('GET', '/v1/candles/months', params)
    
    def get_candles_years(self, market: str, to: Optional[str] = None,
                         count: int = 1) -> List[Dict[str, Any]]:
        """년 캔들 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
            
        return self._make_request('GET', '/v1/candles/years', params)
    
    # ========== Quotation API - Trades ==========
    
    def get_trades_ticks(self, market: str, to: Optional[str] = None, count: int = 1,
                        cursor: Optional[str] = None, days_ago: Optional[int] = None) -> List[Dict[str, Any]]:
        """최근 체결 내역 조회"""
        params = {
            'market': market,
            'count': count
        }
        if to:
            params['to'] = to
        if cursor:
            params['cursor'] = cursor
        if days_ago:
            params['daysAgo'] = days_ago
            
        return self._make_request('GET', '/v1/trades/ticks', params)
    
    # ========== Quotation API - Ticker ==========
    
    def get_ticker(self, markets: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """현재가 정보 조회"""
        if isinstance(markets, str):
            markets = [markets]
        
        params = {'markets': ','.join(markets)}
        return self._make_request('GET', '/v1/ticker', params)
    
    def get_tickers_by_quote(self, quote_currencies: Union[str, List[str]]) -> List[Dict[str, Any]]:
        """기준 통화별 현재가 조회"""
        if isinstance(quote_currencies, str):
            quote_currencies = [quote_currencies]
        
        params = {'quoteCurrencies': ','.join(quote_currencies)}
        return self._make_request('GET', '/v1/ticker/all', params)
    
    # ========== Quotation API - Orderbook ==========
    
    def get_orderbook(self, markets: Union[str, List[str]], level: Optional[int] = None) -> List[Dict[str, Any]]:
        """호가 정보 조회"""
        if isinstance(markets, str):
            markets = [markets]
        
        params = {'markets': ','.join(markets)}
        if level:
            params['level'] = level
            
        return self._make_request('GET', '/v1/orderbook', params)
    
    def get_orderbook_levels(self) -> List[Dict[str, Any]]:
        """지원 레벨 조회"""
        return self._make_request('GET', '/v1/orderbook/levels')
    
    # ========== 편의 메소드 (기존 호환성) ==========
    
    def get_account_balance(self) -> Dict[str, Any]:
        """계좌 잔고 조회 (공식 API 기준)"""
        try:
            # 공식 API를 통한 계좌 조회
            accounts = self.get_accounts()
            
            # 표준 형식으로 잔고 정보 구성
            balance = {
                'krw': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'btc': {'free': 0.0, 'used': 0.0, 'total': 0.0}
            }
            
            for account in accounts:
                currency = account['currency'].lower()
                if currency in balance:
                    account_balance = float(account['balance'])
                    locked_balance = float(account['locked'])
                    total_balance = account_balance + locked_balance
                    
                    balance[currency] = {
                        'free': account_balance,    # 사용 가능한 잔고
                        'used': locked_balance,     # 주문에 사용 중인 잔고
                        'total': total_balance      # 전체 잔고
                    }
                    
                    logger.debug(f"{currency.upper()} 잔고: 사용가능 {account_balance}, 사용중 {locked_balance}, 총 {total_balance}")
            
            balance['timestamp'] = datetime.now().isoformat()
            return balance
            
        except Exception as e:
            logger.error(f"계좌 잔고 조회 실패: {e}")
            # CCXT 백업 사용
            if self.exchange:
                try:
                    ccxt_balance = self.exchange.fetch_balance()
                    krw_balance = ccxt_balance.get('KRW', {})
                    btc_balance = ccxt_balance.get('BTC', {})
                    
                    return {
                        'krw': {
                            'free': krw_balance.get('free', 0.0),
                            'used': krw_balance.get('used', 0.0),
                            'total': krw_balance.get('total', 0.0)
                        },
                        'btc': {
                            'free': btc_balance.get('free', 0.0),
                            'used': btc_balance.get('used', 0.0),
                            'total': btc_balance.get('total', 0.0)
                        },
                        'timestamp': datetime.now().isoformat()
                    }
                except Exception as ccxt_error:
                    logger.error(f"CCXT 백업도 실패: {ccxt_error}")
            
            # 모든 방법이 실패한 경우 기본값 반환
            return {
                'krw': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'btc': {'free': 0.0, 'used': 0.0, 'total': 0.0},
                'timestamp': datetime.now().isoformat(),
                'error': str(e)
            }
    
    def get_candles(self, market: str = None, interval: str = '1m', limit: int = 200) -> List[Dict[str, Any]]:
        """캔들 데이터 조회 (기존 호환성)"""
        if not market:
            market = config.exchange.get('market', 'KRW-BTC')
        
        try:
            # 간격에 따른 API 호출
            if interval.endswith('s'):
                unit = int(interval[:-1])
                candles = self.get_candles_seconds(market, unit, count=limit)
            elif interval.endswith('m'):
                unit = int(interval[:-1])
                candles = self.get_candles_minutes(market, unit, count=limit)
            elif interval.endswith('h'):
                unit = int(interval[:-1]) * 60
                candles = self.get_candles_minutes(market, unit, count=limit)
            elif interval == '1d':
                candles = self.get_candles_days(market, count=limit)
            elif interval == '1w':
                candles = self.get_candles_weeks(market, count=limit)
            elif interval == '1M':
                candles = self.get_candles_months(market, count=limit)
            else:
                # 기본값으로 분 캔들 사용
                candles = self.get_candles_minutes(market, 1, count=limit)
            
            # 기존 형식으로 변환
            result = []
            for candle in candles:
                result.append({
                    'timestamp': int(datetime.fromisoformat(candle['candle_date_time_kst'].replace('Z', '+00:00')).timestamp() * 1000),
                    'datetime': candle['candle_date_time_kst'],
                    'open': candle['opening_price'],
                    'high': candle['high_price'],
                    'low': candle['low_price'],
                    'close': candle['trade_price'],
                    'volume': candle['candle_acc_trade_volume']
                })
            
            return result
            
        except Exception as e:
            logger.error(f"캔들 데이터 조회 실패: {e}")
            # CCXT 백업 사용
            if self.exchange:
                try:
                    timeframe_map = {
                        '1m': '1m', '5m': '5m', '15m': '15m', '30m': '30m',
                        '1h': '1h', '4h': '4h', '1d': '1d'
                    }
                    timeframe = timeframe_map.get(interval, '1m')
                    ohlcv = self.exchange.fetch_ohlcv(market, timeframe, limit=limit)
                    
                    result = []
                    for candle in ohlcv:
                        result.append({
                            'timestamp': candle[0],
                            'datetime': datetime.fromtimestamp(candle[0] / 1000).isoformat(),
                            'open': candle[1],
                            'high': candle[2],
                            'low': candle[3],
                            'close': candle[4],
                            'volume': candle[5]
                        })
                    return result
                except Exception as ccxt_error:
                    logger.error(f"CCXT 백업도 실패: {ccxt_error}")
            return []
    
    def get_current_price(self, market: str = None) -> Dict[str, Any]:
        """현재 가격 조회 (기존 호환성)"""
        if not market:
            market = config.exchange.get('market', 'KRW-BTC')
        
        try:
            tickers = self.get_ticker(market)
            if tickers:
                ticker = tickers[0]
                return {
                    'symbol': ticker['market'],
                    'last': ticker['trade_price'],
                    'bid': ticker.get('bid_price', ticker['trade_price']),
                    'ask': ticker.get('ask_price', ticker['trade_price']),
                    'high': ticker['high_price'],
                    'low': ticker['low_price'],
                    'volume': ticker['acc_trade_volume_24h'],
                    'change': ticker['change_price'],
                    'percentage': ticker['change_rate'] * 100,
                    'timestamp': int(datetime.now().timestamp() * 1000),
                    'datetime': datetime.now().isoformat()
                }
        except Exception as e:
            logger.error(f"현재 가격 조회 실패: {e}")
            # CCXT 백업 사용
            if self.exchange:
                try:
                    ticker = self.exchange.fetch_ticker(market)
                    return {
                        'symbol': ticker['symbol'],
                        'last': ticker['last'],
                        'bid': ticker['bid'],
                        'ask': ticker['ask'],
                        'high': ticker['high'],
                        'low': ticker['low'],
                        'volume': ticker['baseVolume'],
                        'change': ticker['change'],
                        'percentage': ticker['percentage'],
                        'timestamp': ticker['timestamp'],
                        'datetime': ticker['datetime']
                    }
                except Exception as ccxt_error:
                    logger.error(f"CCXT 백업도 실패: {ccxt_error}")
            raise
    
    def test_connection(self) -> bool:
        """연결 테스트"""
        try:
            # 공개 API 테스트
            markets = self.get_markets()
            if markets and len(markets) > 0:
                logger.info(f"공개 API 연결 성공: {len(markets)}개 마켓")
                
                # 인증 API 테스트 (키가 있는 경우)
                if self.access_key and self.secret_key:
                    try:
                        accounts = self.get_accounts()
                        logger.info(f"인증 API 연결 성공: {len(accounts)}개 계좌")
                    except Exception as auth_error:
                        logger.warning(f"인증 API 테스트 실패: {auth_error}")
                
                return True
            else:
                logger.error("마켓 정보를 가져올 수 없습니다")
                return False
                
        except Exception as e:
            logger.error(f"연결 테스트 실패: {e}")
            return False

# 전역 인스턴스
upbit_api = UpbitAPI()
