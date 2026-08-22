# -*- coding: utf-8 -*-
"""검수를 통과한 문항을 data.js에 병합하고 버전을 올린다.

사용법:
    python tools/merge.py tools/incoming/*.json            # 병합 + 버전 자동 상향
    python tools/merge.py tools/incoming/*.json --dry-run  # 결과만 확인

하는 일
  1) validate.py와 같은 스키마·중복 검사를 다시 한 번 (안전장치)
  2) 난이도(d)가 없는 문항은 기본값 2(중간)로 채운다
  3) id를 `g<파일순번>-<문항번호>` 형태로 새로 부여 (기존 id와 충돌하지 않게)
  4) data.js 갱신 + index.html의 APP_VERSION / data.js?v= / version.json 동시 상향
"""
import sys, os, json, re, glob, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA_JS = os.path.join(ROOT, "data.js")
INDEX = os.path.join(ROOT, "index.html")
VERSION_JSON = os.path.join(ROOT, "version.json")

sys.path.insert(0, HERE)
from validate import TOPIC2SUBJ, norm, BAD_CHOICE   # noqa


def read_data():
    raw = open(DATA_JS, encoding="utf-8").read()
    body = raw[raw.index("=") + 1:].rstrip().rstrip(";\n").rstrip(";")
    return json.loads(body)


def write_data(data):
    with open(DATA_JS, "w", encoding="utf-8", newline="") as fh:
        fh.write("window.QUIZ_DATA = ")
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write(";\n")


def bump_versions(n_questions):
    today = datetime.date.today().strftime("%Y.%m.%d")
    html = open(INDEX, encoding="utf-8").read()
    cur = re.search(r'APP_VERSION = "([^"]+)"', html).group(1)
    # 같은 날짜면 마지막 숫자를 올리고, 날짜가 바뀌면 .1로 시작
    if cur.startswith(today):
        parts = cur.split(".")
        new = ".".join(parts[:3] + [str(int(parts[3]) + 1)]) if len(parts) == 4 else today + ".1"
    else:
        new = today + ".1"
    html = html.replace(f'APP_VERSION = "{cur}"', f'APP_VERSION = "{new}"')
    html = re.sub(r'data\.js\?v=[^"]*', f"data.js?v={n_questions}", html)
    open(INDEX, "w", encoding="utf-8", newline="").write(html)
    open(VERSION_JSON, "w", encoding="utf-8", newline="").write(json.dumps({
        "app": new, "data": str(n_questions),
        "note": "index.html의 APP_VERSION과 app 값을 항상 같이 올린다. "
                "data.js를 바꾸면 index.html의 data.js?v= 값과 data 값도 함께 올린다."
    }, ensure_ascii=False, indent=2) + "\n")
    return cur, new


def main():
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    dry = "--dry-run" in sys.argv
    paths = []
    for a in args:
        paths.extend(sorted(glob.glob(a)))
    if not paths:
        print("사용법: python tools/merge.py <문항 json...> [--dry-run]"); return 1

    data = read_data()
    qs = data["questions"]
    existing_norm = {norm(q["q"]): q["id"] for q in qs}
    used_ids = {q["id"] for q in qs}
    before = len(qs)

    added, skipped = 0, []
    for fi, p in enumerate(paths, 1):
        items = json.load(open(p, encoding="utf-8"))
        for i, it in enumerate(items, 1):
            # 안전장치: 스키마·중복 재검사
            if it.get("t") not in TOPIC2SUBJ or len(it.get("c", [])) != 5 \
               or not isinstance(it.get("ans"), int) or not 1 <= it["ans"] <= 5 \
               or not str(it.get("q", "")).strip() or not str(it.get("exp", "")).strip() \
               or any(BAD_CHOICE.search(str(c)) for c in it["c"]) \
               or len({norm(c) for c in it["c"]}) != 5:
                skipped.append(f"{os.path.basename(p)}#{i} 스키마 위반"); continue
            key = norm(it["q"])
            if key in existing_norm:
                skipped.append(f"{os.path.basename(p)}#{i} 중복(={existing_norm[key]})"); continue
            qid = f"g{fi}-{i}"
            while qid in used_ids:
                qid += "x"
            used_ids.add(qid); existing_norm[key] = qid
            d = it.get("d")
            qs.append({
                "id": qid, "s": TOPIC2SUBJ[it["t"]], "t": it["t"],
                "q": str(it["q"]).strip(), "c": [str(c).strip() for c in it["c"]],
                "ans": it["ans"], "exp": str(it["exp"]).strip(),
                "d": d if d in (1, 2, 3) else 2,
            })
            added += 1

    per_subj = collections.Counter(q["s"] for q in qs)
    per_diff = collections.Counter(q.get("d", 2) for q in qs)
    print(f"{before} → {len(qs)}문항 (추가 {added}, 건너뜀 {len(skipped)})")
    print("과목별:", dict(per_subj))
    print("난이도:", dict(sorted(per_diff.items())), " (1쉬움 2중간 3어려움)")
    for s in skipped[:20]:
        print("  - 건너뜀:", s)

    # 모의고사 쿼터 실현 가능성 점검
    MIX = {"노멀": {"기초": [.641, .327, .033], "보건": [.505, .419, .076],
                    "공중": [.35, .393, .257], "실기": [.448, .462, .09]},
           "하드": {k: [.2, .5, .3] for k in ("기초", "보건", "공중", "실기")}}
    MOCK = {"기초": 35, "보건": 15, "공중": 20, "실기": 35}
    for name, mix in MIX.items():
        short = []
        for s, m in MOCK.items():
            inv = collections.Counter(q.get("d", 2) for q in qs if q["s"] == s)
            for d in (1, 2, 3):
                need = round(m * mix[s][d - 1])
                if inv[d] < need:
                    short.append(f"{s}d{d}({inv[d]}<{need})")
        print(f"{name} 모드 쿼터:", "충족" if not short else "부족 " + ", ".join(short))

    if dry:
        print("\n--dry-run: 아무것도 저장하지 않았다.")
        return 0
    if not added:
        print("\n추가된 문항이 없어 저장하지 않았다.")
        return 0

    write_data(data)
    old, new = bump_versions(len(qs))
    print(f"\ndata.js 저장 완료. 버전 {old} → {new}")
    print("다음: git add -A && git commit && git push origin main main:gh-pages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
