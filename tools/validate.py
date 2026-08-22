# -*- coding: utf-8 -*-
"""새로 만든 문항 파일을 검사한다 (병합 전 필수).

사용법:
    python tools/validate.py tools/incoming/nq3_배뇨배변.json [...]
    python tools/validate.py tools/incoming/*.json

검사 항목
  1) JSON 파싱 / 스키마 (t, q, c(5개), ans(1~5), exp)
  2) 주제 라벨(t)이 허용된 27개 중 하나인지
  3) 보기 중복, 빈 문자열, "모두 옳다"류 보기
  4) 기존 data.js 1,3xx문항과의 중복 (발문 정규화 + 유사도)
  5) 파일 내부 중복
  6) 정답 번호 분포 / 부정형 비율 / 교재별로 갈리는 위험 표현 경고

종료 코드: 오류가 있으면 1 (병합하지 말 것), 경고만이면 0
"""
import sys, os, json, re, glob, collections, difflib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_JS = os.path.join(ROOT, "data.js")

TOPICS = {
    "기초": ["간호관리·윤리·역사", "해부생리(구조·신경·감각)", "해부생리(내장기관)",
             "성인간호(내과)", "성인간호(외과·수술)", "모성간호", "아동간호", "노인간호",
             "약물·영양", "치과·한방"],
    "보건": ["보건행정·의료보장", "보건교육·산업보건", "모자보건·지역사회·방문"],
    "공중": ["감염병·역학", "환경·식품위생", "인구·통계·건강증진",
             "의료법규(의료법)", "의료법규(관계법규)"],
    "실기": ["활력징후·신체계측", "감염관리·무균술", "투약·검체", "위생·체위·안전",
             "배뇨·배변", "영양·식사돕기", "상처·붕대·열냉요법", "산소·흡인·호흡", "응급처치·CPR"],
}
TOPIC2SUBJ = {t: s for s, ts in TOPICS.items() for t in ts}

# "위 모두"는 앞에 다른 한글이 붙으면 다른 뜻이다 ("부위 모두", "상위 모두") — 오탐지를 막는다
BAD_CHOICE = re.compile(r"(모두\s*(옳|맞|틀|아니))|(정답\s*없)|((?<![가-힣])위\s*모두)")
# 교재별로 값이 갈려 정답 근거로 쓰면 위험한 표현
# 각 항목: (반드시 모두 매칭돼야 하는 정규식 목록, 경고 문구)
RISKY = [
    ([r"손\s*씻|손위생", r"\d+\s*초"], "내과적 손씻기 '시간'(교재별 10~60초로 갈림) — 시간 대신 절차·방향으로"),
    ([r"경관영양|영양액|위관영양", r"체온"], "경관영양액 '체온' 기준(근거지침은 '차갑지 않은 실온')"),
    ([r"단순도뇨|도뇨관|넬라톤", r"(남성|남자)", r"(1[89]|20)\s*cm"], "남성 도뇨 삽입 18~20cm(표준 12~18cm)"),
    ([r"더운물|온요법|물주머니", r"(5[0-9]|60)\s*(℃|도)"], "더운물주머니 50℃ 이상(표준 성인 46~52℃)"),
    ([r"고막|이개|귓바퀴", r"(만\s*)?3\s*세"], "고막체온 경계 나이(만 3세) — 18개월 등으로 바꿀 것"),
    ([r"억제대|신체보호대", r"손가락\s*1\s*개"], "억제대 여유 '손가락 1개' 단정(1~2개로 갈림)"),
]
RISKY = [([re.compile(p) for p in pats], why) for pats, why in RISKY]


def norm(s):
    return re.sub(r"[\s​]+", "", str(s))


def load_existing():
    if not os.path.exists(DATA_JS):
        return []
    raw = open(DATA_JS, encoding="utf-8").read()
    data = json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";\n").rstrip(";"))
    return data.get("questions", [])


def choice_key(choices):
    """보기 구성을 순서와 무관하게 식별하는 키 (앱이 보기 순서를 런타임에 섞으므로 순서는 무의미)."""
    return tuple(sorted(norm(c) for c in choices))


def check_file(path, existing_norm, existing_q, existing_csets, seen_in_run, seen_csets):
    errors, warns = [], []
    try:
        items = json.load(open(path, encoding="utf-8"))
    except Exception as e:
        return [f"JSON 파싱 실패: {e}"], [], 0
    if not isinstance(items, list):
        return ["최상위가 배열이 아님"], [], 0

    ans_dist = collections.Counter()
    neg = 0
    for i, it in enumerate(items):
        tag = f"[{os.path.basename(path)} #{i}]"
        if not isinstance(it, dict):
            errors.append(f"{tag} 객체가 아님"); continue
        for k in ("t", "q", "c", "ans", "exp"):
            if k not in it:
                errors.append(f"{tag} '{k}' 키 없음")
        if any(k not in it for k in ("t", "q", "c", "ans", "exp")):
            continue
        if it["t"] not in TOPIC2SUBJ:
            errors.append(f"{tag} 허용되지 않은 주제 라벨: {it['t']!r}")
        if not isinstance(it["c"], list) or len(it["c"]) != 5:
            errors.append(f"{tag} 보기가 5개가 아님 ({len(it.get('c', []))}개)"); continue
        if not isinstance(it["ans"], int) or not 1 <= it["ans"] <= 5:
            errors.append(f"{tag} ans가 1~5 정수가 아님: {it['ans']!r}"); continue
        if len({norm(c) for c in it["c"]}) != 5:
            errors.append(f"{tag} 보기 중복")
        for c in it["c"]:
            if not str(c).strip():
                errors.append(f"{tag} 빈 보기")
            if BAD_CHOICE.search(str(c)):
                errors.append(f"{tag} 금지된 보기 유형: {str(c)[:30]!r}")
        if not str(it["q"]).strip() or not str(it["exp"]).strip():
            errors.append(f"{tag} 발문 또는 해설이 빈 문자열")

        ans_dist[it["ans"]] += 1
        if re.search(r"않은|아닌|틀린|잘못", str(it["q"])):
            neg += 1

        key = norm(it["q"])
        if key in seen_in_run:
            errors.append(f"{tag} 이번 배치 안에서 발문 중복 ({seen_in_run[key]})")
        else:
            seen_in_run[key] = tag
        if key in existing_norm:
            errors.append(f"{tag} 기존 문제은행과 발문 중복 (id={existing_norm[key]})")
        else:
            near = difflib.get_close_matches(key, existing_q, n=1, cutoff=0.92)
            if near:
                warns.append(f"{tag} 기존 문항과 매우 유사 — 확인 필요")

        # 보기 5개가 기존 문항과 완전히 동일하면 사실상 같은 문제일 가능성이 높다.
        # (개념 분류를 여러 사례로 묻는 정상적인 경우도 있어 오류가 아니라 경고로 처리)
        ck = choice_key(it["c"])
        if ck in seen_csets:
            warns.append(f"{tag} 이번 배치 안에 보기 구성이 완전히 같은 문항이 있음 ({seen_csets[ck]}) — 사실상 같은 문제인지 확인")
        else:
            seen_csets[ck] = tag
        if ck in existing_csets:
            ids = existing_csets[ck]
            warns.append(f"{tag} 기존 문항과 보기 5개가 완전히 동일 (id={', '.join(ids[:3])}"
                         f"{' 외' if len(ids) > 3 else ''}) — 사실상 같은 문제면 다른 개념으로 교체")

        blob = str(it["q"]) + " " + " ".join(map(str, it["c"])) + " " + str(it["exp"])
        for pats, why in RISKY:
            if all(p.search(blob) for p in pats):
                warns.append(f"{tag} 위험 표현: {why}")

    n = len(items)
    if n:
        worst = max(ans_dist.values()) if ans_dist else 0
        if worst > n * 0.4:
            warns.append(f"[{os.path.basename(path)}] 정답 번호 편중: {dict(sorted(ans_dist.items()))}")
        if neg > n * 0.3:
            warns.append(f"[{os.path.basename(path)}] 부정형 비율 높음: {neg}/{n}")
    return errors, warns, n


def main():
    paths = []
    for a in sys.argv[1:]:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print("사용법: python tools/validate.py <문항 json 파일...>"); return 1

    existing = load_existing()
    existing_norm = {norm(q["q"]): q["id"] for q in existing}
    existing_q = list(existing_norm.keys())
    existing_csets = collections.defaultdict(list)
    for q in existing:
        if isinstance(q.get("c"), list) and len(q["c"]) == 5:
            existing_csets[choice_key(q["c"])].append(q["id"])
    print(f"기존 문제은행: {len(existing)}문항 (보기 구성 {len(existing_csets)}종)\n")

    all_err, all_warn, total = [], [], 0
    seen_in_run, seen_csets = {}, {}
    for p in paths:
        err, warn, n = check_file(p, existing_norm, existing_q, existing_csets, seen_in_run, seen_csets)
        total += n
        all_err += err; all_warn += warn
        print(f"{os.path.basename(p):40s} {n:4d}문항  오류 {len(err):3d}  경고 {len(warn):3d}")

    print(f"\n합계 {total}문항 / 오류 {len(all_err)}건 / 경고 {len(all_warn)}건")
    for e in all_err[:80]:
        print("  ✗", e)
    if len(all_err) > 80:
        print(f"  ... 오류 {len(all_err)-80}건 더")
    for w in all_warn[:40]:
        print("  ⚠", w)
    if len(all_warn) > 40:
        print(f"  ... 경고 {len(all_warn)-40}건 더")

    if all_err:
        print("\n오류가 있으므로 병합하지 마라. 고친 뒤 다시 실행할 것.")
        return 1
    print("\n스키마·중복 검사 통과. 다음: 다른 모델로 정확성 검수(tools/prompt_verify.md) → tools/merge.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
