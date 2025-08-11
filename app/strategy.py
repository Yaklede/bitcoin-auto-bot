"""
전략 엔진 모듈
추세추종, 변동성 돌파, RSI 역추세 등 다양한 트레이딩 전략을 구현
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging
from datetime import datetime

from .config import config
from .indicators import indicator_analyzer

logger = logging.getLogger(__name__)

class SignalType(Enum):
    """시그널 타입"""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE_LONG = "close_long"
    CLOSE_SHORT = "close_short"

class Signal:
    """트레이딩 시그널 클래스"""
    
    def __init__(self, signal_type: SignalType, price: float, timestamp: datetime,
                 confidence: float = 1.0, stop_loss: Optional[float] = None,
                 take_profit: Optional[float] = None, metadata: Optional[Dict] = None):
        self.signal_type = signal_type
        self.price = price
        self.timestamp = timestamp
        self.confidence = confidence  # 0.0 ~ 1.0
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.metadata = metadata or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환"""
        return {
            'signal_type': self.signal_type.value,
            'price': self.price,
            'timestamp': self.timestamp.isoformat(),
            'confidence': self.confidence,
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'metadata': self.metadata
        }

class TrendFollowingStrategy:
    """추세추종 전략 (메인 전략)"""
    
    def __init__(self, strategy_config: Dict[str, Any]):
        self.config = strategy_config.get('params', {})
        self.ema_fast = self.config.get('ema_fast', 20)
        self.ema_slow = self.config.get('ema_slow', 50)
        self.atr_len = self.config.get('atr_len', 14)
        self.init_stop_atr = self.config.get('init_stop_atr', 2.5)
        self.trail_atr_mult = self.config.get('trail_atr_mult', 3.0)
        
        # 필터 설정
        self.filters = strategy_config.get('filters', {})
        self.only_long_when_fast_gt_slow = self.filters.get('only_long_when_fast_gt_slow', True)
        self.min_volume_threshold = self.filters.get('min_volume_threshold', 1000000)
        
        logger.info(f"추세추종 전략 초기화: EMA({self.ema_fast}/{self.ema_slow}), ATR({self.atr_len})")
    
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """
        추세추종 시그널 생성
        
        Args:
            data: 지표가 포함된 OHLCV 데이터
            
        Returns:
            생성된 시그널 리스트
        """
        try:
            if len(data) < max(self.ema_fast, self.ema_slow) + 10:
                logger.warning("데이터가 부족하여 시그널 생성을 건너뜁니다")
                return []
            
            # 필요한 지표 계산
            data_with_indicators = indicator_analyzer.calculate_all_indicators(data, self.config)
            
            signals = []
            
            # 컬럼명 설정
            ema_fast_col = f'ema_{self.ema_fast}'
            ema_slow_col = f'ema_{self.ema_slow}'
            
            if ema_fast_col not in data_with_indicators.columns or ema_slow_col not in data_with_indicators.columns:
                logger.error(f"필요한 EMA 컬럼을 찾을 수 없습니다: {ema_fast_col}, {ema_slow_col}")
                return []
            
            # 최근 데이터만 분석 (마지막 100개)
            recent_data = data_with_indicators.tail(100).copy()
            
            for i in range(1, len(recent_data)):
                current_row = recent_data.iloc[i]
                prev_row = recent_data.iloc[i-1]
                
                # 기본 조건 확인
                if pd.isna(current_row[ema_fast_col]) or pd.isna(current_row[ema_slow_col]):
                    continue
                
                # 추세 확인
                current_trend = current_row[ema_fast_col] > current_row[ema_slow_col]
                prev_trend = prev_row[ema_fast_col] > prev_row[ema_slow_col]
                
                # 볼륨 필터
                if current_row['volume'] * current_row['close'] < self.min_volume_threshold:
                    continue
                
                # 매수 시그널: EMA 크로스오버 (상승)
                if not prev_trend and current_trend and self.only_long_when_fast_gt_slow:
                    # 추가 확인: 가격이 EMA 위에 있는지
                    if current_row['close'] > current_row[ema_fast_col]:
                        # 스탑로스 계산
                        atr_value = current_row.get('atr', 0)
                        stop_loss = current_row['close'] - (self.init_stop_atr * atr_value)
                        
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            price=current_row['close'],
                            timestamp=current_row.name,
                            confidence=self._calculate_confidence(current_row, 'buy'),
                            stop_loss=stop_loss,
                            metadata={
                                'strategy': 'trend_following',
                                'trigger': 'ema_crossover',
                                'ema_fast': current_row[ema_fast_col],
                                'ema_slow': current_row[ema_slow_col],
                                'atr': atr_value
                            }
                        )
                        signals.append(signal)
                        logger.info(f"추세추종 매수 시그널 생성: {current_row['close']:,.0f}원")
                
                # 매도 시그널: EMA 크로스언더 (하락)
                elif prev_trend and not current_trend:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        price=current_row['close'],
                        timestamp=current_row.name,
                        confidence=self._calculate_confidence(current_row, 'sell'),
                        metadata={
                            'strategy': 'trend_following',
                            'trigger': 'ema_crossunder',
                            'ema_fast': current_row[ema_fast_col],
                            'ema_slow': current_row[ema_slow_col]
                        }
                    )
                    signals.append(signal)
                    logger.info(f"추세추종 매도 시그널 생성: {current_row['close']:,.0f}원")
            
            return signals
            
        except Exception as e:
            logger.error(f"추세추종 시그널 생성 실패: {e}")
            return []
    
    def _calculate_confidence(self, row: pd.Series, signal_type: str) -> float:
        """
        시그널 신뢰도 계산
        
        Args:
            row: 현재 데이터 행
            signal_type: 시그널 타입 ('buy' 또는 'sell')
            
        Returns:
            신뢰도 (0.0 ~ 1.0)
        """
        try:
            confidence = 0.5  # 기본 신뢰도
            
            # RSI 기반 신뢰도 조정
            if 'rsi' in row and not pd.isna(row['rsi']):
                rsi = row['rsi']
                if signal_type == 'buy' and rsi < 70:  # 과매수 아닌 경우
                    confidence += 0.2
                elif signal_type == 'sell' and rsi > 30:  # 과매도 아닌 경우
                    confidence += 0.2
            
            # 볼륨 기반 신뢰도 조정
            if 'volume' in row:
                # 평균 볼륨 대비 현재 볼륨이 높으면 신뢰도 증가
                # (실제로는 이전 N일 평균과 비교해야 하지만 단순화)
                if row['volume'] > 0:
                    confidence += 0.1
            
            # ATR 기반 변동성 조정
            if 'atr' in row and not pd.isna(row['atr']):
                # 적당한 변동성일 때 신뢰도 증가
                atr_ratio = row['atr'] / row['close']
                if 0.01 < atr_ratio < 0.05:  # 1~5% 변동성
                    confidence += 0.1
            
            return min(confidence, 1.0)
            
        except Exception as e:
            logger.error(f"신뢰도 계산 실패: {e}")
            return 0.5
    
    def calculate_chandelier_exit(self, data: pd.DataFrame, position_entry_price: float, 
                                 position_entry_time: datetime, is_long: bool = True) -> Optional[float]:
        """
        Chandelier Exit 트레일링 스탑 계산
        
        Args:
            data: OHLCV 데이터 (지표 포함)
            position_entry_price: 포지션 진입 가격
            position_entry_time: 포지션 진입 시간
            is_long: 롱 포지션 여부
            
        Returns:
            트레일링 스탑 가격 (None이면 계산 불가)
        """
        try:
            # 포지션 진입 이후 데이터만 사용
            position_data = data[data.index >= position_entry_time].copy()
            
            if len(position_data) < 2:
                return None
            
            # 지표 계산 확인
            if 'atr' not in position_data.columns:
                position_data = indicator_analyzer.calculate_all_indicators(position_data, self.config)
            
            latest_row = position_data.iloc[-1]
            atr_value = latest_row.get('atr', 0)
            
            if atr_value <= 0:
                return None
            
            if is_long:
                # 롱 포지션: 최고가에서 ATR * 배수만큼 아래
                highest_high = position_data['high'].max()
                chandelier_exit = highest_high - (self.trail_atr_mult * atr_value)
                
                # 초기 스탑로스보다 낮아지지 않도록 제한
                initial_stop = position_entry_price - (self.init_stop_atr * atr_value)
                chandelier_exit = max(chandelier_exit, initial_stop)
                
                logger.debug(f"Chandelier Exit 계산: 최고가({highest_high:,.0f}) - ATR({atr_value:.0f}) * {self.trail_atr_mult} = {chandelier_exit:,.0f}")
                
                return chandelier_exit
            else:
                # 숏 포지션: 최저가에서 ATR * 배수만큼 위
                lowest_low = position_data['low'].min()
                chandelier_exit = lowest_low + (self.trail_atr_mult * atr_value)
                
                # 초기 스탑로스보다 높아지지 않도록 제한
                initial_stop = position_entry_price + (self.init_stop_atr * atr_value)
                chandelier_exit = min(chandelier_exit, initial_stop)
                
                return chandelier_exit
                
        except Exception as e:
            logger.error(f"Chandelier Exit 계산 실패: {e}")
            return None
    
    def should_trail_stop(self, current_price: float, current_trail_stop: float, 
                         new_trail_stop: float, is_long: bool = True) -> Tuple[bool, float]:
        """
        트레일링 스탑 업데이트 여부 결정
        
        Args:
            current_price: 현재 가격
            current_trail_stop: 현재 트레일링 스탑 가격
            new_trail_stop: 새로 계산된 트레일링 스탑 가격
            is_long: 롱 포지션 여부
            
        Returns:
            (업데이트 여부, 최종 트레일링 스탑 가격)
        """
        try:
            if is_long:
                # 롱 포지션: 트레일링 스탑은 올라가기만 함
                if new_trail_stop > current_trail_stop:
                    logger.info(f"트레일링 스탑 업데이트: {current_trail_stop:,.0f} → {new_trail_stop:,.0f}")
                    return True, new_trail_stop
                else:
                    return False, current_trail_stop
            else:
                # 숏 포지션: 트레일링 스탑은 내려가기만 함
                if new_trail_stop < current_trail_stop:
                    logger.info(f"트레일링 스탑 업데이트: {current_trail_stop:,.0f} → {new_trail_stop:,.0f}")
                    return True, new_trail_stop
                else:
                    return False, current_trail_stop
                    
        except Exception as e:
            logger.error(f"트레일링 스탑 업데이트 판단 실패: {e}")
            return False, current_trail_stop

class VolatilityBreakoutStrategy:
    """변동성 돌파 전략 (보조 전략)"""
    
    def __init__(self, strategy_config: Dict[str, Any]):
        self.config = strategy_config.get('params', {})
        self.breakout_multiplier = self.config.get('breakout_multiplier', 0.6)
        self.atr_len = self.config.get('atr_len', 14)
        self.min_volume_ratio = self.config.get('min_volume_ratio', 1.5)
        
        logger.info(f"변동성 돌파 전략 초기화: 돌파배수({self.breakout_multiplier})")
    
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """변동성 돌파 시그널 생성"""
        try:
            if len(data) < 50:
                return []
            
            # 지표 계산
            data_with_indicators = indicator_analyzer.calculate_all_indicators(data, self.config)
            
            signals = []
            recent_data = data_with_indicators.tail(50).copy()
            
            for i in range(1, len(recent_data)):
                current_row = recent_data.iloc[i]
                prev_row = recent_data.iloc[i-1]
                
                if pd.isna(current_row.get('atr')):
                    continue
                
                # 전일 범위 계산
                prev_range = prev_row['high'] - prev_row['low']
                breakout_threshold = prev_row['close'] + (self.breakout_multiplier * prev_range)
                
                # 상승 돌파 확인
                if (current_row['high'] > breakout_threshold and 
                    current_row['close'] > prev_row['close']):
                    
                    # 볼륨 확인
                    volume_ratio = current_row['volume'] / max(prev_row['volume'], 1)
                    if volume_ratio >= self.min_volume_ratio:
                        
                        atr_value = current_row['atr']
                        stop_loss = current_row['close'] - (2.0 * atr_value)
                        
                        signal = Signal(
                            signal_type=SignalType.BUY,
                            price=current_row['close'],
                            timestamp=current_row.name,
                            confidence=min(volume_ratio / 3.0, 1.0),
                            stop_loss=stop_loss,
                            metadata={
                                'strategy': 'volatility_breakout',
                                'trigger': 'upward_breakout',
                                'breakout_threshold': breakout_threshold,
                                'volume_ratio': volume_ratio
                            }
                        )
                        signals.append(signal)
                        logger.info(f"변동성 돌파 매수 시그널: {current_row['close']:,.0f}원")
            
            return signals
            
        except Exception as e:
            logger.error(f"변동성 돌파 시그널 생성 실패: {e}")
            return []

class RSIMeanReversionStrategy:
    """RSI 역추세 전략 (보조 전략)"""
    
    def __init__(self, strategy_config: Dict[str, Any]):
        self.config = strategy_config.get('params', {})
        self.rsi_oversold = self.config.get('rsi_oversold', 25)
        self.rsi_overbought = self.config.get('rsi_overbought', 75)
        self.rsi_exit = self.config.get('rsi_exit', 55)
        self.max_position_size = self.config.get('max_position_size', 0.3)  # 낮은 레버리지
        
        logger.info(f"RSI 역추세 전략 초기화: 과매도({self.rsi_oversold}), 과매수({self.rsi_overbought})")
    
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """RSI 역추세 시그널 생성"""
        try:
            if len(data) < 30:
                return []
            
            # 지표 계산
            data_with_indicators = indicator_analyzer.calculate_all_indicators(data, self.config)
            
            signals = []
            recent_data = data_with_indicators.tail(30).copy()
            
            for i in range(1, len(recent_data)):
                current_row = recent_data.iloc[i]
                
                if pd.isna(current_row.get('rsi')):
                    continue
                
                rsi = current_row['rsi']
                
                # 과매도 구간에서 매수 (분할 매수)
                if rsi < self.rsi_oversold:
                    # 추세 필터: 강한 하락추세에서는 제외
                    ema_fast_col = f"ema_{self.config.get('ema_fast', 20)}"
                    ema_slow_col = f"ema_{self.config.get('ema_slow', 50)}"
                    
                    if (ema_fast_col in current_row and ema_slow_col in current_row and
                        not pd.isna(current_row[ema_fast_col]) and not pd.isna(current_row[ema_slow_col])):
                        
                        # 너무 강한 하락추세는 제외
                        ema_ratio = current_row[ema_fast_col] / current_row[ema_slow_col]
                        if ema_ratio < 0.95:  # 5% 이상 차이나면 제외
                            continue
                    
                    atr_value = current_row.get('atr', 0)
                    stop_loss = current_row['close'] - (3.0 * atr_value)  # 넓은 스탑
                    
                    signal = Signal(
                        signal_type=SignalType.BUY,
                        price=current_row['close'],
                        timestamp=current_row.name,
                        confidence=max(0.3, (self.rsi_oversold - rsi) / self.rsi_oversold),
                        stop_loss=stop_loss,
                        metadata={
                            'strategy': 'rsi_mean_reversion',
                            'trigger': 'oversold',
                            'rsi': rsi,
                            'position_size_ratio': self.max_position_size
                        }
                    )
                    signals.append(signal)
                    logger.info(f"RSI 역추세 매수 시그널: {current_row['close']:,.0f}원 (RSI: {rsi:.1f})")
                
                # 중간 지점에서 매도
                elif rsi > self.rsi_exit:
                    signal = Signal(
                        signal_type=SignalType.SELL,
                        price=current_row['close'],
                        timestamp=current_row.name,
                        confidence=0.7,
                        metadata={
                            'strategy': 'rsi_mean_reversion',
                            'trigger': 'exit',
                            'rsi': rsi
                        }
                    )
                    signals.append(signal)
                    logger.info(f"RSI 역추세 매도 시그널: {current_row['close']:,.0f}원 (RSI: {rsi:.1f})")
            
            return signals
            
        except Exception as e:
            logger.error(f"RSI 역추세 시그널 생성 실패: {e}")
            return []

class StrategyEngine:
    """전략 엔진 - 여러 전략을 통합 관리"""
    
    def __init__(self):
        self.strategy_config = config.strategy
        self.strategies = self._initialize_strategies()
        
        logger.info(f"전략 엔진 초기화 완료: {len(self.strategies)}개 전략")
    
    def _initialize_strategies(self) -> Dict[str, Any]:
        """전략 객체들 초기화"""
        strategies = {}
        
        # 메인 전략: 추세추종
        if self.strategy_config.get('main') == 'trend_follow':
            strategies['trend_following'] = TrendFollowingStrategy(self.strategy_config)
        
        # 보조 전략들
        strategies['volatility_breakout'] = VolatilityBreakoutStrategy(self.strategy_config)
        strategies['rsi_mean_reversion'] = RSIMeanReversionStrategy(self.strategy_config)
        
        return strategies
    
    def generate_signal(self, market_data: Dict[str, Any], indicators: Dict[str, Any], current_position: Any = None) -> Optional[Dict[str, Any]]:
        """
        전략 신호 생성 (runner.py 호환성 메서드)
        
        Args:
            market_data: 시장 데이터
            indicators: 기술적 지표 데이터
            current_position: 현재 포지션 정보
            
        Returns:
            생성된 신호 정보
        """
        try:
            # 캔들 데이터에서 DataFrame 생성
            main_candles = market_data.get('candles', {}).get('1h', [])
            if not main_candles or len(main_candles) < 50:
                logger.warning("신호 생성을 위한 충분한 데이터가 없습니다")
                return None
            
            # DataFrame으로 변환
            import pandas as pd
            df = pd.DataFrame(main_candles)
            
            # 지표 데이터를 DataFrame에 추가
            for key, value in indicators.items():
                if isinstance(value, (int, float)) and not pd.isna(value):
                    df[key] = value
            
            # 통합 신호 생성
            combined_signal = self.get_combined_signal(df)
            
            if combined_signal:
                return {
                    'action': combined_signal.signal_type.value,
                    'price': combined_signal.price,
                    'confidence': combined_signal.confidence,
                    'strategy': combined_signal.metadata.get('strategy', 'combined'),
                    'timestamp': combined_signal.timestamp,
                    'metadata': combined_signal.metadata
                }
            
            return None
            
        except Exception as e:
            logger.error(f"신호 생성 실패: {e}")
            return None

    def generate_all_signals(self, data: pd.DataFrame) -> Dict[str, List[Signal]]:
        """
        모든 전략에서 시그널 생성
        
        Args:
            data: OHLCV 데이터
            
        Returns:
            전략별 시그널 딕셔너리
        """
        all_signals = {}
        
        for strategy_name, strategy in self.strategies.items():
            try:
                signals = strategy.generate_signals(data)
                all_signals[strategy_name] = signals
                logger.info(f"{strategy_name}: {len(signals)}개 시그널 생성")
                
            except Exception as e:
                logger.error(f"{strategy_name} 시그널 생성 실패: {e}")
                all_signals[strategy_name] = []
        
        return all_signals
    
    def analyze_market_condition(self, data: pd.DataFrame) -> Dict[str, Any]:
        """
        시장 상황 분석 (ADX 기반 추세/비추세 구간 판별)
        
        Args:
            data: 지표가 포함된 OHLCV 데이터
            
        Returns:
            시장 상황 분석 결과
        """
        try:
            if len(data) < 20:
                return {'condition': 'unknown', 'confidence': 0.0}
            
            latest_row = data.iloc[-1]
            
            # ADX 기반 추세 강도 분석
            adx = latest_row.get('adx', 0)
            
            # EMA 기반 추세 방향 분석
            ema_fast_col = f"ema_{self.strategy_config.get('params', {}).get('ema_fast', 20)}"
            ema_slow_col = f"ema_{self.strategy_config.get('params', {}).get('ema_slow', 50)}"
            
            trend_direction = 'neutral'
            if (ema_fast_col in latest_row and ema_slow_col in latest_row and
                not pd.isna(latest_row[ema_fast_col]) and not pd.isna(latest_row[ema_slow_col])):
                
                ema_ratio = latest_row[ema_fast_col] / latest_row[ema_slow_col]
                if ema_ratio > 1.02:  # 2% 이상 차이
                    trend_direction = 'uptrend'
                elif ema_ratio < 0.98:  # 2% 이상 차이
                    trend_direction = 'downtrend'
            
            # RSI 기반 과매수/과매도 분석
            rsi = latest_row.get('rsi', 50)
            rsi_condition = 'neutral'
            if rsi > 70:
                rsi_condition = 'overbought'
            elif rsi < 30:
                rsi_condition = 'oversold'
            
            # 시장 상황 종합 판단
            if adx > 25:  # 강한 추세
                if trend_direction == 'uptrend':
                    condition = 'strong_uptrend'
                elif trend_direction == 'downtrend':
                    condition = 'strong_downtrend'
                else:
                    condition = 'trending'
            elif adx > 15:  # 약한 추세
                condition = 'weak_trend'
            else:  # 횡보
                condition = 'sideways'
            
            # 신뢰도 계산 (ADX 값에 기반)
            confidence = min(adx / 30.0, 1.0)  # ADX 30 이상이면 신뢰도 1.0
            
            return {
                'condition': condition,
                'trend_direction': trend_direction,
                'trend_strength': adx,
                'rsi_condition': rsi_condition,
                'confidence': confidence,
                'adx': adx,
                'rsi': rsi
            }
            
        except Exception as e:
            logger.error(f"시장 상황 분석 실패: {e}")
            return {'condition': 'unknown', 'confidence': 0.0}
    
    def get_dynamic_strategy_weights(self, market_condition: Dict[str, Any]) -> Dict[str, float]:
        """
        시장 상황에 따른 동적 전략 가중치 계산
        
        Args:
            market_condition: 시장 상황 분석 결과
            
        Returns:
            전략별 가중치 (0.0 ~ 1.0)
        """
        try:
            condition = market_condition.get('condition', 'unknown')
            trend_strength = market_condition.get('trend_strength', 0)
            rsi_condition = market_condition.get('rsi_condition', 'neutral')
            
            # 기본 가중치
            weights = {
                'trend_following': 0.6,      # 기본 메인 전략
                'volatility_breakout': 0.3,  # 보조 전략
                'rsi_mean_reversion': 0.1    # 보조 전략
            }
            
            # 시장 상황별 가중치 조정
            if condition in ['strong_uptrend', 'strong_downtrend']:
                # 강한 추세: 추세추종 전략 강화
                weights['trend_following'] = 0.8
                weights['volatility_breakout'] = 0.2
                weights['rsi_mean_reversion'] = 0.0
                
            elif condition == 'weak_trend':
                # 약한 추세: 변동성 돌파 전략 강화
                weights['trend_following'] = 0.5
                weights['volatility_breakout'] = 0.4
                weights['rsi_mean_reversion'] = 0.1
                
            elif condition == 'sideways':
                # 횡보: RSI 역추세 전략 강화
                weights['trend_following'] = 0.2
                weights['volatility_breakout'] = 0.3
                weights['rsi_mean_reversion'] = 0.5
            
            # RSI 과매수/과매도 상황 고려
            if rsi_condition == 'overbought':
                # 과매수: 매수 전략 약화, 역추세 강화
                weights['trend_following'] *= 0.7
                weights['volatility_breakout'] *= 0.5
                weights['rsi_mean_reversion'] *= 1.5
                
            elif rsi_condition == 'oversold':
                # 과매도: 역추세 전략 강화
                weights['rsi_mean_reversion'] *= 1.3
            
            # 가중치 정규화
            total_weight = sum(weights.values())
            if total_weight > 0:
                weights = {k: v / total_weight for k, v in weights.items()}
            
            logger.info(f"동적 전략 가중치: {weights} (시장상황: {condition})")
            
            return weights
            
        except Exception as e:
            logger.error(f"동적 전략 가중치 계산 실패: {e}")
            return {'trend_following': 0.6, 'volatility_breakout': 0.3, 'rsi_mean_reversion': 0.1}
    def get_combined_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        통합 시그널 생성 (시장 상황 기반 동적 가중치 적용)
        
        Args:
            data: OHLCV 데이터
            
        Returns:
            최종 통합 시그널
        """
        try:
            # 시장 상황 분석
            market_condition = self.analyze_market_condition(data)
            
            # 동적 전략 가중치 계산
            strategy_weights = self.get_dynamic_strategy_weights(market_condition)
            
            # 모든 전략에서 시그널 생성
            all_signals = self.generate_all_signals(data)
            
            # 가중치 기반 시그널 선택
            best_signal = None
            best_score = 0.0
            
            for strategy_name, signals in all_signals.items():
                if not signals:
                    continue
                
                # 가장 최근 시그널 선택
                latest_signal = max(signals, key=lambda s: s.timestamp)
                
                # 시그널 점수 계산 (신뢰도 × 전략 가중치)
                strategy_weight = strategy_weights.get(strategy_name, 0.0)
                signal_score = latest_signal.confidence * strategy_weight
                
                # 시장 상황과 시그널 방향 일치성 보너스
                if market_condition.get('condition') in ['strong_uptrend', 'weak_trend']:
                    if latest_signal.signal_type == SignalType.BUY:
                        signal_score *= 1.2  # 상승 추세에서 매수 시그널 보너스
                elif market_condition.get('condition') == 'strong_downtrend':
                    if latest_signal.signal_type == SignalType.SELL:
                        signal_score *= 1.2  # 하락 추세에서 매도 시그널 보너스
                
                # 최고 점수 시그널 선택
                if signal_score > best_score and signal_score >= 0.3:  # 최소 임계값
                    best_score = signal_score
                    best_signal = latest_signal
                    
                    # 메타데이터에 시장 분석 정보 추가
                    best_signal.metadata.update({
                        'market_condition': market_condition,
                        'strategy_weights': strategy_weights,
                        'final_score': signal_score
                    })
            
            if best_signal:
                logger.info(f"통합 시그널 선택: {best_signal.metadata.get('strategy', 'unknown')} - "
                           f"{best_signal.signal_type.value} (점수: {best_score:.3f})")
            
            return best_signal
            
        except Exception as e:
            logger.error(f"통합 시그널 생성 실패: {e}")
            return None
    
    def get_strategy_status(self) -> Dict[str, Any]:
        """전략 상태 정보 반환"""
        return {
            'active_strategies': list(self.strategies.keys()),
            'main_strategy': self.strategy_config.get('main'),
            'config': self.strategy_config
        }

# 전역 전략 엔진 인스턴스
strategy_engine = StrategyEngine()
