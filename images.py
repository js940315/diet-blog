"""팩트시트 → 실물 사진 N장.

카드뉴스(텍스트 얹은 이미지)는 쓰지 않는다. 실물 사진 그대로 간다.
하는 일은 세 가지뿐이다: 어느 버킷을 쓸지 고르고 → 순환 선택하고 → 정사각으로 자른다.

⚠️ 연예인 인물 사진은 쓰지 않는다. 초상권은 사진가의 저작권과 별개이고,
   이 시스템은 실명 자체를 안 쓰는 설계다. 사진은 음식·운동·공간 소재만.
"""

import os

import config as C
import photo_library as PL
from image_sourcing import prepare_photo

# 팩트시트의 한국어 식단/운동 표현 → 사진 버킷
FOOD_BUCKETS = {
    "닭가슴살": ("닭가슴살", "닭 가슴살", "닭가슴", "치킨브레스트"),
    "샐러드": ("샐러드", "채소", "야채", "생채소", "쌈"),
    "고구마": ("고구마", "군고구마", "찐고구마"),
    "단백질쉐이크": ("단백질", "프로틴", "쉐이크", "셰이크"),
    "그릭요거트": ("요거트", "요구르트", "그릭"),
    "아보카도": ("아보카도",),
    "두부": ("두부", "순두부", "콩"),
    "오트밀": ("오트밀", "귀리", "곡물", "현미", "잡곡"),
    "도시락": ("도시락", "밀프렙"),
}

EXERCISE_BUCKETS = {
    "필라테스": ("필라테스",),
    "요가": ("요가",),
    "러닝": ("러닝", "달리기", "조깅", "마라톤"),
    "웨이트": ("웨이트", "근력", "덤벨", "헬스", "무산소"),
    "홈트": ("홈트", "홈트레이닝", "집에서"),
    "수영": ("수영", "아쿠아"),
    "스트레칭": ("스트레칭", "유연"),
    "사이클": ("사이클", "자전거", "스피닝", "실내자전거"),
    "걷기": ("걷기", "산책", "만보", "워킹"),
}

SPACE_FOR = {
    "홈트": "공간홈트", "웨이트": "공간헬스장", "필라테스": "공간필라테스",
    "요가": "공간필라테스", "러닝": "공간야외", "걷기": "공간야외",
    "사이클": "공간헬스장", "수영": "공간헬스장", "스트레칭": "공간홈트",
}


def _match_bucket(texts, table):
    joined = " ".join(t for t in texts if t)
    for bucket, keys in table.items():
        if any(k in joined for k in keys):
            return bucket
    return None


def choose_buckets(fs: dict):
    """슬롯별 photo_category. 1번이 대표 사진(홈판 썸네일로 쓰인다)."""
    food = _match_bucket(fs.get("foods") or [], FOOD_BUCKETS)
    ex = _match_bucket(fs.get("exercises") or [], EXERCISE_BUCKETS)

    # 1번은 음식 컷을 앞세운다. 다이어트 글에서 가장 잘 눌리는 소재고,
    # 인물 없이도 주제가 한눈에 읽힌다.
    slots = [food or "식단레시피"]
    slots.append(ex or "운동홈트")
    slots.append(SPACE_FOR.get(ex, "공간주방" if food else "요요관리"))
    slots.append("셀럽감량" if food else "뷰티바디")
    return slots[: C.IMAGE_COUNT]


def _focus_from(align: str) -> str:
    """variation_seed의 9방향 정렬을 PIL 크롭 기준으로 옮긴다."""
    if "YMin" in align:
        return "top"
    if "YMax" in align:
        return "bottom"
    return "center"


def render(title, fs, date_tag, outdir):
    """실물 사진 세트를 만든다. 반환: [{slot, category, photo, file}]"""
    buckets = choose_buckets(fs)
    used, made = set(), []

    for seq, category in enumerate(buckets, 1):
        fname = PL.pick_photo(category, date_tag, seq, exclude=used)
        if not fname:
            print(f"  [건너뜀] {seq}번 — '{category}' 버킷에 사진이 없습니다.")
            continue
        src = os.path.join(PL.PHOTO_DIR, fname)
        if not os.path.exists(src):
            print(f"  [건너뜀] {seq}번 — 파일 없음: {fname}")
            continue

        used.add(fname)
        var = PL.variation_seed(fname, date_tag, seq)
        dst = os.path.join(outdir, f"{seq}번 사진.jpg")
        try:
            prepare_photo(src, dst, size=C.IMAGE_SIZE,
                          focus=_focus_from(var["align"]),
                          grade=C.PHOTO_GRADE, vignette=C.PHOTO_VIGNETTE)
        except Exception as e:
            print(f"  [실패] {seq}번 가공 실패: {str(e)[:60]}")
            continue

        PL.record_usage(category, fname, date_tag, seq)
        made.append({"slot": seq, "category": category,
                     "photo": fname, "file": os.path.basename(dst)})
        print(f"  {seq}번 사진.jpg  [{category}] {fname}")

    if not made:
        print("  [주의] 사진이 한 장도 없습니다. 먼저 소싱하세요:")
        print("         python build_photo_library.py --per 3")
    return made


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("슬롯 버킷:", choose_buckets({
        "foods": ["고구마", "닭가슴살 샐러드"],
        "exercises": ["필라테스", "아침 산책"],
    }))
    print("빈 팩트시트:", choose_buckets({"foods": [], "exercises": []}))
