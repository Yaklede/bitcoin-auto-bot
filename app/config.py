"""
설정 관리 모듈
YAML 설정 파일과 환경 변수를 로드하고 관리
"""

import os
import yaml
from typing import Dict, Any
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

class Config:
    """설정 관리 클래스"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self._config = self._load_config()
        
    def _load_config(self) -> Dict[str, Any]:
        """YAML 설정 파일 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {self.config_path}")
        except yaml.YAMLError as e:
            raise ValueError(f"YAML 파일 파싱 오류: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """중첩된 키로 설정값 가져오기 (예: 'exchange.name')"""
        keys = key.split('.')
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    @property
    def exchange(self) -> Dict[str, Any]:
        """거래소 설정"""
        return self._config.get('exchange', {})
    
    @property
    def risk(self) -> Dict[str, Any]:
        """리스크 관리 설정"""
        return self._config.get('risk', {})
    
    @property
    def strategy(self) -> Dict[str, Any]:
        """전략 설정"""
        return self._config.get('strategy', {})
    
    @property
    def data(self) -> Dict[str, Any]:
        """데이터 수집 설정"""
        return self._config.get('data', {})
    
    @property
    def monitoring(self) -> Dict[str, Any]:
        """모니터링 설정"""
        return self._config.get('monitoring', {})
    
    @property
    def backtest(self) -> Dict[str, Any]:
        """백테스트 설정"""
        return self._config.get('backtest', {})

class EnvConfig:
    """환경 변수 관리 클래스"""
    
    @staticmethod
    def get_upbit_credentials() -> Dict[str, str]:
        """Upbit API 인증 정보"""
        return {
            'api_key': os.getenv('UPBIT_API_KEY', ''),
            'secret': os.getenv('UPBIT_SECRET', '')
        }
    
    @staticmethod
    def get_database_config() -> Dict[str, str]:
        """데이터베이스 설정"""
        return {
            'host': os.getenv('PG_HOST', 'localhost'),
            'database': os.getenv('PG_DB', 'btc_bot'),
            'user': os.getenv('PG_USER', 'btc_user'),
            'password': os.getenv('PG_PASSWORD', '')
        }
    
    @staticmethod
    def get_redis_config() -> str:
        """Redis 설정"""
        return os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    @staticmethod
    def get_mode() -> str:
        """운영 모드 (paper/live)"""
        return os.getenv('MODE', 'paper')
    
    @staticmethod
    def get_alert_config() -> Dict[str, str]:
        """알림 설정"""
        return {
            'slack_webhook': os.getenv('SLACK_WEBHOOK_URL', ''),
            'telegram_token': os.getenv('TELEGRAM_BOT_TOKEN', ''),
            'telegram_chat_id': os.getenv('TELEGRAM_CHAT_ID', '')
        }

# 전역 설정 인스턴스
config = Config()
env_config = EnvConfig()
