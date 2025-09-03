# auth.py

from flask import Blueprint, request, jsonify, render_template
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity, get_jwt
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from extensions import mongo

auth_bp = Blueprint('auth', __name__)
blacklisted_tokens = set()

# JWT 토큰 블랙리스트 확인 콜백
@auth_bp.record_once
def on_load(state):
    jwt = state.app.extensions['flask-jwt-extended']
    @jwt.token_in_blocklist_loader
    def check_if_token_is_revoked(jwt_header, jwt_payload):
        jti = jwt_payload['jti']
        return jti in blacklisted_tokens

@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('id', '').strip()
        email = data.get('email', '').strip()
        password = data.get('password', '')

        if not all([username, email, password]):
            return jsonify({'message': '모든 필드를 입력해주세요'}), 400
        if len(password) < 6:
            return jsonify({'message': '비밀번호는 최소 6자 이상이어야 합니다'}), 400

        if mongo.db.users.find_one({"username": username}):
            return jsonify({'message': '이미 존재하는 ID입니다'}), 400
        if mongo.db.users.find_one({"email": email}):
            return jsonify({'message': '이미 존재하는 이메일입니다'}), 400

        # ### 변경된 부분 ###
        # easy_score와 hard_score 필드를 제거했습니다.
        user_id = mongo.db.users.insert_one({
            'username': username,
            'email': email,
            'password_hash': generate_password_hash(password)
        }).inserted_id

        return jsonify({'message': '회원가입이 완료되었습니다', 'user_id': str(user_id)}), 201

    except Exception as e:
        return jsonify({'message': f'서버 오류: {e}'}), 500

# login, logout, verify_token 함수는 기존과 동일합니다.
@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('id', '').strip()
        password = data.get('password', '')

        if not username or not password:
            return jsonify({'message': 'ID와 비밀번호를 입력해주세요'}), 400

        user = mongo.db.users.find_one({"$or": [{"username": username}, {"email": username}]})

        if user and check_password_hash(user['password_hash'], password):
            access_token = create_access_token(
                identity=user['username'],
                expires_delta=timedelta(hours=24)
            )
            return jsonify({
                'message': '로그인 성공',
                'access_token': access_token,
                'username': user['username']
            }), 200

        return jsonify({'message': '잘못된 ID 또는 비밀번호입니다'}), 401

    except Exception as e:
        return jsonify({'message': f'서버 오류: {e}'}), 500

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    jti = get_jwt()['jti']
    blacklisted_tokens.add(jti)
    return jsonify({'message': '로그아웃되었습니다'}), 200

@auth_bp.route('/verify-token', methods=['GET'])
@jwt_required()
def verify_token():
    try:
        current_username = get_jwt_identity()
        return jsonify({'valid': True, 'username': current_username}), 200
    except Exception:
        return jsonify({'valid': False}), 401