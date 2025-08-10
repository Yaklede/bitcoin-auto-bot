#!/bin/bash

# EC2에서 로그 관리 설정을 위한 스크립트
# 사용법: sudo ./setup-log-management.sh

echo "=== Docker 로그 관리 설정 시작 ==="

# 1. Docker 데몬 로그 설정 업데이트
echo "Docker 데몬 로그 설정 업데이트..."
cat > /etc/docker/daemon.json << EOF
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "3",
    "compress": "true"
  },
  "storage-driver": "overlay2"
}
EOF

# 2. 로그 로테이션 설정 복사
echo "로그 로테이션 설정..."
cp ./docker/logrotate.conf /etc/logrotate.d/docker-containers
chmod 644 /etc/logrotate.d/docker-containers

# 3. 로그 디렉토리 권한 설정
echo "로그 디렉토리 권한 설정..."
mkdir -p ./logs
chown -R ubuntu:ubuntu ./logs
chmod 755 ./logs

# 4. 시스템 로그 정리 크론잡 설정
echo "크론잡 설정..."
(crontab -l 2>/dev/null; echo "0 2 * * * /usr/sbin/logrotate /etc/logrotate.d/docker-containers") | crontab -
(crontab -l 2>/dev/null; echo "0 3 * * * docker system prune -f --filter until=168h") | crontab -

# 5. Docker 재시작
echo "Docker 재시작..."
systemctl restart docker

# 6. 현재 로그 사용량 확인
echo "=== 현재 로그 사용량 ==="
du -sh /var/lib/docker/containers/*/
du -sh ./logs/

echo "=== 로그 관리 설정 완료 ==="
echo "주요 설정:"
echo "- Docker 로그: 최대 50MB × 3개 파일 (압축)"
echo "- 로그 로테이션: 매일 실행, 7일 보관"
echo "- Docker 시스템 정리: 매일 새벽 3시 (7일 이상된 데이터 삭제)"
echo "- Prometheus 데이터: 7일 보관, 최대 2GB"
