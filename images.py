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

def _match_buckets(texts, table):
    """팩트시트에 언급된 식품과 맞는 버킷을 언급 순서대로."""
    joined = " ".join(t for t in texts if t)
    return [b for b, keys in table.items() if any(k in joined for k in keys)]


def choose_buckets(fs: dict, date_tag: str = ""):
    """슬롯별 photo_category. 1번이 대표 사진(홈판 썸네일로 쓰인다).

    ⚠️ 음식 버킷만 쓴다. 운동·공간·인물 컷은 사람이 크게 나와서 글과 따로 놀고,
       남의 몸 사진을 다이어트 글에 붙이는 모양새가 된다.
       팩트시트에 식품 언급이 없으면 기본 버킷을 날짜에 따라 돌려 쓴다.
    """
    picked = [b for b in _match_buckets(fs.get("foods") or [], FOOD_BUCKETS)
              if b in C.FOOD_BUCKETS_ONLY]

    # 남는 슬롯은 기본 음식 버킷에서 채운다. 날짜로 시작점을 밀어
    # 매일 같은 조합이 나오지 않게 한다.
    pool = list(C.FOOD_BUCKETS_ONLY)
    if pool:
        offset = sum(ord(c) for c in date_tag) % len(pool)
        pool = pool[offset:] + pool[:offset]
    for b in pool:
        if len(picked) >= C.IMAGE_COUNT:
            break
        if b not in picked:
            picked.append(b)
    return picked[: C.IMAGE_COUNT]


def _focus_from(align: str) -> str:
    """variation_seed의 9방향 정렬을 PIL 크롭 기준으로 옮긴다."""
    if "YMin" in align:
        return "top"
    if "YMax" in align:
        return "bottom"
    return "center"


def _day_used_path(date_tag):
    return os.path.join(C.ROOT, "state", f"used_photos_{date_tag}.json")


def _load_day_used(date_tag):
    """같은 날 다른 슬롯이 이미 쓴 사진들. 하루 10편 체제에서 슬롯 간 중복 방지.

    슬롯들이 병렬로 돌면 서로의 선택을 못 보고 같은 사진을 집는다(실측 13건).
    날짜 단위 사용 기록을 두고 뽑기 전에 제외한다.
    """
    import json
    p = _day_used_path(date_tag)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()


def _save_day_used(date_tag, used):
    import json
    with open(_day_used_path(date_tag), "w", encoding="utf-8") as f:
        json.dump(sorted(used), f, ensure_ascii=False, indent=1)


def render(title, fs, date_tag, outdir):
    """실물 사진 세트를 만든다. 반환: [{slot, category, photo, file}]"""
    buckets = choose_buckets(fs, date_tag)
    used, made = _load_day_used(date_tag), []

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
        _save_day_used(date_tag, used)
        made.append({"slot": seq, "category": category,
                     "photo": fname, "file": os.path.basename(dst)})
        print(f"  {seq}번 사진.jpg  [{category}] {fname}")

    if len(made) < C.IMAGE_COUNT:
        print(f"  [알림] 음식 사진 {len(made)}장 (목표 {C.IMAGE_COUNT}장). "
              "모자라면 모자란 대로 나갑니다.")
    if not made:
        print("         버킷을 채우려면: python build_photo_library.py --per 3")
    return made


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    print("식품 언급 있음:", choose_buckets(
        {"foods": ["고구마", "닭가슴살 샐러드"], "exercises": ["필라테스"]}, "0804"))
    print("식품 언급 없음:", choose_buckets({"foods": [], "exercises": []}, "0804"))
    print("다른 날짜   :", choose_buckets({"foods": [], "exercises": []}, "0806"))
    print("\n운동 버킷이 섞이지 않는지 확인 — 위 결과에 아래 단어가 없어야 한다:")
    print("  운동홈트 공간주방 공간홈트 셀럽감량 뷰티바디 스트레칭 필라테스")
