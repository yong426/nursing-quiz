# -*- coding: utf-8 -*-
"""오답 보강 보고서를 data.js에 일괄 적용한다 (병합된 문항의 보기 수정 전용).

에이전트는 data.js를 직접 수정하지 않고 보고서(JSON 배열)만 쓴다:
    [{"id": "m2-40-5", "c": ["보기1", ..., "보기5"]}, ...]

사용법:
    python tools/apply_bank_patch.py <보고서디렉터리> [--dry]

강제 규칙 (하나라도 어기면 그 항목은 적용하지 않고 오류로 남긴다)
  - 정답 보기 텍스트는 바꿀 수 없다 (정답은 이미 검수된 자산 — 오답만 보강)
  - 보기 5개, 빈 문자열 없음, 서로 중복 없음
  - id·ans·발문·해설·난이도는 건드리지 않는다
적용 후 정답 길이 단서(정답 ≥ 최장 오답×1.4 이고 +12자)가 남으면 경고로 알려 준다.
"""
import os, sys, glob, json, io, re, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_JS = os.path.join(ROOT, "data.js")


def read_data():
    raw = io.open(DATA_JS, encoding="utf-8").read()
    return json.loads(raw[raw.index("=") + 1:].rstrip().rstrip(";\n").rstrip(";"))


def write_data(data):
    with io.open(DATA_JS, "w", encoding="utf-8", newline="") as fh:
        fh.write("window.QUIZ_DATA = ")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")


def length_cue(c, ans):
    lens = [len(str(x)) for x in c]
    a = ans - 1
    others = lens[:a] + lens[a + 1:]
    return lens[a] >= max(others) * 1.4 and lens[a] - max(others) >= 12


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if not args:
        print(__doc__); return 1
    reports = sorted(glob.glob(os.path.join(args[0], "*.json")))
    if not reports:
        print("보고서를 찾지 못했다:", args[0]); return 1

    plan = {}
    for rp in reports:
        try:
            items = json.load(io.open(rp, encoding="utf-8"))
        except Exception as e:
            print(f"✗ 파싱 실패 {os.path.basename(rp)}: {e}"); return 1
        for x in items:
            plan[x["id"]] = (x["c"], os.path.basename(rp))
    print(f"보고서 {len(reports)}개 / 패치 {len(plan)}건")

    data = read_data()
    byid = {q["id"]: q for q in data["questions"]}
    applied, errors, still_cued = 0, [], []
    for qid, (new_c, src) in plan.items():
        q = byid.get(qid)
        if not q:
            errors.append(f"{qid}: data.js에 없음 [{src}]"); continue
        if not isinstance(new_c, list) or len(new_c) != 5 \
           or any(not str(x).strip() for x in new_c) \
           or len({str(x).strip() for x in new_c}) != 5:
            errors.append(f"{qid}: 보기 형식 위반 [{src}]"); continue
        a = q["ans"] - 1
        if str(new_c[a]).strip() != str(q["c"][a]).strip():
            errors.append(f"{qid}: 정답 보기가 변경됨 — 오답만 보강해야 한다 [{src}]"); continue
        q["c"] = [str(x).strip() for x in new_c]
        applied += 1
        if length_cue(q["c"], q["ans"]):
            still_cued.append(qid)

    if errors:
        print(f"\n오류 {len(errors)}건 — 해당 항목은 적용하지 않았다:")
        for e in errors[:30]:
            print("  ✗", e)
    if still_cued:
        print(f"\n⚠ 적용 후에도 길이 단서가 남은 문항 {len(still_cued)}건:",
              ", ".join(still_cued[:12]), "..." if len(still_cued) > 12 else "")
    print(f"\n적용 {applied}건 / 오류 {len(errors)}건" + ("  (dry-run)" if dry else ""))
    if not dry and applied:
        bak = DATA_JS + ".patch_bak"
        if not os.path.exists(bak):
            shutil.copy2(DATA_JS, bak)
        write_data(data)
        print("data.js 저장 (원본은 data.js.patch_bak). 다음: 재측정 → merge 없이 버전만 올려 배포")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
