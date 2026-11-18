"""멈칫 클릭 시안 캡처 + 동작 단언. 실행: .venv/bin/python prototype/capture.py
단언이 하나라도 실패하면 종료 코드 1."""
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "prototype/web/index.html").as_uri()
OUT = ROOT / "docs/week11/prototype"
OUT.mkdir(parents=True, exist_ok=True)
HASHES = ["onboarding", "chat", "judging", "card", "charge", "cooldown", "cooldown-done",
          "trusted-preview", "record", "game-pay", "game-pay-false-positive", "settings-off"]
fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 412, "height": 915}, device_scale_factor=2)
    requests = []
    ctx.on("request", lambda r: requests.append(r.url))

    def open_page(query, h):
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.goto(f"{PAGE}{query}#{h}")
        page.wait_for_timeout(300)
        return page, errs

    for h in HASHES:
        page, errs = open_page("", h)
        check(not errs, f"#{h} JS 오류 없음 {errs}")
        # 글자 잘림: 스크롤 영역이 아닌 요소가 안쪽 내용이 넘치는지
        clipped = page.evaluate("""()=>[...document.querySelectorAll('.phone *')].filter(e=>{
          const s=getComputedStyle(e);return e.scrollWidth>e.clientWidth+1&&e.clientWidth>0&&s.overflowX!=='auto'&&e.tagName!=='INPUT'&&e.tagName!=='TEXTAREA'}).map(e=>e.className+':'+e.textContent.slice(0,20))""")
        check(not clipped, f"#{h} 가로 넘침 없음 {clipped}")
        vclip = page.evaluate("""()=>[...document.querySelectorAll('.phone *')].filter(e=>{
          const s=getComputedStyle(e);const hid=s.overflowY==='hidden'||s.overflowY==='clip';
          const scroller=['body','chat','game'].some(c=>e.classList.contains(c));
          return e.clientHeight>0&&e.scrollHeight>e.clientHeight+1&&(hid||scroller)&&!(e.classList.contains('body')&&document.querySelector('#in-promise'))}).map(e=>e.className+':'+e.textContent.slice(0,20))""")
        check(not vclip, f"#{h} 세로 잘림·스크롤 없음 {vclip}")
        sheetbottom = page.evaluate("""()=>[...document.querySelectorAll('.sheet,.body,.foot')].every(e=>e.getBoundingClientRect().bottom<=915.5)""")
        check(sheetbottom, f"#{h} 시트·본문이 뷰포트 아래로 안 넘침")
        page.screenshot(path=str(OUT / f"{h}.png"))
        if h == "card":
            check(page.locator("#btn-exit").is_enabled(), "#card 나가기 활성")
            check(page.locator("#btn-continue").is_disabled(), "#card 계속 보기 비활성(멈칫하기)")
            check("불법 도박 사이트일 가능성이 높아요" in page.inner_text(".sheet .hdr"), "#card 헤더 문구")
            ct = page.inner_text(".sheet")
            check("지켜 낸 날 3일" in ct and "멈춰서 지킨 돈 15만 원" in ct, "#card 지켜 낸 날·멈춰서 지킨 돈")
            check("잃은 돈 합계" not in ct and "끊은 지" not in ct, "#card 기본값에 잃은 돈 합계·끊은 지 없음")
            check(page.locator("#chips .chip").count() >= 3, "#card 근거 칩 3개 이상")
        body_text = page.inner_text("body")
        check("화면을 보" not in body_text and "화면을 봐" not in body_text and "중독" not in body_text, f"#{h} '화면을 본다'·'중독' 표현 없음")
        if h in ("cooldown", "cooldown-done", "trusted-preview"):
            check("상품권은 넣지 않고 그대로 두면 돼요." in body_text, f"#{h} 상품권 안내 한 줄")
            check("지금까지 멈춰서 지킨 돈" in body_text and "지금까지 잃은 돈" not in body_text, f"#{h} 기본 통계 = 지킨 돈, 잃은 돈 행 없음")
        if h == "onboarding":
            check("저장하지 않고 바로 지워요" in body_text, "#onboarding 자동 확인·저장 안 함 설명")
            check(page.locator("[data-ex]").count() == 2, "#onboarding 약속 예시 칩 2개")
            check(page.locator("#in-showlost").is_checked() is False and page.locator("#in-amount").count() == 0, "#onboarding 잃은 돈 합계 기본 끔(금액 입력 숨김)")
            check(page.locator("[name=noff][value='0']").is_checked(), "#onboarding 끌 때 알림 기본 = 알리지 않음")
            page.evaluate("document.querySelector('.body').scrollTop=9999")
            page.screenshot(path=str(OUT / "onboarding-bottom.png"))
        if h == "cooldown-done":
            check(page.locator("#btn-continue").is_enabled(), "#cooldown-done 계속 활성")
        if h == "trusted-preview":
            check("충전 시도 · 5만 원 · 카지노형" in page.inner_text("body"), "#trusted-preview 보낼 내용 미리보기")
            g = page.inner_text("#guide")
            check("혼내기 전에 먼저 들어 주세요" in g and "1336" in g, "#trusted-preview 받는 분께 함께 가는 안내")
        if h == "onboarding":
            check("도박" not in page.inner_text(".hdr"), "#onboarding 헤더에 '도박' 없음")
            check(page.inner_text("#appname") == "멈칫", "앱 이름 멈칫")
        if h == "game-pay":
            check(page.locator("#fpLink").count() == 1, "#game-pay 정상 게임 표시 링크")
            check(page.locator("#btn-exit").count() == 0, "#game-pay 개입 없음")
        if h == "game-pay-false-positive":
            ft = page.inner_text("#fpToast")
            check("잘못 잡아서 미안해요. 이 게임은 앞으로 확인하지 않을게요." in ft and "신뢰인에게는 아무것도 가지 않아요." in ft and "하루 3번까지" in ft, "#game-pay-false-positive 사과·신뢰인 없음·하루 3번")
        if h == "settings-off":
            pb = page.inner_text("#pendingBox")
            check("24시간 뒤" in pb and "신뢰인에게는 아무것도 가지 않아요" in pb and "보호 꺼짐" not in pb,
                  "#settings-off 24시간 뒤·기본은 신뢰인에게 안 감")
        page.close()

    page, _ = open_page("", "cooldown")
    check(page.locator("#btn-continue").is_disabled(), "#cooldown(멈칫하기) 계속 비활성")
    page.close()
    page, _ = open_page("", "card")
    check(page.locator("#btn-continue").is_disabled(), "#card 로드 직후 계속 보기 비활성(60초 잠금)")
    page.close()
    page, _ = open_page("?speed=10", "card")
    page.wait_for_timeout(6500)
    check(page.locator("#btn-continue").is_enabled(), "?speed=10#card 6초 뒤 계속 보기 활성")
    page.close()
    page, _ = open_page("?level=block", "card")
    check(page.locator("#btn-continue").is_disabled(), "?level=block#card 계속 보기 비활성(멈칫하기와 같은 60초 잠금)")
    page.close()
    page, _ = open_page("?level=notify", "cooldown-done")
    check(page.locator("#btn-continue").is_enabled() and page.locator("#count").count() == 0, "?level=notify#cooldown-done 계속 활성")
    page.close()
    page, _ = open_page("?speed=10", "cooldown")
    page.wait_for_timeout(1500)
    before = page.inner_text("#count")
    page.click("#btn-trusted"); page.wait_for_selector("#tp-cancel"); page.click("#tp-cancel")
    page.wait_for_selector("#btn-trusted")
    after = page.inner_text("#count")
    mmss = lambda t: int(t.split(":")[0]) * 60 + int(t.split(":")[1])
    check(mmss(after) <= mmss(before) and mmss(after) < 30, f"신뢰인 미리보기 열고 닫아도 쿨다운 안 리셋 ({before} -> {after})")
    page.wait_for_timeout(2200)
    check(page.locator("#btn-continue").is_enabled(), "미리보기 후에도 카운트가 끝나면 계속 활성")
    page.close()
    # 온보딩에서 옵션을 켜고 흐름 진행
    page, _ = open_page("?speed=10", "onboarding")
    page.click("#in-showlost"); page.wait_for_selector("#in-amount")
    page.click("[name=noff][value='1']")
    page.click("[data-ex='0']")
    check(page.input_value("#in-promise") == "내 용돈은 내가 쓰고 싶은 데 쓴다", "예시 칩 누르면 약속 입력칸에 들어감")
    page.click("#start"); page.click("#link"); page.wait_for_selector("#btn-exit", timeout=3000)
    check("잃은 돈 합계 180만 원" in page.inner_text(".sheet"), "잃은 돈 합계 켜면 카드에 표시")
    page.evaluate("location.hash='charge'"); page.click("#chargeGo")
    check("지금까지 잃은 돈185만 원" in page.inner_text(".sheet").replace("\n", ""), "잃은 돈 합계 켜면 쿨다운에 185만 원")
    page.evaluate("location.hash='settings-off'"); page.wait_for_selector("#pendingBox")
    check("○○ 님이 잠시 쉬겠다고 했어요" in page.inner_text("#pendingBox"), "끌 때 알림 선택 시 부드러운 문구")
    page.close()
    page, _ = open_page("?level=block", "cooldown")
    check(page.locator("#btn-continue").count() == 0, "?level=block#cooldown 계속 버튼 없음")
    page.close()
    page, _ = open_page("?level=notify", "cooldown")
    check(page.locator("#btn-continue").is_enabled(), "?level=notify#cooldown 계속 즉시 활성")
    page.close()
    page, _ = open_page("?level=notify", "card")
    check(page.locator("#btn-continue").is_enabled(), "?level=notify#card 계속 보기 즉시 활성")
    page.close()
    page, _ = open_page("?speed=10", "cooldown")
    page.wait_for_timeout(3800)
    check(page.locator("#btn-continue").is_enabled(), "?speed=10 30초 쿨다운이 4초 안에 끝남")
    page.close()
    # 전체 흐름 클릭
    page, _ = open_page("?speed=10", "onboarding")
    page.click("#start"); page.click("#link"); page.wait_for_selector("#btn-exit", timeout=3000)
    page.wait_for_timeout(6500)
    page.click("#btn-continue"); page.click("#chargeGo"); page.click("#btn-exit")
    page.wait_for_selector("text=멈춘 금액", timeout=3000)
    check("멈춘 금액" in page.inner_text("body"), "클릭 흐름 온보딩→카드→충전→쿨다운→기록")
    page.close()
    check(all(u.startswith("file://") or u.startswith("data:") for u in requests), "네트워크 요청 없음(file만)")
    browser.close()

pngs = sorted(OUT.glob("*.png"))
check(len(pngs) >= 12, f"PNG {len(pngs)}장")
if fails:
    print(f"\n{len(fails)}개 실패"); sys.exit(1)
print("\n전체 통과")
