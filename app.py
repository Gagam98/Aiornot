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
from ranking import get_ranking_data

# --- 설정 부분 ---
PIXABAY_API_KEY = "52091010-849e60920cd3cadb857a7d1d3"
CATEGORY_MAP = {
    "고양이": "cat",
    "아이스크림": "icecream",
    "장미": "rose",
    "과일": "fruit",
}


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
        """
        카테고리에 맞는 퀴즈 이미지를 Pixabay API를 통해 가져오는 API
        '랜덤'과 '나만퀴' 카테고리를 처리하는 로직이 추가되었습니다.
        """
        category_ko = request.args.get('category')
        count = request.args.get('count', default=2, type=int)

        if not category_ko:
            return jsonify({'message': '카테고리 정보가 없습니다.'}), 400

        # '나만퀴' 특별 처리
        if category_ko == '나만퀴(나만의 퀴즈 만들기)':
            # TODO: 여기에 '나만퀴'를 위한 커스텀 로직을 구현해야 합니다.
            # 예를 들어, 사용자가 만든 퀴즈 데이터를 DB에서 가져올 수 있습니다.
            # 현재는 빈 이미지 리스트와 함께 성공 응답을 보냅니다.
            return jsonify({'images': [], 'correctAnswer': 0, 'message': '나만퀴 기능은 준비 중입니다.'})

        # '랜덤' 카테고리 처리
        if category_ko == '랜덤':
            # CATEGORY_MAP의 키(한글 이름) 중 하나를 무작위로 선택
            random_category_ko = random.choice(list(CATEGORY_MAP.keys()))
            search_query = CATEGORY_MAP[random_category_ko]
        else:
            # 일반 카테고리 처리
            search_query = CATEGORY_MAP.get(category_ko)

        if not search_query:
            return jsonify({'message': f"'{category_ko}'에 대한 검색어를 찾을 수 없습니다."}), 404

        api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"

        try:
            response = requests.get(api_url)
            response.raise_for_status()  # 요청 실패 시 예외 발생
            data = response.json()

            if not data.get("hits"):
                return jsonify({'message': f"'{category_ko}'에 대한 이미지를 찾을 수 없습니다."}), 404

            all_image_urls = [hit['largeImageURL'] for hit in data['hits']]

            if len(all_image_urls) < count:
                return jsonify({'message': f"퀴즈를 만들기에 이미지가 부족합니다."}), 409

            selected_urls = random.sample(all_image_urls, count)
            correct_answer_index = random.randint(0, count - 1)

            return jsonify({'images': selected_urls, 'correctAnswer': correct_answer_index})

        except requests.exceptions.RequestException as e:
            return jsonify({'message': f'이미지 API 호출 중 오류 발생: {e}'}), 503
        except Exception as e:
            return jsonify({'message': f'이미지를 처리하는 중 서버 오류 발생: {e}'}), 500

    @app.route('/api/save-score', methods=['POST'])
    @jwt_required()
    def save_score():
        """게임 결과를 scores 컬렉션에 저장하는 API"""
        try:
            current_username = get_jwt_identity()
            user = mongo.db.users.find_one({"username": current_username})
            if not user:
                return jsonify({"message": "사용자를 찾을 수 없습니다."}), 404

            data = request.get_json()
            score = data.get('score')
            mode = data.get('difficulty')
            theme = data.get('category')

            if score is None or mode not in ['easy', 'hard'] or not theme:
                return jsonify({'message': '잘못된 데이터입니다.'}), 400

            # '랜덤' 또는 '나만퀴' 테마는 랭킹에 저장하지 않음 (선택 사항)
            if theme in ['랜덤', '나만퀴(나만의 퀴즈 만들기)']:
                return jsonify({'message': '랜덤/나만퀴 모드는 랭킹에 기록되지 않습니다.'}), 200

            mongo.db.scores.insert_one({
                'user_id': user['_id'],
                'username': current_username,
                'score': score,
                'mode': mode,
                'theme': theme,
                'createdAt': datetime.utcnow()
            })

            return jsonify({'message': '게임 결과가 성공적으로 저장되었습니다.'}), 200
        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

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


# 앱 인스턴스 생성
app = create_app()

if __name__ == '__main__':
    # 디버그 모드로 앱 실행
    app.run(debug=True, host='0.0.0.0', port=5000)