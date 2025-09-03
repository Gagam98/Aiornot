# ranking.py

from pymongo import DESCENDING, ASCENDING
from bson.objectid import ObjectId


def get_ranking_data(mongo, username: str, mode: str, theme: str) -> dict:
    """
    scores 컬렉션에서 특정 모드와 테마에 대한 랭킹 데이터를 조회하고 계산합니다.

    :param mongo: Flask-PyMongo 인스턴스
    :param username: 현재 로그인한 사용자의 이름
    :param mode: 게임 모드 ('easy' 또는 'hard')
    :param theme: 게임 테마 (예: '고양이')
    :return: 랭킹 데이터가 담긴 딕셔너리
    """

    user = mongo.db.users.find_one({"username": username})
    if not user:
        return None

    scores_collection = mongo.db.scores

    # 1. 특정 모드/테마에서 각 사용자별 최고 점수를 찾기 위한 파이프라인
    pipeline = [
        {'$match': {'mode': mode, 'theme': theme}},
        {'$sort': {'score': DESCENDING, 'createdAt': ASCENDING}},
        {
            '$group': {
                '_id': '$user_id',
                'username': {'$first': '$username'},
                'max_score': {'$first': '$score'}
            }
        },
        {'$sort': {'max_score': DESCENDING}}
    ]

    all_users_ranking = list(scores_collection.aggregate(pipeline))

    # 2. 현재 사용자의 순위 계산
    user_rank = -1
    user_score = 0
    for i, rank_info in enumerate(all_users_ranking):
        if rank_info['_id'] == user['_id']:
            user_rank = i + 1
            user_score = rank_info['max_score']
            break

    # 3. 상위 3명 랭킹 정보 추출
    top_3_ranking = []
    for rank_info in all_users_ranking[:3]:
        top_3_ranking.append({
            'username': rank_info['username'],
            'score': rank_info['max_score']
        })

    # 4. 최종 데이터 정리하여 반환
    return {
        "user_rank": user_rank,
        "user_score": user_score,
        "top_3_ranking": top_3_ranking,
        "total_ranked_users": len(all_users_ranking)
    }