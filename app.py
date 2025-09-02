# app.py

from flask import Flask, render_template, jsonify
from flask_jwt_extended import JWTManager, jwt_required # jwt_required 추가
from flask_cors import CORS
from config import Config
from auth import auth_bp
from extensions import mongo

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 확장 프로그램 초기화
    mongo.init_app(app)
    jwt = JWTManager(app)
    CORS(app)

    # Blueprint 등록
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # --- 라우트 ---
    @app.route('/')
    def dashboard():
        """기본 대시보드 페이지"""
        return render_template('dashboard.html')

    @app.route('/welcome')
    def welcome():
        """로그인 폼을 보여주는 페이지 (auth 블루프린트와 분리)"""
        return render_template('login.html')

    # ▼▼▼▼▼ 로그인 후 도착할 메인 페이지 라우트 추가 ▼▼▼▼▼
    @app.route('/main')
    def main_page():
        # 이 페이지는 클라이언트 측에서 JWT 토큰을 기반으로 접근을 제어합니다.
        # 서버 측 보호가 필요하다면 @jwt_required()를 사용할 수 있으나,
        # 여기서는 localStorage에 토큰 유무로 판단하는 로직을 따릅니다.
        return render_template('main.html')
    # ▲▲▲▲▲ 여기까지 추가 ▲▲▲▲▲

    # --- 에러 핸들러 ---
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'message': '페이지를 찾을 수 없습니다'}), 404

    return app

# 앱 생성
app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)