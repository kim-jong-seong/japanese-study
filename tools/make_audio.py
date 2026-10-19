#!/usr/bin/env python3
"""VOICEVOX로 data.js의 모든 일본어를 m4a로 만들어 audio/ 에 저장한다.

사용법 (VOICEVOX 앱이 꺼져 있으면 자동으로 켜고, 끝나면 다시 끈다):
  python3 tools/make_audio.py                 # 없는 파일만 생성 (기본 화자)
  python3 tools/make_audio.py --keep          # 끝나도 VOICEVOX를 끄지 않음
  python3 tools/make_audio.py --speaker 13    # 화자 지정
  python3 tools/make_audio.py --list          # 화자 목록
  python3 tools/make_audio.py --samples       # 메인 문장을 여러 화자로 만들어 audio/_samples/ 에 저장 (고르기용)
  python3 tools/make_audio.py --force         # 전부 다시 생성 (화자 바꿨을 때)

파일 이름 규칙 (index.html 과 맞춰야 함):
  {id}.m4a          메인 문장
  {id}-w{n}.m4a     n번째 단어 (구두점 제외, 1부터)
  {id}-g{n}.m4a     n번째 문법 예문
  {id}-s.m4a        비슷한 표현
  {id}-s{n}.m4a     단어 바꾸기 예문 n
"""
import argparse, json, os, subprocess, sys, time, urllib.parse, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = "http://127.0.0.1:50021"
DEFAULT_SPEAKER = 13  # 青山龍星 (차분한 남성). 바꾸려면 --speaker 또는 audio/speaker.txt
SAMPLE_SPEAKERS = [13, 14, 52, 11, 8, 2, 53, 100, 94, 10, 108, 9]  # 차분한 편인 음성들


def api(path, data=None, params=None):
    url = ENGINE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=data, method="POST" if data is not None or path != "/speakers" else "GET")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def engine_alive():
    try:
        urllib.request.urlopen(ENGINE + "/version", timeout=2)
        return True
    except Exception:
        return False


def ensure_engine():
    """엔진이 없으면 VOICEVOX 앱을 켜고 기다린다. 이 함수가 켰으면 True."""
    if engine_alive():
        return False
    print("VOICEVOX 실행 중...", flush=True)
    subprocess.run(["open", "-a", "VOICEVOX"], check=True)
    for _ in range(40):
        time.sleep(3)
        if engine_alive():
            return True
    sys.exit("VOICEVOX 엔진이 2분 안에 뜨지 않았습니다. 앱을 직접 열어 보세요. (127.0.0.1:50021)")


def quit_app():
    subprocess.run(["osascript", "-e", 'quit app "VOICEVOX"'], check=False)


def synth(text, speaker):
    q = api("/audio_query", data=b"", params={"text": text, "speaker": speaker})
    return api("/synthesis", data=q, params={"speaker": speaker})


def write_m4a(path, wav_bytes):
    """wav → m4a(AAC 64kbps). 용량 1/10, Mac 내장 afconvert 사용."""
    tmp = path + ".wav"
    open(tmp, "wb").write(wav_bytes)
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", tmp, path], check=True)
    os.remove(tmp)


def load_sentences():
    out = subprocess.check_output(
        ["node", "-e", "global.window={};require('./data.js');console.log(JSON.stringify(window.SENTENCES))"],
        cwd=ROOT)
    return json.loads(out)


def clean(ja):
    return "".join(str(ja).split())


def jobs(sentences):
    for s in sentences:
        sid = s["id"]
        toks = [t for t in s.get("tokens", []) if not t.get("p")]
        yield sid, clean("".join(t["t"] for t in s.get("tokens", [])))
        for i, t in enumerate(toks, 1):
            yield f"{sid}-w{i}", clean(t["t"])
        for i, g in enumerate(s.get("grammar", []), 1):
            if g.get("ex"):
                yield f"{sid}-g{i}", clean(g["ex"]["ja"])
        sim = s.get("similar")
        if isinstance(sim, dict):
            yield f"{sid}-s", clean(sim["ja"])
            for i, m in enumerate(sim.get("more", []), 1):
                yield f"{sid}-s{i}", clean(m["ja"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speaker", type=int)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--samples", nargs="*", type=int, metavar="ID", help="메인 문장 샘플 생성. 번호를 주면 그 화자만")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--keep", action="store_true", help="끝나도 VOICEVOX를 끄지 않음")
    a = ap.parse_args()

    launched = ensure_engine()
    try:
        run(a)
    finally:
        if launched and not a.keep:
            quit_app()
            print("VOICEVOX 종료.")


def run(a):
    if a.list:
        for sp in json.loads(api("/speakers")):
            for st in sp["styles"]:
                print(f'{st["id"]:>3}  {sp["name"]}  ({st["name"]})')
        return

    audio_dir = os.path.join(ROOT, "audio")
    os.makedirs(audio_dir, exist_ok=True)
    sp_file = os.path.join(audio_dir, "speaker.txt")

    sentences = load_sentences()

    if a.samples is not None:
        d = os.path.join(audio_dir, "_samples")
        os.makedirs(d, exist_ok=True)
        text = next(jobs(sentences))[1]
        names = {st["id"]: f'{sp["name"]}-{st["name"]}' for sp in json.loads(api("/speakers")) for st in sp["styles"]}
        for sid in (a.samples or SAMPLE_SPEAKERS):
            path = os.path.join(d, f"{sid}_{names.get(sid, sid)}.m4a")
            write_m4a(path, synth(text, sid))
            print("sample:", os.path.relpath(path, ROOT))
        print("\n들어 보고 마음에 드는 번호로:  python3 tools/make_audio.py --speaker <번호> --force")
        return

    speaker = a.speaker
    if speaker is None and os.path.exists(sp_file):
        speaker = int(open(sp_file).read().strip() or DEFAULT_SPEAKER)
    if speaker is None:
        speaker = DEFAULT_SPEAKER
    open(sp_file, "w").write(str(speaker))

    made = skipped = 0
    for key, text in jobs(sentences):
        path = os.path.join(audio_dir, key + ".m4a")
        if os.path.exists(path) and not a.force:
            skipped += 1
            continue
        write_m4a(path, synth(text, speaker))
        made += 1
        print(f"{key:<22} {text}")
    print(f"\n화자 {speaker}: 생성 {made}개, 건너뜀 {skipped}개 → audio/")


if __name__ == "__main__":
    main()
