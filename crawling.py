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

dotenv.load_dotenv()
DEFAULT_MODEL = "gemini-2.5-flash-image-preview"


def _slugify(text: str) -> str:
    """파일명에 안전하도록 간단 슬러그화."""
    text = text.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = re.sub(r"^-+|-+$", "", text)
    return text[:60] if text else "image"


def _ensure_dir(path: Union[str, Path]) -> Path:  # ← 변경
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_image_once(
    prompt: str,
    out_dir: Union[str, Path],          # ← 변경
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    filename_prefix: Optional[str] = None,
) -> List[Path]:
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

    out_dir = _ensure_dir(out_dir)
    base = filename_prefix or _slugify(prompt)
    ts = int(time.time())
    saved_paths: List[Path] = []

    # 후보(candidate) 내 content.parts 에 이미지 파트가 들어있음
    # 텍스트 파트가 섞일 수 있어 분기 처리
    candidate = response.candidates[0] if response.candidates else None
    if not candidate or not getattr(candidate, "content", None):
        return saved_paths  # 이미지가 없을 수 있음

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
                fpath = out_dir / fname
                img.save(fpath)
                saved_paths.append(fpath)
                idx_in_parts += 1
            except Exception as e:
                print(f"[warn] 이미지 저장 실패: {e}")

    return saved_paths


def _worker_task(
    prompt: str,
    out_dir: Union[str, Path],  # ← 변경
    model: str,
    api_key: Optional[str],
    filename_prefix: Optional[str],
) -> Tuple[str, List[Path]]:
    """스레드 워커: 프롬프트 1건 생성-저장."""
    try:
        paths = generate_image_once(
            prompt=prompt,
            out_dir=out_dir,
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
    out_dir: Union[str, Path],          # ← 변경
    *,
    repeat_per_prompt: int = 1,
    max_workers: int = 4,
    model: str = DEFAULT_MODEL,
    api_key: Optional[str] = None,
    filename_prefix: Optional[str] = None,
) -> Dict[str, List[Path]]:
    """
    여러 프롬프트를 동시 병렬로 요청하여 이미지 저장.
    - prompts: 프롬프트 목록
    - out_dir: 저장 폴더
    - repeat_per_prompt: 각 프롬프트를 몇 번 반복 호출할지(다양한 샘플 원할 때 >1)
    - max_workers: 동시 스레드 수
    - model, api_key, filename_prefix: 옵션
    반환: {prompt: [Path, ...]} 매핑
    """
    out_dir = _ensure_dir(out_dir)
    api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되어 있지 않습니다.")

    results: Dict[str, List[Path]] = {p: [] for p in prompts}

    tasks: List[Tuple[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for prompt in prompts:
            for _ in range(max_workers if repeat_per_prompt == -1 else repeat_per_prompt):
                fut = ex.submit(
                    _worker_task,
                    prompt,
                    out_dir,
                    model,
                    api_key,
                    filename_prefix,
                )
                tasks.append((prompt, fut))

        for prompt, fut in tasks:
            p, paths = fut.result()
            results[p].extend(paths)
            print(f"[done] '{p}' -> {len(paths)}장 저장")

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
    base_out_dir = "static/generated"

    all_results = {}
    for category, prompts in categories.items():
        out_dir = os.path.join(base_out_dir, category)
        results = generate_images_concurrent(
            prompts=prompts,
            out_dir=out_dir,
            repeat_per_prompt=2,
            max_workers=20,
            model=DEFAULT_MODEL,
            filename_prefix=None,
        )
        all_results[category] = results

    total = sum(len(v) for v in results.values())
    print(f"\n총 {total}장 저장됨.")
    for p, paths in results.items():
        print(f"- {p} :")
        for path in paths:
            print(f"    {path}")
