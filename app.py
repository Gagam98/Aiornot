# app.py

import os
import random
import requests
from flask import Flask, render_template, jsonify, request, url_for
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
from config import Config
from auth import auth_bp
from extensions import mongo
from datetime import datetime
from ranking import get_ranking_data
from crawling import generate_images_concurrent

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

    @app.route('/api/prepare-game', methods=['POST'])
    def prepare_game():
        """게임 시작 전 AI 이미지를 미리 생성하고 퀴즈 세트를 준비"""
        try:
            data = request.get_json()
            category_ko = data.get('category')
            difficulty = data.get('difficulty', 'easy')

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

            # AI 이미지 생성용 프롬프트 (crawling.py의 프롬프트 재사용)
            ai_prompts = get_ai_prompts_for_category(search_query)

            # AI 이미지 10장 생성
            ai_results = generate_images_concurrent(
                prompts=ai_prompts[:10],  # 10개 프롬프트만 사용
                out_dir=f"static/generated/{search_query}",
                repeat_per_prompt=1,
                max_workers=10
            )

            # 생성된 AI 이미지 경로 수집
            ai_image_paths = []
            for prompt, paths in ai_results.items():
                ai_image_paths.extend([str(path) for path in paths])

            if len(ai_image_paths) < 10:
                return jsonify({'message': 'AI 이미지 생성에 실패했습니다.'}), 500

            # Pixabay에서 실제 사진 50장 가져오기
            api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"
            response = requests.get(api_url)
            response.raise_for_status()
            pixabay_data = response.json()

            if not pixabay_data.get("hits"):
                return jsonify({'message': f"'{category_ko}'에 대한 실제 이미지를 찾을 수 없습니다."}), 404

            real_image_urls = [hit['largeImageURL'] for hit in pixabay_data['hits']]

            if len(real_image_urls) < 10:
                return jsonify({'message': '실제 이미지가 부족합니다.'}), 409

            # 퀴즈 세트 생성 (10문제)
            quiz_sets = []
            images_per_question = 6 if difficulty == 'hard' else 2

            for i in range(10):
                # AI 이미지 1장과 실제 이미지 (images_per_question-1)장 선택
                ai_image = ai_image_paths[i] if i < len(ai_image_paths) else random.choice(ai_image_paths)
                real_images = random.sample(real_image_urls, images_per_question - 1)

                # 이미지 목록 생성 및 셞기
                question_images = [ai_image] + real_images
                random.shuffle(question_images)

                # 정답 인덱스 찾기
                correct_answer = question_images.index(ai_image)

                # AI 이미지 경로를 URL로 변환
                question_images_urls = []
                for img_path in question_images:
                    if img_path.startswith('static/'):
                        # 로컬 AI 생성 이미지
                        question_images_urls.append(url_for('static', filename=img_path[7:]))  # 'static/' 제거
                    else:
                        # Pixabay URL
                        question_images_urls.append(img_path)

                quiz_sets.append({
                    'images': question_images_urls,
                    'correctAnswer': correct_answer
                })

            return jsonify({
                'message': '게임 준비가 완료되었습니다.',
                'quizSets': quiz_sets,
                'totalQuestions': 10
            })

        except requests.exceptions.RequestException as e:
            return jsonify({'message': f'이미지 API 호출 중 오류 발생: {e}'}), 503
        except Exception as e:
            return jsonify({'message': f'게임 준비 중 서버 오류 발생: {e}'}), 500

    def get_ai_prompts_for_category(category):
        """카테고리별 AI 이미지 생성 프롬프트 반환"""
        prompts_map = {
            "cat": [
                "Photorealistic sunrise rooftop shot of a tabby cat sitting on a warm metal railing, 35mm, f/2.0, ISO 200, 1/800s, golden rim light, gentle haze, center big gemini watermark.",
                "Photorealistic cat peeking out of a cardboard box on a living room floor, 50mm, f/1.8, ISO 400, 1/250s, side window light, soft bokeh, center big gemini watermark.",
                "Photorealistic reflection of a black cat in a wall mirror, 35mm, f/2.2, ISO 800, 1/125s, tungsten lamp mixed with daylight, handheld, center big gemini watermark.",
                "Photorealistic alley scene with a ginger cat near a puddle after rain, 28mm, f/2.8, ISO 320, 1/500s, overcast sky, subtle reflections, center big gemini watermark.",
                "Photorealistic close-up of a cat's collar tag and fur texture, 85mm, f/2.8, ISO 200, 1/400s, diffused daylight, high micro-contrast, center big gemini watermark.",
                "Photorealistic candid through houseplants showing a cat on a windowsill, 50mm, f/2.0, ISO 320, 1/250s, backlit greenery bokeh, center big gemini watermark.",
                "Photorealistic top-down shot of a white cat lounging on tatami mat, 35mm, f/2.8, ISO 200, 1/160s, soft ambient light, natural colors, center big gemini watermark.",
                "Photorealistic cat curled beside a space heater glow, 35mm, f/1.8, ISO 1600, 1/100s, warm white balance, slight grain, center big gemini watermark.",
                "Photorealistic maine coon cat stretching on wooden deck at sunset, 85mm, f/2.0, ISO 100, 1/1000s, warm golden hour lighting, center big gemini watermark.",
                "Photorealistic persian cat sleeping in a sunbeam through lace curtains, 50mm, f/1.4, ISO 200, 1/500s, soft diffused light, dreamy bokeh, center big gemini watermark."
            ],
            "icecream": [
                "Photorealistic cafe window seat shot of a strawberry sundae with condensation on the glass, 50mm, f/2.2, ISO 200, 1/250s, side window light, center big gemini watermark.",
                "Photorealistic close-up of soft-serve swirling out of a machine into a cone, 70mm, f/4, ISO 400, 1/500s, clean stainless backdrop, motion freeze, center big gemini watermark.",
                "Photorealistic child's hands holding a chocolate-dipped cone at a park, 35mm, f/2.0, ISO 100, 1/1000s, bright daylight, gentle background blur, center big gemini watermark.",
                "Photorealistic macro detail of waffle cone texture with tiny sugar crystals, 100mm macro, f/5.6, ISO 200, 1/200s, softbox bounce, center big gemini watermark.",
                "Photorealistic two friends clinking ice cream cones on a city street, 28mm, f/2.8, ISO 400, 1/800s, late afternoon sun, lively bokeh, center big gemini watermark.",
                "Photorealistic car interior shot of a vanilla cone near the dashboard, 35mm, f/2.2, ISO 800, 1/160s, mixed lighting, natural reflections, center big gemini watermark.",
                "Photorealistic evening street festival with a mango sorbet cup under string lights, 50mm, f/1.8, ISO 2000, 1/200s, warm bokeh, handheld, center big gemini watermark.",
                "Photorealistic freezer door opening with frost swirl and a pistachio pint visible, 24mm, f/3.5, ISO 1600, 1/60s, cool white balance, center big gemini watermark.",
                "Photorealistic gelato display case with colorful scoops under warm display lights, 35mm, f/2.8, ISO 800, 1/125s, commercial lighting, center big gemini watermark.",
                "Photorealistic melting ice cream on hot pavement creating a colorful puddle, 50mm, f/4, ISO 100, 1/2000s, harsh midday sun, high contrast, center big gemini watermark."
            ],
            "rose": [
                "Photorealistic florist's cooler seen through fogged glass with red and white roses, 35mm, f/2.8, ISO 800, 1/125s, cool lighting, condensation detail, center big gemini watermark.",
                "Photorealistic dried rose on linen fabric beside a window, 50mm, f/2.0, ISO 200, 1/200s, soft morning light, gentle shadows, center big gemini watermark.",
                "Photorealistic rose silhouette projected on a wall by direct sunlight, 35mm, f/4, ISO 100, 1/2000s, strong contrast, crisp edges, center big gemini watermark.",
                "Photorealistic candlelit macro of rose stamens and inner petals, 105mm macro, f/3.5, ISO 1600, 1/60s, warm flicker, handheld, center big gemini watermark.",
                "Photorealistic rose crown woven into hair at an outdoor garden, 85mm, f/2.0, ISO 200, 1/640s, backlit strands, natural color, center big gemini watermark.",
                "Photorealistic scattered rose petals on a marble staircase, 28mm, f/2.8, ISO 400, 1/250s, side light, subtle specular highlights, center big gemini watermark.",
                "Photorealistic single yellow rose under a glass cloche on a wooden desk, 50mm, f/2.5, ISO 320, 1/160s, soft desk lamp, reflections controlled, center big gemini watermark.",
                "Photorealistic raindrops sliding on a rose leaf with sharp vein detail, 100mm macro, f/5.6, ISO 400, 1/200s, overcast daylight, center big gemini watermark.",
                "Photorealistic vintage rose bouquet in antique crystal vase, 85mm, f/2.8, ISO 200, 1/320s, window light with lace shadows, center big gemini watermark.",
                "Photorealistic wild rose bush growing against old brick wall, 35mm, f/4, ISO 100, 1/1000s, natural outdoor lighting, textural detail, center big gemini watermark."
            ],
            "fruit": [
                "Photorealistic breakfast counter with a bowl of berries and yogurt, 35mm, f/2.8, ISO 200, 1/200s, side window light, natural tones, center big gemini watermark.",
                "Photorealistic pouring smoothie into a glass with banana and spinach beside, 50mm, f/3.2, ISO 400, 1/500s, motion freeze, kitchen light, center big gemini watermark.",
                "Photorealistic apple picking in an orchard with sunlit leaves, 35mm, f/2.0, ISO 200, 1/1000s, backlit flare, candid hands, center big gemini watermark.",
                "Photorealistic analog scale with a crate of oranges on a market counter, 28mm, f/4, ISO 400, 1/160s, ambient indoor light, center big gemini watermark.",
                "Photorealistic picnic bench with a freshly cut watermelon wedge, 35mm, f/2.8, ISO 100, 1/640s, bright midday sun, crisp texture, center big gemini watermark.",
                "Photorealistic fig cross-section on a ceramic plate, 85mm, f/4, ISO 200, 1/200s, window side-light, rich seeds detail, center big gemini watermark.",
                "Photorealistic grapes on the vine with translucent backlight, 70mm, f/2.8, ISO 100, 1/1000s, vineyard ambience, center big gemini watermark.",
                "Photorealistic stainless bowl reflection with assorted fruits on a counter, 24mm, f/3.5, ISO 800, 1/60s, cool kitchen light, subtle reflections, center big gemini watermark.",
                "Photorealistic farmers market display of colorful seasonal fruits, 35mm, f/4, ISO 200, 1/500s, natural outdoor lighting, vibrant colors, center big gemini watermark.",
                "Photorealistic tropical fruit salad in coconut bowl on beach sand, 50mm, f/2.8, ISO 100, 1/1000s, bright beach lighting, shallow depth of field, center big gemini watermark."
            ]
        }
        return prompts_map.get(category, prompts_map["cat"])  # 기본값으로 cat 사용

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
    app.run(debug=True, host='0.0.0.0', port=5001)