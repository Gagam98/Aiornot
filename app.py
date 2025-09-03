# app.py

import os
import random
import requests
from flask import Flask, render_template, jsonify, request
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
from config import Config
from auth import auth_bp
from extensions import mongo
from datetime import datetime
from ranking import get_ranking_data  # 변경된 랭킹 함수 import

# --- 설정 부분 (기존과 동일) ---
PIXABAY_API_KEY = "52091010-849e60920cd3cadb857a7d1d3"
CATEGORY_MAP = {
    "고양이": "cat", "아이스크림": "icecream", "장미": "rose", "과일": "fruit",
}


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    mongo.init_app(app)
    jwt = JWTManager(app)
    CORS(app)
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # --- 페이지 렌더링 라우트 (기존과 동일) ---
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
    def category():
        return render_template('category.html')

    @app.route('/levelselect')
    def levelselect():
        return render_template('levelselect.html')

    @app.route('/game')
    def game():
        return render_template('game.html')

    @app.route('/result')
    def result():
        return render_template('result.html')

    # --- API 엔드포인트 ---
    @app.route('/api/get-quiz-images', methods=['GET'])
    def get_quiz_images():
        # (기존과 동일)
        category_ko = request.args.get('category')
        count = request.args.get('count', default=2, type=int)
        if not category_ko: return jsonify({'message': '카테고리 정보가 없습니다.'}), 400
        search_query = CATEGORY_MAP.get(category_ko)
        if not search_query: return jsonify({'message': f"'{category_ko}'에 대한 검색어를 찾을 수 없습니다."}), 404
        api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"
        try:
            response = requests.get(api_url)
            response.raise_for_status()
            data = response.json()
            if not data.get("hits"): return jsonify({'message': f"'{category_ko}'에 대한 이미지를 찾을 수 없습니다."}), 404
            all_image_urls = [hit['largeImageURL'] for hit in data['hits']]
            if len(all_image_urls) < count: return jsonify({'message': f"퀴즈를 만들기에 이미지가 부족합니다."}), 409
            selected_urls = random.sample(all_image_urls, count)
            correct_answer_index = random.randint(0, count - 1)
            return jsonify({'images': selected_urls, 'correctAnswer': correct_answer_index})
        except requests.exceptions.RequestException as e:
            return jsonify({'message': f'이미지 API 호출 중 오류 발생: {e}'}), 503
        except Exception as e:
            return jsonify({'message': f'이미지를 처리하는 중 서버 오류 발생: {e}'}), 500

    # ### 변경된 부분 ###
    @app.route('/api/save-score', methods=['POST'])
    @jwt_required()
    def save_score():
        """게입 결과를 새로운 scores 컬렉션에 저장하는 API"""
        try:
            current_username = get_jwt_identity()
            user = mongo.db.users.find_one({"username": current_username})
            if not user:
                return jsonify({"message": "사용자를 찾을 수 없습니다."}), 404

            data = request.get_json()
            score = data.get('score')
            mode = data.get('difficulty')  # mode
            theme = data.get('category')  # theme

            if score is None or mode not in ['easy', 'hard'] or not theme:
                return jsonify({'message': '잘못된 데이터입니다.'}), 400

            # users 컬렉션 대신 scores 컬렉션에 새 문서를 삽입합니다.
            mongo.db.scores.insert_one({
                'user_id': user['_id'],  # users 컬렉션의 ObjectId 참조
                'username': current_username,  # 표시를 위한 사용자 이름
                'score': score,  # 점수
                'mode': mode,  # 난이도
                'theme': theme,  # 테마
                'createdAt': datetime.utcnow()  # 기록 시간
            })

            return jsonify({'message': '게임 결과가 성공적으로 저장되었습니다.'}), 200
        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

    # ### 변경된 부분 ###
    @app.route('/api/ranking', methods=['GET'])
    @jwt_required()
    def get_ranking():
        """난이도와 테마별 랭킹 정보를 반환하는 API"""
        try:
            username = get_jwt_identity()
            mode = request.args.get('difficulty')
            theme = request.args.get('category')

            if not all([mode, theme]) or mode not in ['easy', 'hard']:
                return jsonify({'message': '난이도와 테마 정보가 올바르지 않습니다.'}), 400

            # 새로운 랭킹 함수 호출
            ranking_data = get_ranking_data(mongo, username, mode, theme)

            if not ranking_data:
                return jsonify({'message': '사용자 정보를 찾을 수 없습니다.'}), 404

            return jsonify(ranking_data), 200
        except Exception as e:
            return jsonify({'message': f'랭킹 조회 중 서버 오류 발생: {e}'}), 500

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'message': '페이지를 찾을 수 없습니다'}), 404

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)