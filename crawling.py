# app.py
from google import genai
from google.genai import types  # 필요시 사용
from PIL import Image
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Tuple, Dict, Any, Optional, Union  # ← Union 추가
import os
import re
import uuid
import time
import dotenv

import boto3
from config import Config

dotenv.load_dotenv()
DEFAULT_MODEL = "gemini-2.5-flash-image-preview"

# S3 클라이언트 초기화 (config.py 값 사용)
# 프로그램 시작 시 한 번만 생성하여 재사용합니다.
s3_client = boto3.client(
    's3',
    aws_access_key_id=Config.aws_access_key,
    aws_secret_access_key=Config.aws_secret_key,
    region_name=Config.region_name
)
S3_BUCKET_NAME = Config.bucket_name
S3_BASE_PATH = "generated"

def _slugify(text: str) -> str:
    """파일명에 안전하도록 간단 슬러그화."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:60] if text else "image"

def generate_image_once(
    prompt: str,
    category: str,        # ← 변경
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    filename_prefix: Optional[str] = None,
) -> List[str]:
    """
    단일 요청으로 생성된 '모든 이미지 파트'를 저장하고 경로 리스트 반환.
    - prompt: 이미지 생성 프롬프트
    - out_dir: 저장 폴더
    - model: 사용할 모델명
    - api_key: 명시 없으면 환경변수 GOOGLE_API_KEY 사용
    - filename_prefix: 파일명 접두어(없으면 프롬프트 기반 자동 생성)
    """
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되어 있지 않습니다.")

    client = genai.Client(api_key=api_key)

    # 요청
    response = client.models.generate_content(
        model=model,
        contents=[prompt],
    )

    base = filename_prefix or _slugify(prompt)
    ts = int(time.time())
    saved_s3_paths: List[str] = [] # S3 경로를 저장할 리스트

    # 후보(candidate) 내 content.parts 에 이미지 파트가 들어있음
    # 텍스트 파트가 섞일 수 있어 분기 처리
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not getattr(candidate, "content", None):
        return saved_s3_paths

    idx_in_parts = 0
    for part in candidate.content.parts:
        # 텍스트는 건너뜀(필요시 로깅)
        if getattr(part, "text", None):
            continue

        inline = getattr(part, "inline_data", None)
        if inline and inline.data:
            try:
                img = Image.open(BytesIO(inline.data))
                unique = uuid.uuid4().hex[:8]
                fname = f"{base}-{ts}-{unique}-{idx_in_parts}.png"

                # S3 전체 경로(객체 키) 설정
                s3_object_name = f"{S3_BASE_PATH}/{category}/{fname}"

                # 이미지를 파일이 아닌 '메모리 버퍼'에 저장
                in_mem_file = BytesIO()
                img.save(in_mem_file, format='PNG')
                in_mem_file.seek(0)  # 버퍼의 포인터를 맨 앞으로 이동

                # 메모리에 있는 이미지 데이터를 S3로 직접 업로드
                s3_client.upload_fileobj(in_mem_file, S3_BUCKET_NAME, s3_object_name)

                saved_s3_paths.append(s3_object_name)
                # print(f"✅ S3 Upload OK: {s3_object_name}") # 확인이 필요하면 주석 해제
            except Exception as e:
                print(f"[warn] 이미지 저장 실패: {e}")

    return saved_s3_paths


def _worker_task(
    prompt: str,
    category: str,  # ← 변경
    model: str,
    api_key: Optional[str],
    filename_prefix: Optional[str],
) -> Tuple[str, List[str]]:
    """스레드 워커: 프롬프트 1건 생성-저장."""
    try:
        paths = generate_image_once(
            prompt=prompt,
            category=category,
            model=model,
            api_key=api_key,
            filename_prefix=filename_prefix,
        )
        return prompt, paths
    except Exception as e:
        print(f"[error] '{prompt}' 생성 실패: {e}")
        return prompt, []


def generate_images_concurrent(
    prompts: List[str],
    category: str, # 'category' 파라미터 추가
    *,
    repeat_per_prompt: int = 1,
    max_workers: int = 4,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    filename_prefix: Optional[str] = None,
) -> Dict[str, List[str]]: # 반환 타입을 S3 경로 리스트로 변경
    """
    여러 프롬프트를 동시 병렬로 요청하여 이미지를 S3에 업로드.
    - prompts: 프롬프트 목록
    - out_dir: 저장 폴더
    - repeat_per_prompt: 각 프롬프트를 몇 번 반복 호출할지(다양한 샘플 원할 때 >1)
    - max_workers: 동시 스레드 수
    - model, api_key, filename_prefix: 옵션
    반환: {prompt: [Path, ...]} 매핑
    """
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되어 있지 않습니다.")

    results: Dict[str, List[str]] = {p: [] for p in prompts}

    tasks: List[Tuple[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for prompt in prompts:
            for _ in range(max_workers if repeat_per_prompt == -1 else repeat_per_prompt):
                fut = ex.submit(
                    _worker_task,
                    prompt,
                    category,
                    model,
                    api_key,
                    filename_prefix,
                )
                tasks.append((prompt, fut))

        for prompt, fut in tasks:
            p, paths = fut.result()
            results[p].extend(paths)
            print(f"[done] '{p[:30]}...' -> {len(paths)}장 S3 업로드")

    return results


if __name__ == "__main__":
    # 카테고리별 프롬프트와 out_dir을 카테고리별로 다르게 설정
    categories = {
    "cat": [
        "Photorealistic sunrise rooftop shot of a tabby cat sitting on a warm metal railing, 35mm, f/2.0, ISO 200, 1/800s, golden rim light, gentle haze, no text or watermark.",
        "Photorealistic cat peeking out of a cardboard box on a living room floor, 50mm, f/1.8, ISO 400, 1/250s, side window light, soft bokeh, no text or watermark.",
        "Photorealistic reflection of a black cat in a wall mirror, 35mm, f/2.2, ISO 800, 1/125s, tungsten lamp mixed with daylight, handheld, no text or watermark.",
        "Photorealistic alley scene with a ginger cat near a puddle after rain, 28mm, f/2.8, ISO 320, 1/500s, overcast sky, subtle reflections, no text or watermark.",
        "Photorealistic close-up of a cat’s collar tag and fur texture, 85mm, f/2.8, ISO 200, 1/400s, diffused daylight, high micro-contrast, no text or watermark.",
        "Photorealistic candid through houseplants showing a cat on a windowsill, 50mm, f/2.0, ISO 320, 1/250s, backlit greenery bokeh, no text or watermark.",
        "Photorealistic top-down shot of a white cat lounging on tatami mat, 35mm, f/2.8, ISO 200, 1/160s, soft ambient light, natural colors, no text or watermark.",
        "Photorealistic cat curled beside a space heater glow, 35mm, f/1.8, ISO 1600, 1/100s, warm white balance, slight grain, no text or watermark."
    ],
    "icecream": [
        "Photorealistic cafe window seat shot of a strawberry sundae with condensation on the glass, 50mm, f/2.2, ISO 200, 1/250s, side window light, no text or watermark.",
        "Photorealistic close-up of soft-serve swirling out of a machine into a cone, 70mm, f/4, ISO 400, 1/500s, clean stainless backdrop, motion freeze, no text or watermark.",
        "Photorealistic child’s hands holding a chocolate-dipped cone at a park, 35mm, f/2.0, ISO 100, 1/1000s, bright daylight, gentle background blur, no text or watermark.",
        "Photorealistic macro detail of waffle cone texture with tiny sugar crystals, 100mm macro, f/5.6, ISO 200, 1/200s, softbox bounce, no text or watermark.",
        "Photorealistic two friends clinking ice cream cones on a city street, 28mm, f/2.8, ISO 400, 1/800s, late afternoon sun, lively bokeh, no text or watermark.",
        "Photorealistic car interior shot of a vanilla cone near the dashboard, 35mm, f/2.2, ISO 800, 1/160s, mixed lighting, natural reflections, no text or watermark.",
        "Photorealistic evening street festival with a mango sorbet cup under string lights, 50mm, f/1.8, ISO 2000, 1/200s, warm bokeh, handheld, no text or watermark.",
        "Photorealistic freezer door opening with frost swirl and a pistachio pint visible, 24mm, f/3.5, ISO 1600, 1/60s, cool white balance, no text or watermark."
    ],
    "rose": [
        "Photorealistic florist’s cooler seen through fogged glass with red and white roses, 35mm, f/2.8, ISO 800, 1/125s, cool lighting, condensation detail, no text or watermark.",
        "Photorealistic dried rose on linen fabric beside a window, 50mm, f/2.0, ISO 200, 1/200s, soft morning light, gentle shadows, no text or watermark.",
        "Photorealistic rose silhouette projected on a wall by direct sunlight, 35mm, f/4, ISO 100, 1/2000s, strong contrast, crisp edges, no text or watermark.",
        "Photorealistic candlelit macro of rose stamens and inner petals, 105mm macro, f/3.5, ISO 1600, 1/60s, warm flicker, handheld, no text or watermark.",
        "Photorealistic rose crown woven into hair at an outdoor garden, 85mm, f/2.0, ISO 200, 1/640s, backlit strands, natural color, no text or watermark.",
        "Photorealistic scattered rose petals on a marble staircase, 28mm, f/2.8, ISO 400, 1/250s, side light, subtle specular highlights, no text or watermark.",
        "Photorealistic single yellow rose under a glass cloche on a wooden desk, 50mm, f/2.5, ISO 320, 1/160s, soft desk lamp, reflections controlled, no text or watermark.",
        "Photorealistic raindrops sliding on a rose leaf with sharp vein detail, 100mm macro, f/5.6, ISO 400, 1/200s, overcast daylight, no text or watermark."
    ],
    "fruits": [
        "Photorealistic breakfast counter with a bowl of berries and yogurt, 35mm, f/2.8, ISO 200, 1/200s, side window light, natural tones, no text or watermark.",
        "Photorealistic pouring smoothie into a glass with banana and spinach beside, 50mm, f/3.2, ISO 400, 1/500s, motion freeze, kitchen light, no text or watermark.",
        "Photorealistic apple picking in an orchard with sunlit leaves, 35mm, f/2.0, ISO 200, 1/1000s, backlit flare, candid hands, no text or watermark.",
        "Photorealistic analog scale with a crate of oranges on a market counter, 28mm, f/4, ISO 400, 1/160s, ambient indoor light, no text or watermark.",
        "Photorealistic picnic bench with a freshly cut watermelon wedge, 35mm, f/2.8, ISO 100, 1/640s, bright midday sun, crisp texture, no text or watermark.",
        "Photorealistic fig cross-section on a ceramic plate, 85mm, f/4, ISO 200, 1/200s, window side-light, rich seeds detail, no text or watermark.",
        "Photorealistic grapes on the vine with translucent backlight, 70mm, f/2.8, ISO 100, 1/1000s, vineyard ambience, no text or watermark.",
        "Photorealistic stainless bowl reflection with assorted fruits on a counter, 24mm, f/3.5, ISO 800, 1/60s, cool kitchen light, subtle reflections, no text or watermark."
    ]
}
    # base_out_dir = "static/generated"

    all_results = {}
    for category, prompts in categories.items():
        # generate_images_concurrent 함수가 이제 'out_dir' 대신 'category'를 받습니다.
        results = generate_images_concurrent(
            prompts=prompts,
            category=category,
            repeat_per_prompt=1,
            max_workers=10,
            model=DEFAULT_MODEL,
            filename_prefix=None,
        )
        all_results[category] = results

    total_count = sum(len(paths) for res in all_results.values() for paths in res.values())
    print(f"\n--- 작업 완료: 총 {total_count}개의 이미지를 S3에 업로드했습니다. ---")
    for category, res in all_results.items():
        print(f"\n## 카테고리: {category}")
        for prompt, s3_paths in res.items():
            if s3_paths:
                # 생성된 S3 경로 중 첫 번째 것만 샘플로 출력
                print(f"  - s3://{S3_BUCKET_NAME}/{s3_paths[0]}")
