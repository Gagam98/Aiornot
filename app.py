# app.py

from flask import Flask, render_template, jsonify, request
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
from config import Config
from auth import auth_bp
from extensions import mongo


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    mongo.init_app(app)
    jwt = JWTManager(app)
    CORS(app)

    app.register_blueprint(auth_bp, url_prefix='/auth')

    # --- 페이지 렌더링 라우트 ---
    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/welcome')
    def welcome():
        return render_template('login.html')

    @app.route('/signup')
    def signup():
        return render_template('signup.html')

    @app.route('/category')
    @jwt_required()
    def category():
        return render_template('category.html')

    @app.route('/levelselect')
    @jwt_required()
    def levelselect():
        return render_template('levelselect.html')

    @app.route('/game')
    @jwt_required()
    def game():
        return render_template('game.html')

    @app.route('/result')
    @jwt_required()
    def result():
        return render_template('result.html')

    # --- API 엔드포인트 ---
    @app.route('/api/save-score', methods=['POST'])
    @jwt_required()
    def save_score():
        try:
            current_user = get_jwt_identity()
            data = request.get_json()
            score = data.get('score')
            difficulty = data.get('difficulty')

            if score is None or difficulty not in ['easy', 'hard']:
                return jsonify({'message': '잘못된 데이터입니다.'}), 400

            # 난이도에 따라 적절한 점수 필드 업데이트
            score_field = f"{difficulty}_score"

            # 새 점수가 기존 점수보다 높을 경우에만 업데이트
            mongo.db.users.update_one(
                {'username': current_user, score_field: {'$lt': score}},
                {'$set': {score_field: score}}
            )

            return jsonify({'message': '점수가 성공적으로 저장되었습니다.'}), 200
        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

    # --- 에러 핸들러 ---
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'message': '페이지를 찾을 수 없습니다'}), 404

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0._0.0.0', port=5001)