"""
기술적 지표 계산 모듈
EMA, ATR, RSI 등 트레이딩에 필요한 기술적 지표를 계산
"""

import pandas as pd
import numpy as np
import pandas_ta as ta
from typing import Union, Optional
import logging

logger = logging.getLogger(__name__)

class TechnicalIndicators:
    """기술적 지표 계산 클래스"""
    
    def calculate_all_indicators(self, candles: list) -> dict:
        """
        모든 기술적 지표를 계산하여 반환
        
        Args:
            candles: 캔들 데이터 리스트
            
        Returns:
            계산된 지표들의 딕셔너리
        """
        try:
            # 캔들 데이터를 DataFrame으로 변환
            if not candles or len(candles) < 20:
                logger.warning("지표 계산을 위한 충분한 데이터가 없습니다")
                return {}
            
            df = pd.DataFrame(candles)
            
            # 필요한 컬럼이 있는지 확인
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in required_columns:
                if col not in df.columns:
                    logger.error(f"필수 컬럼 '{col}'이 없습니다")
                    return {}
            
            # 최신 값들 추출
            latest = df.iloc[-1]
            
            # 기본 지표들 계산
            indicators = {
                'current_price': latest['close'],
                'volume': latest['volume'],
                'high_24h': df['high'].tail(24).max() if len(df) >= 24 else latest['high'],
                'low_24h': df['low'].tail(24).min() if len(df) >= 24 else latest['low'],
            }
            
            # 이동평균 계산
            if len(df) >= 5:
                indicators['sma_5'] = self.sma(df['close'], 5).iloc[-1]
            if len(df) >= 10:
                indicators['sma_10'] = self.sma(df['close'], 10).iloc[-1]
                indicators['ema_10'] = self.ema(df['close'], 10).iloc[-1]
            if len(df) >= 20:
                indicators['sma_20'] = self.sma(df['close'], 20).iloc[-1]
                indicators['ema_20'] = self.ema(df['close'], 20).iloc[-1]
            if len(df) >= 50:
                indicators['sma_50'] = self.sma(df['close'], 50).iloc[-1]
            
            # RSI 계산
            if len(df) >= 14:
                rsi_values = self.rsi(df['close'], 14)
                if not rsi_values.empty:
                    indicators['rsi'] = rsi_values.iloc[-1]
            
            # MACD 계산
            if len(df) >= 26:
                macd_data = self.macd(df['close'])
                if not macd_data.empty and len(macd_data.columns) >= 1:
                    # MACD 데이터에서 마지막 값들 추출
                    last_row = macd_data.iloc[-1]
                    
                    # pandas_ta MACD 컬럼명: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
                    for col in macd_data.columns:
                        if 'MACD_' in col and 'h' not in col and 's' not in col:
                            indicators['macd'] = last_row[col]
                        elif 'MACDh_' in col:
                            indicators['macd_histogram'] = last_row[col]
                        elif 'MACDs_' in col:
                            indicators['macd_signal'] = last_row[col]
            
            # 볼린저 밴드 계산
            if len(df) >= 20:
                bb_data = self.bollinger_bands(df['close'], 20, 2)
                if not bb_data.empty and len(bb_data.columns) >= 3:
                    # 볼린저 밴드 데이터에서 마지막 값들 추출
                    last_row = bb_data.iloc[-1]
                    
                    # pandas_ta 볼린저 밴드 컬럼명: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
                    for col in bb_data.columns:
                        if 'BBL_' in col:  # Lower band
                            indicators['bb_lower'] = last_row[col]
                        elif 'BBM_' in col:  # Middle band
                            indicators['bb_middle'] = last_row[col]
                        elif 'BBU_' in col:  # Upper band
                            indicators['bb_upper'] = last_row[col]
                    
                    # BB 포지션 계산 (현재가가 밴드 내에서 어느 위치인지)
                    if 'bb_upper' in indicators and 'bb_lower' in indicators:
                        bb_range = indicators['bb_upper'] - indicators['bb_lower']
                        if bb_range > 0:
                            indicators['bb_position'] = (latest['close'] - indicators['bb_lower']) / bb_range
            
            # 스토캐스틱 계산
            if len(df) >= 14:
                stoch_data = self.stochastic(df)
                if not stoch_data.empty and len(stoch_data.columns) >= 1:
                    # 스토캐스틱 데이터에서 마지막 값들 추출
                    last_row = stoch_data.iloc[-1]
                    
                    # pandas_ta 스토캐스틱 컬럼명: STOCHk_14_3_3, STOCHd_14_3_3
                    for col in stoch_data.columns:
                        if 'STOCHk_' in col:
                            indicators['stoch_k'] = last_row[col]
                        elif 'STOCHd_' in col:
                            indicators['stoch_d'] = last_row[col]
            
            # 거래량 지표
            if len(df) >= 10:
                vol_sma = df['volume'].rolling(10).mean()
                if not vol_sma.empty:
                    indicators['volume_ratio'] = latest['volume'] / vol_sma.iloc[-1]
            
            # 변동성 계산
            if len(df) >= 20:
                returns = df['close'].pct_change().dropna()
                if len(returns) >= 19:
                    indicators['volatility'] = returns.tail(20).std() * np.sqrt(24)  # 일일 변동성
            
            logger.debug(f"지표 계산 완료: {len(indicators)}개 지표")
            return indicators
            
        except Exception as e:
            logger.error(f"지표 계산 중 오류: {e}")
            return {}
    
    @staticmethod
    def ema(data: Union[pd.Series, pd.DataFrame], period: int, column: str = 'close') -> pd.Series:
        """
        지수이동평균(EMA) 계산
        
        Args:
            data: 가격 데이터 (Series 또는 DataFrame)
            period: 기간
            column: DataFrame인 경우 사용할 컬럼명
            
        Returns:
            EMA 값들의 Series
        """
        try:
            if isinstance(data, pd.DataFrame):
                prices = data[column]
            else:
                prices = data
            
            ema_values = ta.ema(prices, length=period)
            return ema_values
            
        except Exception as e:
            logger.error(f"EMA 계산 실패: {e}")
            return pd.Series(dtype=float)
    
    @staticmethod
    def sma(data: Union[pd.Series, pd.DataFrame], period: int, column: str = 'close') -> pd.Series:
        """
        단순이동평균(SMA) 계산
        
        Args:
            data: 가격 데이터
            period: 기간
            column: DataFrame인 경우 사용할 컬럼명
            
        Returns:
            SMA 값들의 Series
        """
        try:
            if isinstance(data, pd.DataFrame):
                prices = data[column]
            else:
                prices = data
            
            sma_values = ta.sma(prices, length=period)
            return sma_values
            
        except Exception as e:
            logger.error(f"SMA 계산 실패: {e}")
            return pd.Series(dtype=float)
    
    @staticmethod
    def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        평균진폭(ATR) 계산
        
        Args:
            data: OHLC 데이터 (high, low, close 컬럼 필요)
            period: 기간 (기본값: 14)
            
        Returns:
            ATR 값들의 Series
        """
        try:
            required_columns = ['high', 'low', 'close']
            if not all(col in data.columns for col in required_columns):
                raise ValueError(f"ATR 계산을 위해 {required_columns} 컬럼이 필요합니다")
            
            atr_values = ta.atr(
                high=data['high'],
                low=data['low'],
                close=data['close'],
                length=period
            )
            return atr_values
            
        except Exception as e:
            logger.error(f"ATR 계산 실패: {e}")
            return pd.Series(dtype=float)
    
    @staticmethod
    def rsi(data: Union[pd.Series, pd.DataFrame], period: int = 14, column: str = 'close') -> pd.Series:
        """
        상대강도지수(RSI) 계산
        
        Args:
            data: 가격 데이터
            period: 기간 (기본값: 14)
            column: DataFrame인 경우 사용할 컬럼명
            
        Returns:
            RSI 값들의 Series
        """
        try:
            if isinstance(data, pd.DataFrame):
                prices = data[column]
            else:
                prices = data
            
            rsi_values = ta.rsi(prices, length=period)
            return rsi_values
            
        except Exception as e:
            logger.error(f"RSI 계산 실패: {e}")
            return pd.Series(dtype=float)
    
    @staticmethod
    def adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
        """
        평균방향지수(ADX) 계산 - 추세 강도 측정
        
        Args:
            data: OHLC 데이터
            period: 기간 (기본값: 14)
            
        Returns:
            ADX 값들의 Series
        """
        try:
            if not all(col in data.columns for col in ['high', 'low', 'close']):
                logger.error("ADX 계산을 위한 필수 컬럼(high, low, close)이 없습니다")
                return pd.Series(dtype=float)
            
            adx_values = ta.adx(data['high'], data['low'], data['close'], length=period)
            
            # pandas_ta는 ADX_14 형태로 반환하므로 ADX 컬럼만 추출
            if isinstance(adx_values, pd.DataFrame):
                adx_col = f'ADX_{period}'
                if adx_col in adx_values.columns:
                    return adx_values[adx_col]
                else:
                    # 첫 번째 컬럼을 ADX로 가정
                    return adx_values.iloc[:, 0]
            else:
                return adx_values
            
        except Exception as e:
            logger.error(f"ADX 계산 실패: {e}")
            return pd.Series(dtype=float)
    
    @staticmethod
    def bollinger_bands(data: Union[pd.Series, pd.DataFrame], period: int = 20, 
                       std_dev: float = 2.0, column: str = 'close') -> pd.DataFrame:
        """
        볼린저 밴드 계산
        
        Args:
            data: 가격 데이터
            period: 기간 (기본값: 20)
            std_dev: 표준편차 배수 (기본값: 2.0)
            column: DataFrame인 경우 사용할 컬럼명
            
        Returns:
            upper, middle, lower 컬럼을 가진 DataFrame
        """
        try:
            if isinstance(data, pd.DataFrame):
                prices = data[column]
            else:
                prices = data
            
            bb = ta.bbands(prices, length=period, std=std_dev)
            return bb
            
        except Exception as e:
            logger.error(f"볼린저 밴드 계산 실패: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def macd(data: Union[pd.Series, pd.DataFrame], fast: int = 12, slow: int = 26, 
             signal: int = 9, column: str = 'close') -> pd.DataFrame:
        """
        MACD 계산
        
        Args:
            data: 가격 데이터
            fast: 빠른 EMA 기간 (기본값: 12)
            slow: 느린 EMA 기간 (기본값: 26)
            signal: 시그널 라인 기간 (기본값: 9)
            column: DataFrame인 경우 사용할 컬럼명
            
        Returns:
            MACD, MACD_h, MACD_s 컬럼을 가진 DataFrame
        """
        try:
            if isinstance(data, pd.DataFrame):
                prices = data[column]
            else:
                prices = data
            
            macd_data = ta.macd(prices, fast=fast, slow=slow, signal=signal)
            return macd_data
            
        except Exception as e:
            logger.error(f"MACD 계산 실패: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def stochastic(data: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
        """
        스토캐스틱 오실레이터 계산
        
        Args:
            data: OHLC 데이터
            k_period: %K 기간 (기본값: 14)
            d_period: %D 기간 (기본값: 3)
            
        Returns:
            STOCHk, STOCHd 컬럼을 가진 DataFrame
        """
        try:
            required_columns = ['high', 'low', 'close']
            if not all(col in data.columns for col in required_columns):
                raise ValueError(f"스토캐스틱 계산을 위해 {required_columns} 컬럼이 필요합니다")
            
            stoch = ta.stoch(
                high=data['high'],
                low=data['low'],
                close=data['close'],
                k=k_period,
                d=d_period
            )
            return stoch
            
        except Exception as e:
            logger.error(f"스토캐스틱 계산 실패: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def supertrend(data: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
        """
        슈퍼트렌드 지표 계산
        
        Args:
            data: OHLC 데이터
            period: ATR 기간 (기본값: 10)
            multiplier: ATR 배수 (기본값: 3.0)
            
        Returns:
            SUPERT, SUPERTd, SUPERTl, SUPERTs 컬럼을 가진 DataFrame
        """
        try:
            required_columns = ['high', 'low', 'close']
            if not all(col in data.columns for col in required_columns):
                raise ValueError(f"슈퍼트렌드 계산을 위해 {required_columns} 컬럼이 필요합니다")
            
            supertrend = ta.supertrend(
                high=data['high'],
                low=data['low'],
                close=data['close'],
                length=period,
                multiplier=multiplier
            )
            return supertrend
            
        except Exception as e:
            logger.error(f"슈퍼트렌드 계산 실패: {e}")
            return pd.DataFrame()
    
    @staticmethod
    def chandelier_exit(data: pd.DataFrame, period: int = 22, multiplier: float = 3.0) -> pd.DataFrame:
        """
        샨들리에 엑시트 계산 (트레일링 스탑용)
        
        Args:
            data: OHLC 데이터
            period: ATR 기간 (기본값: 22)
            multiplier: ATR 배수 (기본값: 3.0)
            
        Returns:
            long_stop, short_stop 컬럼을 가진 DataFrame
        """
        try:
            required_columns = ['high', 'low', 'close']
            if not all(col in data.columns for col in required_columns):
                raise ValueError(f"샨들리에 엑시트 계산을 위해 {required_columns} 컬럼이 필요합니다")
            
            # ATR 계산
            atr_values = TechnicalIndicators.atr(data, period)
            
            # 최고가/최저가의 이동 최대/최소값
            highest_high = data['high'].rolling(window=period).max()
            lowest_low = data['low'].rolling(window=period).min()
            
            # 샨들리에 엑시트 계산
            long_stop = highest_high - (multiplier * atr_values)
            short_stop = lowest_low + (multiplier * atr_values)
            
            result = pd.DataFrame({
                'long_stop': long_stop,
                'short_stop': short_stop
            }, index=data.index)
            
            return result
            
        except Exception as e:
            logger.error(f"샨들리에 엑시트 계산 실패: {e}")
            return pd.DataFrame()

class IndicatorAnalyzer:
    """지표 분석 및 시그널 생성 클래스"""
    
    def __init__(self):
        self.indicators = TechnicalIndicators()
    
    def calculate_all_indicators(self, data: pd.DataFrame, config: dict) -> pd.DataFrame:
        """
        모든 필요한 지표를 계산하여 데이터에 추가
        
        Args:
            data: OHLCV 데이터
            config: 지표 설정 (전략 설정에서 가져옴)
            
        Returns:
            지표가 추가된 DataFrame
        """
        try:
            result = data.copy()
            
            # EMA 계산
            ema_fast = config.get('ema_fast', 20)
            ema_slow = config.get('ema_slow', 50)
            result[f'ema_{ema_fast}'] = self.indicators.ema(data, ema_fast)
            result[f'ema_{ema_slow}'] = self.indicators.ema(data, ema_slow)
            
            # ATR 계산
            atr_period = config.get('atr_len', 14)
            result['atr'] = self.indicators.atr(data, atr_period)
            
            # RSI 계산
            result['rsi'] = self.indicators.rsi(data, 14)
            
            # ADX 계산 (추세 강도 측정)
            adx_period = config.get('adx_period', 14)
            result['adx'] = self.indicators.adx(data, adx_period)
            
            # 볼린저 밴드
            bb = self.indicators.bollinger_bands(data, 20, 2.0)
            if not bb.empty:
                result = pd.concat([result, bb], axis=1)
            
            # MACD
            macd_data = self.indicators.macd(data)
            if not macd_data.empty:
                result = pd.concat([result, macd_data], axis=1)
            
            # 슈퍼트렌드
            supertrend = self.indicators.supertrend(data)
            if not supertrend.empty:
                result = pd.concat([result, supertrend], axis=1)
            
            # 샨들리에 엑시트 (트레일링 스탑용)
            trail_mult = config.get('trail_atr_mult', 3.0)
            chandelier = self.indicators.chandelier_exit(data, atr_period, trail_mult)
            if not chandelier.empty:
                result = pd.concat([result, chandelier], axis=1)
            
            logger.info(f"지표 계산 완료: {len(result.columns)}개 컬럼")
            return result
            
        except Exception as e:
            logger.error(f"지표 계산 실패: {e}")
            return data
    
    def get_trend_direction(self, data: pd.DataFrame, ema_fast_col: str, ema_slow_col: str) -> pd.Series:
        """
        추세 방향 판단 (EMA 기반)
        
        Args:
            data: 지표가 포함된 데이터
            ema_fast_col: 빠른 EMA 컬럼명
            ema_slow_col: 느린 EMA 컬럼명
            
        Returns:
            1: 상승추세, -1: 하락추세, 0: 횡보
        """
        try:
            if ema_fast_col not in data.columns or ema_slow_col not in data.columns:
                logger.warning(f"EMA 컬럼을 찾을 수 없습니다: {ema_fast_col}, {ema_slow_col}")
                return pd.Series(0, index=data.index)
            
            fast_ema = data[ema_fast_col]
            slow_ema = data[ema_slow_col]
            
            # 추세 방향 계산
            trend = pd.Series(0, index=data.index)
            trend[fast_ema > slow_ema] = 1   # 상승추세
            trend[fast_ema < slow_ema] = -1  # 하락추세
            
            return trend
            
        except Exception as e:
            logger.error(f"추세 방향 계산 실패: {e}")
            return pd.Series(0, index=data.index)
    
    def get_volatility_regime(self, data: pd.DataFrame, atr_col: str = 'atr', 
                             lookback: int = 20) -> pd.Series:
        """
        변동성 체제 판단
        
        Args:
            data: ATR이 포함된 데이터
            atr_col: ATR 컬럼명
            lookback: 변동성 비교 기간
            
        Returns:
            1: 고변동성, 0: 보통, -1: 저변동성
        """
        try:
            if atr_col not in data.columns:
                logger.warning(f"ATR 컬럼을 찾을 수 없습니다: {atr_col}")
                return pd.Series(0, index=data.index)
            
            atr = data[atr_col]
            atr_ma = atr.rolling(window=lookback).mean()
            atr_std = atr.rolling(window=lookback).std()
            
            # 변동성 체제 분류
            volatility_regime = pd.Series(0, index=data.index)
            volatility_regime[atr > atr_ma + atr_std] = 1   # 고변동성
            volatility_regime[atr < atr_ma - atr_std] = -1  # 저변동성
            
            return volatility_regime
            
        except Exception as e:
            logger.error(f"변동성 체제 계산 실패: {e}")
            return pd.Series(0, index=data.index)

# 전역 지표 분석기 인스턴스
indicator_analyzer = IndicatorAnalyzer()
