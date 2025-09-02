import os

class Config:
    """Flask 애플리케이션의 모든 설정을 관리합니다."""

    # 1. 보안 키를 예측 불가능한 임의의 문자열로 변경
    #    (터미널에서 python -c "import secrets; print(secrets.token_hex(16))" 명령어로 생성)
    SECRET_KEY = os.environ.get('SECRET_KEY') or '2d8b5a7b8e5f2a1b9c4d9e8f3a2b1c0d'
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY') or 'f0a9b8c7d6e5f4a3b2c1d0e9f8a7b6c5'

    # 2. MONGO_URI를 클래스 내부에 한 번만 명확하게 정의
    #    (실제 발급받은 URI로 이 부분을 교체하세요)
    MONGO_URI = os.environ.get('MONGO_URI') or "mongodb+srv://jungle01_db_user:7YY5MfgNU92HivHA@aiornot.gfhjper.mongodb.net/AIorNot?retryWrites=true&w=majority"