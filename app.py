# app.py
import os
import random
import requests
from flask import Flask, render_template, jsonify, request, url_for, app
from flask_jwt_extended import JWTManager, jwt_required, get_jwt_identity
from flask_cors import CORS
import boto3

import config
from config import Config
from auth import auth_bp
from extensions import mongo
from datetime import datetime
from ranking import get_ranking_data
from crawling import generate_images_concurrent
from dotenv import load_dotenv
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()
PIXABAY_API_KEY = os.getenv("PIXABAY_API_KEY")

# S3 클라이언트 설정
s3_client = boto3.client(
    's3',
    aws_access_key_id=Config.aws_access_key,
    aws_secret_access_key=Config.aws_secret_key,
    region_name=Config.region_name
)
S3_BUCKET_NAME = Config.bucket_name

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
        ],
    }

    custom_prompts = [
        f"A lifelike {category} in a real park, trees swaying gently in the wind, candid composition",
        f"A beautiful {category} under warm golden-hour sunlight, soft rim light, cinematic composition",
        f"A realistic scene with a person naturally interacting with a {category}, captured in ultra-high-resolution with cinematic lighting and a professional lens.",
        f"photographed in a workshop, believable wear and fingerprints",
        f"A vintage {category} styled with authentic 19th-century props and wardrobe, film-like grain and slight halation",
        f"A levitation shot of {category} captured with a clean background and believable physics (subtle motion blur)",
        f"A hyper-realistic documentary photo featuring a person interacting with or representing '{category}', natural pose and expression",
        f"A studio still-life of objects that embody '{category}', seamless backdrop, softbox lighting, crisp detail",
        f"A detailed macro photo of textures linked to '{category}', shallow depth of field, tactile realism",
        f"A sweeping landscape where '{category}' is the clear focal element, layered depth and atmospheric perspective",
        f"A candid street-photography scene that naturally includes '{category}', off-guard moment, believable context",
        f"A night scene centered on '{category}' with practical light sources (neon, streetlamps), controlled noise",
        f"An editorial portrait that symbolizes '{category}', thoughtful styling and location, authentic skin texture"
    ]

    if category in ["cat", "icecream", "rose", "fruit"]:
        return prompts_map.get(category, prompts_map["cat"])
    else:
        return custom_prompts

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
    @app.route('/api/prepare-game', methods=['POST'])
    def prepare_game():
        """
        [개선] 게임 시작 전, S3 이미지를 먼저 확인하고 부족할 때만 AI 이미지를 생성합니다.
        """
        try:
            data = request.get_json()
            category_input = data.get('category')
            difficulty = data.get('difficulty', 'easy')
            keyword = data.get('keyword', '')

            if not category_input:
                return jsonify({'message': '카테고리 정보가 없습니다.'}), 400

            category_key, category_info = get_category_info(category_input)
            if not category_key:
                return jsonify({'message': f"'{category_input}'에 대한 카테고리를 찾을 수 없습니다."}), 404

            # '랜덤', '나만퀴' 모드에 따른 검색어 설정
            search_query = ""
            if category_key == 'random':
                available_categories = [k for k in CATEGORY_CONFIG.keys() if k not in ['random', 'custom']]
                selected_category_key = random.choice(available_categories)
                search_query = CATEGORY_CONFIG[selected_category_key]['search_query']
            elif category_key == 'custom':
                if not keyword:
                    return jsonify({'message': '나만퀴 모드에서는 키워드가 필요합니다.'}), 400
                search_query = keyword
            else:
                search_query = category_info['search_query']

            # --- S3 이미지 우선 확인 로직 ---
            ai_image_paths = []
            s3_prefix = f"generated/{search_query}/"
            s3_base_url = f"https://{S3_BUCKET_NAME}.s3.{Config.region_name}.amazonaws.com/"

            # 1. S3에서 기존 이미지 목록 가져오기
            response = s3_client.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=s3_prefix)
            if 'Contents' in response:
                for obj in response['Contents']:
                    key = obj['Key']
                    if not key.endswith('/'):
                        # DB에 저장할 때는 S3 키(경로) 자체를 저장합니다.
                        ai_image_paths.append(key)

            # 2. 이미지가 10장 미만이면 부족한 만큼만 생성
            num_images_needed = 10 - len(ai_image_paths)
            if num_images_needed > 0:
                logger.info(f"{search_query}: S3에 이미지가 부족하여 {num_images_needed}장 추가 생성 시작")
                ai_prompts = get_ai_prompts_for_category(search_query)

                # 부족한 수 만큼만 프롬프트를 선택하여 생성 요청
                new_image_results = generate_images_concurrent(
                    prompts=random.sample(ai_prompts, k=min(num_images_needed, len(ai_prompts))),
                    category=search_query,
                    repeat_per_prompt=1,
                    max_workers=10
                )
                for prompt, paths in new_image_results.items():
                    ai_image_paths.extend(paths)

            # 최종적으로 이미지가 최소 요구치(6장) 미만이면 에러 반환
            min_required = 6
            if len(ai_image_paths) < min_required:
                return jsonify({
                    'message': f'AI 이미지 생성 부족 (생성: {len(ai_image_paths)}장, 최소: {min_required}장)',
                }), 500

            # --- 퀴즈 생성 로직 (기존과 유사) ---
            # Pixabay 이미지 가져오기
            api_url = f"https://pixabay.com/api/?key={PIXABAY_API_KEY}&q={requests.utils.quote(search_query)}&image_type=photo&per_page=50"
            pixabay_response = requests.get(api_url)
            pixabay_data = pixabay_response.json()
            real_image_urls = [hit['largeImageURL'] for hit in pixabay_data.get('hits', [])]

            # 퀴즈 생성
            images_per_question = 6 if difficulty == 'hard' else 2
            max_questions = min(10, len(ai_image_paths))
            num_real_images_needed = (images_per_question - 1) * max_questions

            if len(real_image_urls) < num_real_images_needed:
                return jsonify({'message': '퀴즈 생성을 위한 실제 이미지가 부족합니다.'}), 409

            unique_real_images = random.sample(real_image_urls, num_real_images_needed)

            quiz_sets = []
            # AI 이미지를 10장 이상 생성되었더라도 10문제만 출제하도록 세어서 10장만 사용
            selected_ai_images = random.sample(ai_image_paths, max_questions)

            for i in range(max_questions):
                ai_image_s3_key = selected_ai_images[i]

                real_images_for_question = unique_real_images[
                                           i * (images_per_question - 1): (i + 1) * (images_per_question - 1)]

                # 이미지 URL 목록 생성 (AI 이미지는 전체 URL로 변환)
                question_images = [s3_base_url + ai_image_s3_key] + real_images_for_question
                random.shuffle(question_images)

                correct_answer = question_images.index(s3_base_url + ai_image_s3_key)

                quiz_sets.append({
                    'images': question_images,
                    'correctAnswer': correct_answer
                })

            return jsonify({
                'message': '게임 준비가 완료되었습니다.',
                'quizSets': quiz_sets,
                'totalQuestions': len(quiz_sets)
            })

        except Exception as e:
            logger.error(f"게임 준비 중 오류: {e}")
            return jsonify({'message': f'게임 준비 중 서버 오류 발생: {e}'}), 500

    # --- 게임 진행 상황 저장/복원 API ---
    @app.route('/api/save-progress', methods=['POST'])
    @jwt_required()
    def save_progress():
        """[수정] 게임 진행 상황 저장 시, 첫 저장에 quizSets 전체를 함께 저장합니다."""
        try:
            current_username = get_jwt_identity()
            user = mongo.db.users.find_one({"username": current_username})
            if not user:
                return jsonify({"message": "사용자를 찾을 수 없습니다."}), 404

            data = request.get_json()
            current_question = data.get('currentQuestion')
            score = data.get('score')
            mode = data.get('difficulty')
            theme = data.get('category')
            keyword = data.get('keyword', '')  # 키워드 추가
            is_final = data.get('isFinal', False)
            quiz_sets = data.get('quizSets')  # [추가] 프론트에서 보낸 퀴즈 데이터

            if score is None or not mode or not theme or current_question is None:
                return jsonify({'message': '잘못된 데이터입니다.'}), 400

            game_progress = {
                'user_id': user['_id'],
                'username': current_username,
                'score': score,
                'current_question': current_question,
                'mode': mode,
                'theme': theme,
                'keyword': keyword,
                'is_completed': is_final,
                'updatedAt': datetime.utcnow()
            }

            existing_progress = mongo.db.scores.find_one({
                'user_id': user['_id'], 'mode': mode, 'theme': theme, 'is_completed': False
            })

            if existing_progress:
                # 기존 진행 상황 업데이트 (퀴즈 데이터는 덮어쓰지 않음)
                mongo.db.scores.update_one(
                    {'_id': existing_progress['_id']},
                    {'$set': game_progress}
                )
            else:
                # 새로운 진행 상황 생성 시 퀴즈 데이터 추가
                if quiz_sets:
                    game_progress['quizSets'] = quiz_sets
                game_progress['createdAt'] = datetime.utcnow()
                mongo.db.scores.insert_one(game_progress)

            if is_final and theme not in ['랜덤', '나만퀴(나만의 퀴즈 만들기)']:
                mongo.db.scores.update_one(
                    {'user_id': user['_id'], 'mode': mode, 'theme': theme, 'is_completed': False},
                    {'$set': {'is_completed': True, 'updatedAt': datetime.utcnow()}}
                )

            return jsonify({'message': '진행 상황이 저장되었습니다.'}), 200
        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

    @app.route('/api/get-progress', methods=['GET'])
    @jwt_required()
    def get_progress():
        """[수정] 사용자의 진행중인 게임 조회 시, 저장된 quizSets도 함께 반환합니다."""
        try:
            current_username = get_jwt_identity()
            user = mongo.db.users.find_one({"username": current_username})
            if not user:
                return jsonify({"message": "사용자를 찾을 수 없습니다."}), 404

            mode = request.args.get('difficulty')
            theme = request.args.get('category')

            if not mode or not theme:
                return jsonify({'message': '올바른 난이도와 테마를 입력해주세요.'}), 400

            progress = mongo.db.scores.find_one({
                'user_id': user['_id'], 'mode': mode, 'theme': theme, 'is_completed': False
            })

            if progress:
                return jsonify({
                    'hasProgress': True,
                    'currentQuestion': progress['current_question'],
                    'score': progress['score'],
                    'keyword': progress.get('keyword', ''),  # 키워드 반환
                    # [추가] 저장된 퀴즈 데이터 반환
                    'quizSets': progress.get('quizSets', [])
                }), 200
            else:
                return jsonify({'hasProgress': False}), 200

        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

    @app.route('/api/delete-progress', methods=['DELETE'])
    @jwt_required()
    def delete_progress():
        """진행중인 게임 삭제 (새로 시작할 때)"""
        try:
            current_username = get_jwt_identity()
            user = mongo.db.users.find_one({"username": current_username})
            if not user:
                return jsonify({"message": "사용자를 찾을 수 없습니다."}), 404

            data = request.get_json()
            mode = data.get('difficulty')
            theme = data.get('category')

            if not mode or not theme or mode not in ['easy', 'hard']:
                return jsonify({'message': '올바른 난이도와 테마를 입력해주세요.'}), 400

            # 미완료 게임 삭제
            result = mongo.db.scores.delete_one({
                'user_id': user['_id'],
                'mode': mode,
                'theme': theme,
                'is_completed': False
            })

            if result.deleted_count > 0:
                return jsonify({'message': '진행중인 게임이 삭제되었습니다.'}), 200
            else:
                return jsonify({'message': '삭제할 진행중인 게임이 없습니다.'}), 404

        except Exception as e:
            return jsonify({'message': f'서버 오류: {e}'}), 500

    # --- 새로운 API: S3에서 이미지 목록 가져오기 ---
    @app.route('/api/get-quiz-images', methods=['GET'])
    @jwt_required()
    def get_quiz_images():
        """선택한 테마(카테고리)에 해당하는 이미지 URL 목록을 S3에서 가져옵니다."""
        theme = request.args.get('theme')  # ex: /api/get-quiz-images?theme=cat
        if not theme:
            return jsonify({"message": "테마(theme) 파라미터가 필요합니다."}), 400

        image_urls = []
        # S3 버킷의 'generated/테마명/' 경로를 prefix로 지정
        prefix = f"generated/{theme}/"

        try:
            # list_objects_v2를 사용해 해당 prefix를 가진 객체(파일) 목록 조회
            response = s3_client.list_objects_v2(
                Bucket=S3_BUCKET_NAME,
                Prefix=prefix
            )

            # 'Contents'가 있는지 확인 (파일이 하나도 없을 수 있음)
            if 'Contents' in response:
                for obj in response['Contents']:
                    # 객체 키(파일 경로)를 가져옴, ex: 'generated/cat/image-123.png'
                    key = obj['Key']

                    # 파일이 있는 경우에만 URL 생성 (폴더 자체는 제외)
                    if not key.endswith('/'):
                        # 공개적으로 접근 가능한 S3 URL 생성
                        url = f"https://{S3_BUCKET_NAME}.s3.{Config.region_name}.amazonaws.com/{key}"
                        image_urls.append(url)

            return jsonify({"image_urls": image_urls}), 200

        except Exception as e:
            return jsonify({'message': f'S3 이미지 목록을 가져오는 중 오류 발생: {e}'}), 500

    # --- 기존 API ---
    @app.route('/api/save-score', methods=['POST'])
    @jwt_required()
    def save_score():
        """게임 결과를 scores 컬렉션에 저장하는 API (완료된 게임만)"""
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
                'current_question': 10,  # 완료된 게임은 10문제 모두 완료
                'is_completed': True,
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
    app.run(debug=False, host='0.0.0.0', port=5001)