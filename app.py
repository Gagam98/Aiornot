# app.py

import os
import random
import requests  # requests 라이브러리 import
from flask import Flask, render_template, jsonify, request
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
from config import Config
from auth import auth_bp
from extensions import mongo

# --- 설정 부분 ---
# 발급받은 Pixabay API 키를 입력하세요.
# 보안을 위해 실제 운영 환경에서는 config.py나 환경 변수로 옮기는 것이 좋습니다.
PIXABAY_API_KEY = "52091010-849e60920cd3cadb857a7d1d3"

# 한글 카테고리를 Pixabay 검색을 위한 영어 단어로 매핑
CATEGORY_MAP = {
    "고양이": "cat",
    "아이스크림": "ice cream",
    "장미": "rose",
    "과일": "fruit",
}


# -----------------


def create_app():
    """Flask 애플리케이션을 생성하고 설정합니다."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # 확장 초기화
    mongo.init_app(app)
    jwt = JWTManager(app)
    CORS(app)

    # 블루프린트 등록
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
        """Pixabay API를 실시간으로 호출하여 이미지 목록을 반환하는 API"""
        category_ko = request.args.get('category')
        count = request.args.get('count', default=2, type=int)

        if not category_ko:
            return jsonify({'message': '카테고리 정보가 없습니다.'}), 400

        # 한글 카테고리를 영어 검색어로 변환
        search_query = CATEGORY_MAP.get(category_ko)
        if not search_query:
            return jsonify({'message': f"'{category_ko}'에 대한 검색어를 찾을 수 없습니다."}), 404

        # Pixabay API 요청 URL (한 페이지에 더 많은 결과를 요청해서 무작위성을 높임)
        api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"

        try:
            response = requests.get(api_url)
            response.raise_for_status()  # 요청 실패 시 예외 발생
            data = response.json()

            if not data.get("hits"):
                return jsonify({'message': f"'{category_ko}'에 대한 이미지를 찾을 수 없습니다."}), 404

            # 받아온 이미지 목록에서 URL만 추출
            all_image_urls = [hit['largeImageURL'] for hit in data['hits']]

            if len(all_image_urls) < count:
                return jsonify({'message': f"퀴즈를 만들기에 이미지가 부족합니다. (필요: {count}, API 결과: {len(all_image_urls)})"}), 409

            # 필요한 개수만큼 무작위로 이미지 URL 선택
            selected_urls = random.sample(all_image_urls, count)
            correct_answer_index = random.randint(0, count - 1)

            return jsonify({
                'images': selected_urls,
                'correctAnswer': correct_answer_index
            })

        except requests.exceptions.RequestException as e:
            return jsonify({'message': f'이미지 API 호출 중 오류 발생: {e}'}), 503  # 503 Service Unavailable
        except Exception as e:
            return jsonify({'message': f'이미지를 처리하는 중 서버 오류 발생: {e}'}), 500

    @app.route('/api/save-score', methods=['POST'])
    @jwt_required()
    def save_score():
        """게임 점수를 DB에 저장하는 API"""
        try:
            current_user = get_jwt_identity()
            data = request.get_json()
            score = data.get('score')
            difficulty = data.get('difficulty')

            if score is None or difficulty not in ['easy', 'hard']:
                return jsonify({'message': '잘못된 데이터입니다.'}), 400

            score_field = f"{difficulty}_score"

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
    app.run(debug=True, host='0.0.0.0', port=5000)

