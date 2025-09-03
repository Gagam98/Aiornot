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
import logging

logger = logging.getLogger(__name__)

from dotenv import load_dotenv
import os

load_dotenv()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

# 개선된 카테고리 매핑 시스템
CATEGORY_CONFIG = {
    "cat": {
        "ko": "고양이",
        "en": "cat",
        "search_query": "cat",
        "image": "cat.jpg"
    },
    "icecream": {
        "ko": "아이스크림", 
        "en": "icecream",
        "search_query": "icecream",
        "image": "icecream.jpg"
    },
    "rose": {
        "ko": "장미",
        "en": "rose", 
        "search_query": "rose",
        "image": "rose.jpg"
    },
    "fruit": {
        "ko": "과일",
        "en": "fruit",
        "search_query": "fruit", 
        "image": "fruits.jpg"
    },
    "random": {
        "ko": "랜덤",
        "en": "random",
        "search_query": "random",
        "image": "random.jpg"
    },
    "custom": {
        "ko": "나만퀴(나만의 퀴즈 만들기)",
        "en": "custom",
        "search_query": "custom",
        "image": "question.png"
    }
}

# 하위 호환성을 위한 기존 매핑 (한글 키 -> 영어 키)
LEGACY_CATEGORY_MAP = {v["ko"]: k for k, v in CATEGORY_CONFIG.items()}

# API에서 한글/영어 키를 모두 지원하는 헬퍼 함수
def get_category_info(category_input):
    """카테고리 입력(한글/영어)을 받아서 표준화된 정보를 반환"""
    # 영어 키로 직접 조회 시도
    if category_input in CATEGORY_CONFIG:
        return category_input, CATEGORY_CONFIG[category_input]
    
    # 한글 키로 조회 (하위 호환성)
    english_key = LEGACY_CATEGORY_MAP.get(category_input)
    if english_key:
        return english_key, CATEGORY_CONFIG[english_key]
    
    return None, None

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

    # --- API 엔드포인트 --- 제거예정
    @app.route('/api/get-quiz-images', methods=['GET'])
    def get_quiz_images():
        """
        카테고리에 맞는 퀴즈 이미지를 Pixabay API를 통해 가져오는 API
        영어/한글 키를 모두 지원합니다.
        """
        category_input = request.args.get('category')
        count = request.args.get('count', default=2, type=int)

        if not category_input:
            return jsonify({'message': '카테고리 정보가 없습니다.'}), 400

        # 카테고리 정보 가져오기 (한글/영어 모두 지원)
        category_key, category_info = get_category_info(category_input)
        
        if not category_key:
            return jsonify({'message': f"'{category_input}'에 대한 카테고리를 찾을 수 없습니다."}), 404

        # '나만퀴' 특별 처리
        if category_key == 'custom':
            # 나만퀴 기능은 준비 중입니다.
            # 현재는 빈 이미지 리스트와 함께 성공 응답을 보냅니다.
            return jsonify({'images': [], 'correctAnswer': 0, 'message': '나만퀴 기능은 준비 중입니다.'})

        # '랜덤' 카테고리 처리
        if category_key == 'random':
            # 랜덤 카테고리 제외하고 하나 선택
            available_categories = [k for k in CATEGORY_CONFIG.keys() if k not in ['random', 'custom']]
            selected_category_key = random.choice(available_categories)
            search_query = CATEGORY_CONFIG[selected_category_key]['search_query']
        else:
            # 일반 카테고리 처리
            search_query = category_info['search_query']

        api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"

        try:
            response = requests.get(api_url)
            response.raise_for_status()  # 요청 실패 시 예외 발생
            data = response.json()

            if not data.get("hits"):
                return jsonify({'message': f"'{category_info['ko']}'에 대한 이미지를 찾을 수 없습니다."}), 404

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
            category_input = data.get('category')
            difficulty = data.get('difficulty', 'easy')
            keyword = data.get('keyword', '')
            
            if not category_input:
                return jsonify({'message': '카테고리 정보가 없습니다.'}), 400

            # 카테고리 정보 가져오기 (한글/영어 모두 지원)
            category_key, category_info = get_category_info(category_input)
            
            if not category_key:
                return jsonify({'message': f"'{category_input}'에 대한 카테고리를 찾을 수 없습니다."}), 404

            # '랜덤' 카테고리 처리
            if category_key == 'random':
                # 랜덤 카테고리 제외하고 하나 선택
                available_categories = [k for k in CATEGORY_CONFIG.keys() if k not in ['random', 'custom']]
                selected_category_key = random.choice(available_categories)
                search_query = CATEGORY_CONFIG[selected_category_key]['search_query']
            # 나만퀴 처리
            elif category_key == 'custom':
                search_query = keyword
            else:
                # 일반 카테고리 처리
                search_query = category_info['search_query']

            # AI 이미지 생성용 프롬프트
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
            failed_prompts = []
            
            for prompt, paths in ai_results.items():
                if paths:
                    ai_image_paths.extend([str(path) for path in paths])
                else:
                    failed_prompts.append(prompt)

            # 재시도 로직: 부족하면 실패한 프롬프트 재시도
            if len(ai_image_paths) < 10 and failed_prompts:
                logger.info(f"재시도: {len(failed_prompts)}개 프롬프트로 추가 생성")
                
                retry_results = generate_images_concurrent(
                    prompts=failed_prompts,
                    out_dir=f"static/generated/{search_query}",
                    repeat_per_prompt=1,
                    max_workers=len(failed_prompts)
                )
                
                for prompt, paths in retry_results.items():
                    ai_image_paths.extend([str(path) for path in paths])

            # 유연한 기준: 6장 이상이면 진행 (최소 6문제 가능)
            min_required = 6
            if len(ai_image_paths) < min_required:
                return jsonify({
                    'message': f'AI 이미지 생성 부족 (생성: {len(ai_image_paths)}장, 최소: {min_required}장)',
                    'generated_count': len(ai_image_paths)
                }), 500

            # Pixabay에서 실제 사진 50장 가져오기
            api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"
            response = requests.get(api_url)
            response.raise_for_status()
            pixabay_data = response.json()

            if not pixabay_data.get("hits"):
                return jsonify({'message': f"'{category_info['ko']}'에 대한 실제 이미지를 찾을 수 없습니다."}), 404

            real_image_urls = [hit['largeImageURL'] for hit in pixabay_data['hits']]

            if len(real_image_urls) < 10:
                return jsonify({'message': '실제 이미지가 부족합니다.'}), 409

            # 퀴즈 세트 생성 (생성된 AI 이미지 수에 따라 조정)
            quiz_sets = []
            images_per_question = 6 if difficulty == 'hard' else 2
            max_questions = min(10, len(ai_image_paths))  # 생성된 이미지 수에 따라 조정

            for i in range(max_questions):
                # AI 이미지 1장과 실제 이미지 (images_per_question-1)장 선택
                ai_image = ai_image_paths[i] if i < len(ai_image_paths) else random.choice(ai_image_paths)
                real_images = random.sample(real_image_urls, images_per_question - 1)

                # 이미지 목록 생성 및 섞기
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
                'message': f'게임 준비가 완료되었습니다. (AI 이미지: {len(ai_image_paths)}장)',
                'quizSets': quiz_sets,
                'totalQuestions': len(quiz_sets),
                'aiImagesGenerated': len(ai_image_paths),
                'isPartialGeneration': len(ai_image_paths) < 10
            })

        except requests.exceptions.RequestException as e:
            return jsonify({'message': f'이미지 API 호출 중 오류 발생: {e}'}), 503
        except Exception as e:
            return jsonify({'message': f'게임 준비 중 서버 오류 발생: {e}'}), 500

    def get_ai_prompts_for_category(category):
        """카테고리별 AI 이미지 생성 프롬프트 반환"""
        prompts_map = {
            "cat": [
                "Photorealistic sunrise rooftop shot of a tabby cat sitting on a warm metal railing, gentle haze, center big gemini watermark.",
                "Photorealistic cat peeking out of a cardboard box on a living room floor, side window light, soft bokeh, center big gemini watermark.",
                "Photorealistic reflection of a black cat in a wall mirror, tungsten lamp mixed with daylight, handheld, center big gemini watermark.",
                "Photorealistic alley scene with a ginger cat near a puddle after rain, overcast sky, subtle reflections, center big gemini watermark.",
                "Photorealistic close-up of a cat's collar tag and fur texture, diffused daylight, high micro-contrast, center big gemini watermark.",
                "Photorealistic candid through houseplants showing a cat on a windowsill, backlit greenery bokeh, center big gemini watermark.",
                "Photorealistic top-down shot of a white cat lounging on tatami mat, soft ambient light, natural colors, center big gemini watermark.",
                "Photorealistic cat curled beside a space heater glow, warm white balance, slight grain, center big gemini watermark.",
                "Photorealistic maine coon cat stretching on wooden deck at sunset, warm golden hour lighting, center big gemini watermark.",
                "Photorealistic persian cat sleeping in a sunbeam through lace curtains, soft diffused light, dreamy bokeh, center big gemini watermark."
            ],
            "icecream": [
                "Photorealistic cafe window seat shot of a strawberry sundae with condensation on the glass, side window light",
                "Photorealistic close-up of soft-serve swirling out of a machine into a cone, clean stainless backdrop, motion freeze",
                "Photorealistic child's hands holding a chocolate-dipped cone at a park, bright daylight, gentle background blur",
                "Photorealistic macro detail of waffle cone texture with tiny sugar crystals, softbox bounce.",
                "Photorealistic two friends clinking ice cream cones on a city street, late afternoon sun, lively bokeh",
                "Photorealistic car interior shot of a vanilla cone near the dashboard, mixed lighting, natural reflections",
                "Photorealistic evening street festival with a mango sorbet cup under string lights, warm bokeh, handheld",
                "Photorealistic freezer door opening with frost swirl and a pistachio pint visible, cool white balance",
                "Photorealistic gelato display case with colorful scoops under warm display lights, commercial lighting",
                "Photorealistic melting ice cream on hot pavement creating a colorful puddle, harsh midday sun, high contrast"
            ],
            "rose": [
                "Photorealistic florist's cooler seen through fogged glass with red and white roses, cool lighting, condensation detail",
                "Photorealistic dried rose on linen fabric beside a window, soft morning light, gentle shadows",
                "Photorealistic rose silhouette projected on a wall by direct sunlight, strong contrast, crisp edges",
                "Photorealistic candlelit macro of rose stamens and inner petals, warm flicker, handheld",
                "Photorealistic rose crown woven into hair at an outdoor garden, backlit strands, natural color",
                "Photorealistic scattered rose petals on a marble staircase, side light, subtle specular highlights",
                "Photorealistic single yellow rose under a glass cloche on a wooden desk, soft desk lamp, reflections controlled",
                "Photorealistic raindrops sliding on a rose leaf with sharp vein detail, overcast daylight",
                "Photorealistic vintage rose bouquet in antique crystal vase, window light with lace shadows",
                "Photorealistic wild rose bush growing against old brick wall, natural outdoor lighting, textural detail"
            ],
            "fruit": [
                "Photorealistic breakfast counter with a bowl of berries and yogurt, side window light, natural tones",
                "Photorealistic pouring smoothie into a glass with banana and spinach beside, motion freeze, kitchen light",
                "Photorealistic apple picking in an orchard with sunlit leaves, backlit flare, candid hands",
                "Photorealistic analog scale with a crate of oranges on a market counter, ambient indoor light",
                "Photorealistic picnic bench with a freshly cut watermelon wedge, bright midday sun, crisp texture",
                "Photorealistic fig cross-section on a ceramic plate, window side-light, rich seeds detail",
                "Photorealistic grapes on the vine with translucent backlight, vineyard ambience",
                "Photorealistic stainless bowl reflection with assorted fruits on a counter, cool kitchen light, subtle reflections",
                "Photorealistic farmers market display of colorful seasonal fruits, natural outdoor lighting, vibrant colors",
                "Photorealistic tropical fruit salad in coconut bowl on beach sand, bright beach lighting, shallow depth of field"
            ],
        }

        custom_prompts = [
            f"A {category} is sitting quietly in the park, trees swaying gently in the wind.",
            f"A beautiful {category}, glowing softly under the warm sunlight.",
            f"A cyber-style {category}, with mechanical parts and futuristic aesthetics.",
            f"A vintage {category}, inspired by 19th-century design elements.",
            f"A floating {category}, spinning silently in the sky.",
            f"Generate a hyper-realistic photograph of a person in a setting related to {category}.",
            f"Create a stylized, artistic shot of an object or landscape featuring {category}.",
            f"Generate a detailed digital art illustration of a scene featuring {category}.",
            f"Produce a stunning close-up shot of an object or concept related to {category}.",
            f"Create a breathtaking landscape image where {category} is the central element. ",
        ]

        if category in ["cat", "icecream", "rose", "fruit"]:
            return prompts_map.get(category, prompts_map["cat"])
        else:   
            return custom_prompts 

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