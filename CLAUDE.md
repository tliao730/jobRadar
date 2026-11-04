# CLAUDE.md — Job Radar

私人求職工具，不公開（私人 repo，只分享給朋友 clone 回去在自己的 Mac 用）。這份檔案是唯一的專案文件：規則、規格與進度都在這裡；設計變更時更新對應章節，任務完成時勾選「三、進度」。`README.md` 是給使用者（朋友）的安裝與使用說明：安裝步驟、操作方式、設定檔或指令有變時一起更新。

- **申請助手**（已實作）：Dock 上的 Job Radar 開啟一個程式控制的 Chrome，裡面有主頁（職缺清單）與申請頁旁的側邊欄。自動填基本資料、經歷與答案庫，沒填到的題目列成清單（有金鑰時附 Claude 建議答案），我直接到申請頁補上；送出由我手動完成。
- **職缺雷達**（部分實作）：每天 08:30 從 ATS 公開 API（68 家公司）抓職缺，讀 Simplify 在 GitHub 的 New Grad 清單，並搜尋 LinkedIn、Jobright（不登入）；網站上的職缺對到公司的 ATS 就能自動填。用規則評分（以 new grad / entry level 為主），在主頁「推薦職缺」勾選後一鍵加入、開啟申請頁並填好基本資料。Indeed / Glassdoor、LLM 抽取、每日摘要與每週趨勢仍在規劃。

## 指令

```bash
uv sync
uv run job-radar init-profile          # 建立 profile/ 範本（不覆蓋既有檔案）
uv run job-radar install-app           # 建立 ~/Applications/Job Radar.app 並加到 Dock
uv run job-radar ui                    # 申請助手（Dock 圖示做的就是這件事；已在執行時叫回視窗）
uv run job-radar apply add <url>...    # 也可以 apply list、track <job_id> <status>
uv run job-radar inspect <url> --fill  # 在暫時的 Chrome 試跑 ②，列出每題的區塊、分類、結果（不送出）
uv run job-radar fetch                 # 雷達：抓 config/companies.yaml 的職缺
uv run job-radar radar [--excluded]    # 雷達：列出推薦（--excluded 連排除原因一起列）
uv run job-radar check-companies       # 雷達：驗證公司代號
uv run job-radar install-schedule      # 雷達：每天 08:30 自動 fetch（--at HH:MM 改時間，--remove 取消）
uv run pytest                          # 含 headless Chrome 測試（需要安裝 Google Chrome）
```

任務完成的標準：`uv run ruff check . && uv run ruff format . && uv run pytest` 全部通過。

第一次使用（朋友照 README 的步驟；需要 macOS、[uv](https://docs.astral.sh/uv/)、Google Chrome）：`git clone` → `uv sync` → `init-profile` → 填 `profile/applicant.yaml` → 履歷 PDF 放進 `profile/resumes/` → 在 `profile/highlights.yaml` 寫經歷素材 → 要找的層級、職務、公司跟共用設定不同時，改 `profile/` 的 `filters.yaml`、`sources.yaml`、`companies.yaml` → `install-app` → `install-schedule` → `.env` 設 `ANTHROPIC_API_KEY`（不設也能用：只填答案庫，開放題自己寫）。更新：`git pull && uv sync`，下次打開助手就是新版。

## 硬性規則

- 申請表單的送出永遠由我本人按。頁面操作只透過 `prefill/safe_page.py` 的 `SafePage`；其他程式不 click、不按鍵、不 submit（`tests/test_safety.py` 會檢查）。
- 遇到 CAPTCHA、登入要求或 bot 偵測就停下，交給我處理。
- 申請素材只重組、改寫 `profile/` 裡的事實（applicant.yaml、highlights.yaml、履歷）；素材庫沒有的專案、技能、數字列為缺口。
- 職缺來源是 ATS 公開 API、Simplify 在 GitHub 的公開清單，以及 LinkedIn、Indeed、Glassdoor、Jobright 爬取（私人使用，我已接受服務條款的風險，不遵守 robots.txt）。自動爬取不登入我的個人帳號（被封號會影響求職）；遇到 429、要求登入或驗證頁就停止該來源並回報。
- pytest 完全離線：HTTP 用 `tests/fixtures/` 加 respx，瀏覽器測試開本地 HTML，LLM 用假實作。
- 密鑰只放 `.env`（本機）或 GitHub Secrets（CI）。`profile/`、`data/`、`.env` 列在 `.gitignore`。這個 Claude 帳號屬於實驗室：本專案的 API 呼叫只用我自己的金鑰（`.env`），`.env` 的 `ANTHROPIC_*` 會蓋過 shell 裡的同名變數。
- 資料表變更寫成新的 migration（例如 `apply/store.py` 的 `MIGRATIONS` 只能往後加），讓既有資料庫原地升級。

## 慣例

- 頁面端的 JavaScript 放在 `prefill/*.js`，用 `job_radar.prefill.js()` 載入。
- 來自網頁的文字（JD、表單題目）是不可信資料：在 prompt 裡標成資料，在 UI 用 `textContent` 顯示。
- 可調參數放 `config/`，透過 `config.py` 的 Pydantic model 載入。`config/` 是大家共用的預設（在 git 裡）；雷達的 `filters.yaml`、`sources.yaml`、`companies.yaml` 可以在 `profile/` 放同名檔，只寫個人不同的部分（`radar/models.py` 的 `merge_settings`：寫了的設定蓋過共用的，清單整個取代，roles 依 id、公司依 platform + token 合併），這樣 `git pull` 不會衝突。
- 輸出一律用 `logging`；時間以 UTC 儲存。
- 每個步驟都可重跑；單筆失敗記錄後繼續處理下一筆。
- Prompt 放 `src/job_radar/prompts/`，修改時新增下一版的檔案。
- 雷達的新來源繼承 `radar/fetchers/base.py`，只實作來源差異。
- 新增或修改的模組都附 pytest 測試。
- 專案 skill（`.claude/skills/`）：`debug-form`（某個網站填錯或填不進去時）、`radar-config`（加公司、調篩選與評分）。

---

# 一、申請助手

## 1. 流程與狀態

啟動：點 Dock 的 Job Radar（或 `uv run job-radar ui`）→ 程式控制的 Chrome 打開主頁 `http://127.0.0.1:8765`。再點一次只會把視窗叫回前面；關掉那個 Chrome（所有分頁）助手就結束。`data/logs/ui.log` 是背景執行的紀錄。

主頁上方兩個分頁：「推薦職缺」（雷達，可依職務篩選、只看新職缺，勾選後底部出現「加入並開啟」）與「我的申請」（左邊依狀態分組的清單、上方貼網址；右邊是選中的職缺）。每個職缺顯示三步進度（開啟申請頁 → 自動填寫 → 檢查並送出，`common.js` 的 `stageOf`），下面的卡片說明下一步、只把下一步的按鈕做成主要按鈕；自動填寫完就是「檢查並送出」，「我已送出」直接出現。右上角的圓點是申請資料狀態（基本資料、履歷、素材、草稿模型）。

1. 加入職缺：在「推薦職缺」勾選後按「加入並開啟」（逐一加入、開分頁、可選擇自動按 ②），或貼網址（Greenhouse、Lever、Ashby、LinkedIn、Indeed、Glassdoor、Jobright、任何網站）。三家 ATS 會從公開 API 取得 JD；其他網站在開啟頁面時讀取頁面文字。Greenhouse 一律開 embed 申請頁（`job-boards.greenhouse.io/embed/job_app?for=…&token=…`），不經過常被導去公司官網的職缺頁。
2. ① 開啟申請頁：受控的 Chrome 開啟申請頁。需要登入或要先按 Apply 的網站，我在瀏覽器手動處理；職缺開出新分頁時（例如 LinkedIn 的 Apply on company site），會改用新分頁。
3. ② 自動填寫：掃描表單、填入能自動填的欄位，職缺變成「待送出」。沒填到的題目（開放題、人口統計、選不到的選項、填寫失敗的）依頁面順序列成清單，標出所屬區塊、是否必填、原因，有建議答案時一起列出；助手裡不提供作答框（2026-11-01：一題一題在助手裡填再送回頁面太慢）。
4. 我到申請頁補上清單裡的題目、逐欄檢查、自己按送出 → 按「我已送出」。清單和按鈕在主頁與側邊欄都有。常用的答案寫進 `applicant.yaml` 的 `answers`，之後就會自動填。

側邊欄（`web/extension/` 的 Chrome 擴充功能）：按 Chrome 右上角的 Job Radar 圖示或 ⌘⇧Y 打開，之後在同一個視窗切分頁都會跟著換。它顯示目前分頁所屬的職缺，同樣有三步進度和要自己填的清單，下一步的按鈕固定在底部；不在清單裡的網頁（例如在 LinkedIn 逛到的職缺）可以按「加入清單並在這頁申請」。擴充功能只讀分頁網址，內容是 iframe 嵌入的 `/panel`，和主頁共用 `static/common.js`。

沒有金鑰時（`profile_status` 的 `drafts` 為 false）不呼叫模型：開放題只列在清單裡讓我自己寫。

「停下來等我」是職缺停在某個狀態，不是程式開著等：每個按鈕做完自己那一步就結束。重按 ② 會重新掃描目前頁面，已填的欄位不覆寫（包括我在頁面上自己填的），已產生的建議沿用、不重複花費。

分頁關掉了（不小心關掉，或重開助手）：② 遇到分頁已關會重新開啟並自動填寫，不再重新產生建議；以前用 ③ 確認過的答案（`confirmed`，存在 `form.json`）也會依題目填回去。主頁清單會標「分頁已關」，上方的卡片可以「全部恢復」或勾選幾個恢復（一個接一個跑），職缺頁的卡片也有「恢復申請頁」。直接在申請頁上打的字救不回來。

狀態：`queued`（待處理）→ `ready`（待送出，② 成功後）→ `applied`（已送出），另有 `skipped`、`interviewing`、`offer`、`rejected`、`withdrawn`。`prefilled` 是有 ③ 時期的舊狀態，畫面上當成待送出，下次按 ② 會改成 `ready`。

## 2. 欄位分類（`apply/classify.py`，先符合的為準）

| 順序 | 規則 | 結果 |
|---|---|---|
| 1 | 檔案欄位：履歷 / CV | 上傳選定的履歷；cover letter 與其他檔案留給我 |
| 2 | 符合答案庫（`answers_learned.yaml` 優先，其次 `applicant.yaml` 的 `answers`） | 自動填；選擇題對到最接近的選項，對不上就改為「請確認的建議」 |
| 3 | 人口統計、EEO、年齡、犯罪紀錄（也看區塊標題，例如 Diversity） | 留給我；`applicant.yaml` 的 `eeo` 有設定且選項對得上才自動填 |
| 4 | 工作經歷、學歷區塊（`apply/history.py`：看區塊標題、id 尾碼 `-0`/`--0`、題目） | 從 `employment` / `education` 第 N 筆自動填：月份對選項、年份填數字、學位轉成 "Master's Degree" 這類用語；目前工作的結束日期留空並自動勾「目前在職」，「仍是學生」列為建議。科系選不到主修時依序試 `major_fallbacks`；學校名稱要完全相同才選（清單裡的 "National Taipei University of Technology" 不是台北大學），選不到就標失敗請我手動選。表單只有一筆時，按區塊的「Add another」補到 `applicant.yaml` 的筆數（最多 3 筆） |
| 5 | 基本資料（姓名、email、電話、LinkedIn、GitHub、網站、公司、地點、國家） | 從 `applicant.yaml` 自動填；沒填的留給我 |
| 6 | 同意、聲明、仲裁條款，以及其他單一勾選框 | 留給我 |
| 7 | 其他 | 交給 Claude：「請確認的建議」或「需要你思考」 |

畫面分兩區：「要你在申請頁自己填」（上面第 2、3、6、7 類與填寫失敗的，依頁面順序編號，必填的標紅）與收合的「已自動填寫」。每題標出所屬區塊（例如「Employment」）。`POST /api/applications/<id>/fill`（③）還在 API 裡，畫面不再使用。

## 3. 草稿（`apply/drafts.py`）

- 模型 `TAILOR_MODEL`（預設 `claude-sonnet-5-5`），structured outputs（`client.beta.messages.parse` 搭配 Pydantic），effort 預設 `medium`，開啟 server-side refusal fallback（`fallbacks: default`，可在 `config/settings.yaml` 關閉）。
- Prompt：`prompts/draft_answers_v1.md`；改版時新增 v2 並更新 `drafts.PROMPT_VERSION`。
- 依據只有 `profile/`；素材庫沒有的內容用 `[補充：…]` 標出。送出前遮掉履歷中的 email 與電話。JD 與表單文字在 prompt 中標為不可信資料。
- 選擇題答案必須是頁面上的選項，否則降級為「需要你思考」並註明；超過字數上限只標示、不截斷。
- Greenhouse 的下拉選單要點開才有選項，改從 board API 的 `questions=true` 取得（含 `demographic_questions`，它的欄位 id 就是題目 id）。每次按 ② 都重抓一次 ATS 的 JD 與題目，舊職缺也會用到解析上的改進。
- 選項對應（`classify.choose_option`）：完全相同 → 開頭相同 → 包含；都不行時，句子型答案看「意思相同、用詞不同」：重要的字至少一半相同、否定一致、而且只有一個選項最接近（"I am not a protected veteran" → "No, I am not a veteran or active member"）。
- token 用量與估計成本記在 log 與該職缺的 `llm_cost_usd`；一個職缺約 $0.05。

## 4. 填寫表單（`prefill/`）

- `SafePage` 只能填寫、選擇、勾選、上傳，以及點擊非送出元素；點擊前檢查元素，`type=submit`、表單內沒有 type 的 `<button>`、文字像 Submit / Apply / 送出的按鈕一律拒絕。
- 操作期間在頁面裝上 guard（`guard.js`），攔下 submit 事件與 `form.submit()` / `requestSubmit()`；結束就解除，不影響我自己按送出。
- 自動那一輪不覆寫已有內容；我確認過的答案才覆寫。
- 「Add another」（`prefill/add_entry.js` 找按鈕、`SafePage.click_control` 按）：從區塊最後一個欄位往上找，一旦祖先元素裡出現別的區塊的欄位就停，避免按到隔壁區塊的按鈕；按完重新掃描，只分類與填寫新出現的欄位（也會順便填到因先前答案才出現的題目，例如選了 Hispanic = No 才出現的 race）。
- **先等頁面可互動**：伺服器先產生 HTML、再由 React 接手的表單（Greenhouse 新版等），在接手前輸入會讓整個 app 當掉（React #426/#345），之後下拉選單全部打不開、文字欄位看似填了但 app 收不到。`scanner.wait_until_interactive` 等到表單欄位都掛上 React 才掃描與填寫，等不到就停下並提示重新整理，不碰頁面（2026-10-23 在 Coinbase 表單上查到；剛啟動、快取是空的瀏覽器最容易遇到）。快取是空的時候，React 可能還沒標記 root，只有框架的內嵌資料（Remix 的 `__remixContext`、Next.js 的 `__NEXT_DATA__` 等）：看到這些也算 React 頁面、要等（Point72）。前端渲染的頁面（Ashby）表單會晚好幾秒才出現，剛啟動、同時開好幾個分頁時可能超過 20 秒，所以先等到畫面上出現表單欄位（最多 20 秒），再等 React 接手（最多 25 秒）；不能把「0 個欄位」當成已就緒（Ramp，2026-10-24）。
- 可搜尋的下拉選單（react-select 等）：先輸入文字讓選單出現，再點符合的選項；完整名稱沒結果時改用至少兩個字的較短查詢（"Applied Data Science" → "Data Science"），但只接受跟完整值相符的選項；找不到就清空並列為失敗。選項只比對第一行（Ashby 的學校是「名稱／國家／網域」三行，整段比對時 USC 永遠「不在清單裡」）。第二次嘗試等選單 6 秒（國家這種長清單在忙碌時較慢）。點選項逾時時看下拉選單實際顯示的值，已經選上就算成功。
- 日曆型日期欄位（react-datepicker，`FormField.picker`）：只讀得懂完整日期，經歷的日期填 `05/01/2027`（一般文字欄位才填 `05/2027`）；輸入後點日曆上被選中的那天，讓網站用自己的格式寫入並關閉日曆。日曆不關會蓋住旁邊的欄位，之後的勾選點到日曆上（Ramp，2026-10-26）。勾選框點了狀態沒變時，等 0.3 秒再看一次（有些 React 元件下一輪才更新），還是沒變才報錯。
- 填寫失敗時，Playwright 的完整錯誤（含被什麼元素擋住）寫進 `data/logs/ui.log`。
- 掃描所有 frame（公司官網嵌入的 Greenhouse 也能填）。欄位標籤取「畫面上看得到的文字」，找不到時往前找最近、中間沒有其他欄位的標籤；沒有標籤、緊跟在同一組前一個欄位後面的（月＋年兩個下拉選單）沿用前一個的標籤。
- 區塊（`section`）：欄位前最近、且所在容器也包住該欄位的標題；在 `<form>` 裡只認 form 內的標題，題目自己的標籤、以及範圍涵蓋幾乎所有欄位的標題（頁面層級）都不算。
- 登入頁、真人驗證頁、CAPTCHA 挑戰視窗 → 停止並提示；表單上的小型 CAPTCHA 勾選框只提醒。
- 瀏覽器使用獨立 profile（`data/browser-profile/`），手動登入過的網站會保持登入；動作逾時 10 秒，避免卡住介面。填到一半分頁被關掉時，其餘欄位標成「申請頁在填寫途中被關閉」。

## 5. 履歷版本

- `profile/resumes/*.pdf`，檔名即版本名稱。只有一份時一律用它；多份時依 `config/settings.yaml` 的 `apply.resume_rules`（依職稱）建議，頁面上可改選。
- 職缺專用的履歷存成 `data/applications/<job>/resume.pdf`，會優先使用。
- 履歷原始檔在 `~/Documents/MyDocument/CV/`（LaTeX，有自己的 git）。更新後把 `cv.pdf` 複製到 `profile/resumes/`，內容有變時同步修改 `highlights.yaml`。

## 6. 資料

- `profile/`（不 commit）：`applicant.yaml`（基本資料、學歷 `education`（可加 `major_fallbacks`）、工作經歷 `employment`（最近的在前）、答案庫 `answers`、EEO 偏好 `eeo`）、`skills.yaml`（履歷沒寫到但我會的技能，只給雷達排序用）、`highlights.yaml`（經歷素材，每項有 id、context、did、results、skills）、`resumes/*.pdf`、`answers_learned.yaml`（勾「記住這個答案」時寫入，可手動編輯）、雷達的個人設定 `filters.yaml` / `sources.yaml` / `companies.yaml`（只寫跟 `config/` 不同的部分，`init-profile` 會建立全是註解的範本）。
- `data/applications.duckdb`：`applications`（job_id、status、job_snapshot、resume_variant、llm_cost_usd、created_at、updated_at、applied_at、notes）與 `application_events`（job_id、from_status、to_status、occurred_at、note），後者之後用來算面試率、調整雷達權重。
- `data/applications/<job>/`：`jd.md`（JD 快照）、`form.json`（最近一次掃描、分類、草稿與填寫結果）、選用的 `resume.pdf`。

## 7. 本機頁面的安全

頁面跑在 Playwright 控制的 Chrome 裡，`confirm()` / `alert()` 會被自動取消（「我已送出」曾因此按了沒反應），所以需要確認的按鈕改成按兩下（`common.js` 的 `confirmTwice`），`tests/test_safety.py` 禁止頁面用瀏覽器對話框。受控的 Chrome 會跨次保留快取，曾在更新後繼續跑舊版 `app.js`，所以頁面與 `/static` 一律 `Cache-Control: no-cache`，JS／CSS 網址帶依內容計算的 `?v=` 版本。

只綁 `127.0.0.1`；`TrustedHostMiddleware` 擋 DNS rebinding；每次啟動產生 token 嵌在頁面，所有 API 都要帶 `X-JR-Token`（只有 `/healthz` 不用）；來自職缺網頁的文字一律用 `textContent` 顯示。主頁 `frame-ancestors 'none'`，`/panel` 只能被擴充功能嵌入。執行中的 port 與 token 寫在 `data/ui-session.json`（權限 600，結束時刪除），給第二次啟動叫回視窗用。擴充功能只有 `sidePanel`、`tabs` 權限，沒有 content script（`tests/test_safety.py` 會檢查）。

擴充功能的載入方式：Chrome 137 起不接受 `--load-extension`，改用 `--enable-unsafe-extension-debugging` 加 CDP `Extensions.loadUnpacked`（`prefill/browser.py`）。每次啟動把 `web/extension/` 複製到 `data/browser-extension/` 並寫入 `config.js`（伺服器網址）。

## 8. 測試

- `tests/fixtures/forms/` 有仿 Greenhouse、Lever 結構的表單，含「送出就會被記錄」的陷阱；`late_hydration.html` 模擬接手前輸入就當掉的 React 表單，`history_like.html` 模擬 Employment / Education 區塊。瀏覽器測試用 headless Chrome 開本地檔案。
- `tests/test_safety.py`：`safe_page.py` 以外不得 click、按鍵或 submit；`safe_page.py` 只有一處 click，且在檢查之後。
- `tests/conftest.py` 的 `FakeLLM` 讀 prompt 裡的欄位清單產生草稿。

## 9. 已知限制

- **登入**：Greenhouse、Lever、Ashby 的申請表不用帳號，雷達只推這三家，所以自動開出來的頁面都能直接填。Workday、iCIMS 等每家公司要各自註冊帳號：助手遇到登入頁會停下，我手動註冊／登入一次，獨立 profile 會記住。LinkedIn Easy Apply、Indeed Apply 要用我的個人帳號；受控的 Chrome 會被網站看出是自動化瀏覽器，為了不讓求職帳號被封，不在裡面登入 LinkedIn / Indeed，改走職缺頁上的公司 ATS 連結。
- 多頁式表單（Workday 等）：每一頁按一次 ②。
- 非標準元件（按鈕做的 Yes / No、日期挑選器）可能抓不到，留在瀏覽器由我處理。
- LinkedIn Easy Apply 不支援（在 LinkedIn 站內、需要我的帳號）；外部 Apply 會跳到公司 ATS，可以用。
- 只能在本機執行：它要控制我電腦上的 Chrome（我的登入狀態、由我檢查並送出），無法放到 Vercel 這類雲端平台。
- 側邊欄要自己按一次圖示打開（Chrome 只允許使用者動作開啟）；第一次使用時把 Job Radar 圖示釘選在工具列比較方便。
- `install-app` 把專案路徑和 uv 路徑寫死在 App 裡；搬動專案資料夾後要重跑。
- 申請狀態只存在本機，還沒同步到 R2。

---

# 二、職缺雷達（ATS 抓取與規則評分已實作，其餘規劃中）

## 0. 目前實作（`src/job_radar/radar/`）

- `fetchers/`：Greenhouse、Lever、Ashby，各平台一個執行緒、同一平台請求間隔 1 秒；68 家約 75 秒、約 1.4 萬個職缺。
- `store.py`：`data/jobs.duckdb` 的 `jobs`、`fetch_results`、`runs`、`dismissed`（「不感興趣」）。每次操作開短連線、被鎖住時重試，讓排程抓取和開著的助手可以共用；同一個程式裡的執行緒輪流開（DuckDB 在一個連線關閉的同時又開新連線會報 "already attached"，2026-10-25 在介面觸發的抓取中發生過）。下架、suspect、baseline 規則同第 4 節。
- `match.py`：不用 LLM 的規則評分。先用職稱與地點篩（便宜），通過的才讀 JD：排除 sponsorship 寫明不提供、發布超過 60 天。分數 = 加權（技能重疊（平滑過的比例）、職務偏好、層級（想找 intern / new grad，沒寫層級的分數低））。規則都在 `config/filters.yaml`（加上 `profile/filters.yaml` 的個人設定）、`config/skills.yaml`。共用設定不偏向任何人（2026-11-04 起；我的方向、權重、關鍵字搬到我的 `profile/`）：職務類別分三大類 `group`——software（swe、mle、ai_engineer、de、infra）、data（ds、da、ba）、hardware（digital、analog、electrical、embedded），預設全開、權重都是 1；每類有 `name`（推薦頁的標籤，由 `/api/radar` 的 `roles` 傳給頁面）與 `queries`（LinkedIn / Jobright 的搜尋關鍵字）。`only_roles` 寫大類或 id，只看那些類別（`match.active_roles`；類別裡 `enabled: false` 的仍然不看），職稱在「看的類別」裡由上而下第一個符合的為準，所以 embedded、digital、analog 排在 swe 前，infra、electrical 排在 swe 後。沒寫 `queries` 時，搜尋關鍵字＝看的類別各自的 queries，每類先搜第一個再搜第二個（`service.search_queries`，被限流時每類至少搜到一次）。地點包含 50 州全名與縮寫（排除用字邊界：曾經因為 'india' 排除了 Indianapolis）；`no_sponsorship` 也擋 ITAR 的「must be a (i) U.S. citizen」「U.S. person」，但不擋只是提到 export control 的制式文字。技能詞彙涵蓋軟體、資料、商業分析、硬體／嵌入式；我的技能 = highlights + 履歷 + `profile/skills.yaml` 對到的詞彙。
- `service.py`：結果依抓取批次與設定、`highlights.yaml`、`profile/skills.yaml`、履歷 PDF 的修改時間快取（重算一次約 4 秒；只看技能來源的檔案，記住答案、改 `applicant.yaml` 不會讓快取失效）。助手啟動時和每次抓取完就在背景先算好，打開推薦頁不用等；同時間只算一次。同公司同職稱只留分數最高的地點。
- 排程：`install-schedule` 寫 `~/Library/LaunchAgents/local.job-radar.fetch.plist`，紀錄在 `data/logs/fetch.log`。launchd 不會補跑 Mac 關機時錯過的 08:30（10/29、10/30 就這樣漏掉），所以排程跑 `fetch --if-stale` 並加 `RunAtLoad`：08:30、登入時、打開助手時，只要「最近一個排程時間點（今天 08:30，還沒到就算昨天的）之後還沒抓過」就抓（`RadarService.stale`；時間從已安裝的 plist 讀，`--at` 改過也照著走）。原本用「上次抓取超過 20 小時」，11/02 因為前一天下午手動抓過，08:30 被判成不用抓。
- 「新職缺」＝最近 3 天第一次出現（`match.NEW_DAYS`；職缺板第一次被抓到的不算）。推薦頁顯示近 3 天新出現的推薦數，抓完跳出這次新增幾個、哪些來源失敗；以前只顯示「最後一次抓取」的新增數，連按兩次就變 0，看起來像壞掉。
- `sites/`：LinkedIn（訪客職缺搜尋，只抓搜尋卡片；詳細頁兩三個請求就 429，而且不登入看不到申請連結）與 Jobright（不登入的搜尋頁，每個關鍵字前 20 筆，`__NEXT_DATA__`；2026-11 起第一個請求就導到 `/_jr/security/challenge` 真人驗證頁，依規則停下、10/24 之後沒抓到任何 Jobright 職缺）。關鍵字來自職務類別的 `queries`（或個人 `sources.yaml` 的 `queries`），間隔在 `config/sources.yaml`；遇到 429、登入頁、非結果頁就停止該網站，已抓到的保留。網站職缺不會因為這次沒出現就下架，14 天沒再看到才算下架。
- Simplify（`sites/simplify.py`）：讀 `SimplifyJobs/New-Grad-Positions`（可在 `sources.yaml` 的 `simplify.repos` 加實習 repo）的 `.github/scripts/listings.json`，一次下載整份、不用關鍵字；只收 `active` 且 `is_visible` 的。連結直接是公司申請頁：Greenhouse / Lever / Ashby 的直接可自動填（`resolve.ats_job_id`），是已追蹤職缺板上的職缺就用網址對到那筆；Workday 等列在「需要自己開啟」，也不拿公司名去猜職缺板（約 3,000 家，會打出幾千個請求）。清單是完整的，沒出現就立刻下架（`SearchResult.complete`）。沒有 JD：分數只看職稱與層級（New Grad repo 標 New Grad），sponsorship 只在 Simplify 有寫時（Does Not Offer Sponsorship 等）才擋得到。2026-11-02 第一次抓：3,083 筆、77 筆能自動填且通過篩選、24 筆與既有 ATS 職缺重複。
- `resolve.py`：網站職缺用（正規化公司名、職稱相似度 ≥ 0.6）對到 ATS 職缺，`jobs.ats_id` 記下對應；推薦頁只顯示 ATS 那筆並標「也在 LinkedIn / Jobright」。公司不在清單裡時，用完整公司名猜 Greenhouse / Lever / Ashby 代號（不用第一個字，否則 "applied"、"new" 會猜到別家），職缺板上要有職稱對得上的職缺、Greenhouse 的公司名也要對得上才算找到；結果快取在 `company_boards` 30 天。找到的公司列在推薦頁上方，按「加入」寫進自己的 `profile/companies.yaml`（共用清單 `config/companies.yaml` 不動）。對不到的網站職缺列在「需要自己開啟」，加入後只開原網頁、不自動按 ②。
- 層級：以 new grad / entry level 為主（`levels.want`）；實習只收 co-op / off-cycle（職稱有 co-op、off-cycle 或 fall / spring / winter，或 JD 寫 co-op；JD 裡的季節常是在講學期，不算）；JD 要求超過 `max_years`（2）年經驗的排除；網站標的層級（Entry Level、New Grad、Senior Level…）也會用來判斷。
- 2026-10-24 試算：LinkedIn / Jobright 約兩成職缺對得到 ATS；其餘多是用 Workday 或自家系統的大公司。Glassdoor 直接請求被 Cloudflare 擋，JobSpy 走內部 API 抓得到清單但沒有申請連結，樣本 30 筆對到 ATS 0 筆，所以先不做。
- 下面第 1–9 節是完整規劃；已實作的部分以上面為準。

## 1. 架構

```
[每日排程（見第 9 節）]  pull DB：R2 → data/jobs.duckdb
1. Fetch      ATS 公開 API ＋ LinkedIn / Indeed / Glassdoor 爬取，每個來源各自成敗
2. Normalize  統一欄位、HTML → 純文字、計算 content_hash
3. Store      upsert 進 DuckDB；只對「本次抓取成功」的來源判定下架
4. Prefilter  職稱／地點規則（便宜、從寬），決定哪些職缺送 LLM
5. Extract    LLM structured outputs → Pydantic 驗證；同 content_hash 共用結果
6. Match      硬性條件 → embedding 相似度 + 技能重疊 + 領域與職務偏好 → 分數
7. Report     每日摘要、每週趨勢（先產生 Markdown，寄送管道可插拔）
              push DB：data/jobs.duckdb → R2
```

每個階段是獨立模組與 CLI 子指令（`fetch`、`extract`、`match`、`report`，`run` 依序執行全部），可重跑、只處理增量。抓到的職缺全部存進 `jobs`，只有通過 prefilter 的才花 LLM 費用。單一來源、單一職缺的失敗只記錄。

## 2. 資料來源

### ATS 公開 API（主要來源）

| 平台 | Endpoint |
|---|---|
| Greenhouse | `https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` |
| Lever | `https://api.lever.co/v0/postings/{token}?mode=json`（EU 公司用 `api.eu.lever.co`） |
| Ashby | `https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true` |

- token 從公司 careers 網址找：`job-boards.greenhouse.io/{token}`、`jobs.lever.co/{token}`、`jobs.ashbyhq.com/{token}`；`job-radar check-companies` 逐一驗證。公司清單放 `config/companies.yaml`（name、platform、token、選填 region、enabled）。
- 請求間隔 ≥ 1 秒、timeout 30 秒；429 / 5xx 指數退避最多 3 次；404 代表 token 錯誤。
- 某公司這次 0 筆、上次 ≥ 5 筆 → 記為 `suspect`，不據此判定下架。
- Greenhouse：`content` 是 HTML entity 編碼的 HTML，先 `html.unescape()` 再去標籤；有 `company_name`；`updated_at` 不是發布時間。
- Lever：完整 JD 分散在 `description`、`lists[]`（Requirements 等）與 `additional`，三者都要串起來；職稱在 `text`，地點在 `categories.location`，`createdAt` 是毫秒。
- Ashby：用 `descriptionPlain`；只留 `isListed`；`isRemote` 與結構化薪資直接存。

### 職缺網站爬取

| 網站 | 做法 | 注意 |
|---|---|---|
| LinkedIn | 不登入的訪客職缺搜尋與職缺頁 | 一律不用登入狀態 |
| Indeed | 職缺搜尋與職缺頁 | Cloudflare，雲端主機 IP 幾乎一定被擋 |
| Glassdoor | 不需登入的部分 | 大部分內容要登入 |
| Jobright | 暫不自動爬 | 大部分內容要登入；先把網址貼進申請助手 |

- 同一網域請求間隔隨機 3–8 秒，每次執行設數量上限（例如每組搜尋 100 筆），數值放 `config/`。
- 遇到 429、authwall、CAPTCHA、Cloudflare 驗證頁就停止該網站，記在 `fetch_results` 並列在每日摘要。
- 職缺頁的 Apply 連到 Greenhouse / Lever / Ashby 時記下 ATS 網址：申請助手直接開 ATS 頁面，也能跟 ATS 來源去重。跨來源以（正規化公司名、正規化職稱、地點）合併，ATS 版本優先。
- 實作前先評估開源的 JobSpy（`python-jobspy`）能否直接使用。

## 3. 正規化與去重

主鍵 `{source}:{source_job_id}`；`description_text` 去標籤、合併空白；`content_hash = sha256(title + "\n" + description_text)`（HTML 細微變動不算更新）；原始 JSON 存 `raw`。多地點重複職缺（同 content_hash）照存多筆，抽取共用，報告合併顯示。

## 4. 資料表（`data/jobs.duckdb`，時間存 UTC，migration 記在 `schema_version`）

- **jobs**：id、source（greenhouse / lever / ashby / linkedin / indeed / glassdoor / jobright）、company、title、location_raw、url、description_html、description_text、content_hash、raw、posted_at、first_seen_at、last_seen_at、content_changed_at、is_active、closed_at、is_baseline。下架判定只對本次 `fetch_results.status = 'ok'` 的來源；職缺重新出現時清空 closed_at。`is_baseline` = 來源第一次被抓取時就存在的職缺，不算「新增」，避免第一次執行洗版。
- **fetch_results**：run_id、company、source、status（ok / error / suspect）、job_count、error、fetched_at。
- **runs**：run_id、command、started_at、finished_at、stats（新增／更新／下架數、LLM 呼叫數、token、成本）。
- **job_extractions**（主鍵 content_hash：JD 一變就自然重新抽取）：role_type（analytics_ds / modeling_ds / mle / ai_engineer / swe / data_engineer / data_analyst / research / other）、seniority（intern / entry / mid / senior / staff_plus / unknown）、primary_domain、domains（最多 3 個，來自 `config/taxonomy.yaml`）、other_domains、required_skills、preferred_skills（原始輸出，讀取時正規化）、summary（2–3 句英文職責摘要，供 embedding）、min_years_experience、min_degree、visa_sponsorship（yes / no / not_mentioned）、workplace_type、salary_min / max / currency / period、model、prompt_version、input_tokens、output_tokens、extracted_at。
- **extraction_errors**：content_hash、attempt、error_type（api_error / validation_error / refusal / max_tokens）、message、raw_output、created_at；累計 3 次失敗後停止自動重試。
- **job_embeddings**：(content_hash, model) → vector。
- **job_matches**：job_id、similarity、skill_overlap（必備技能為空時 NULL）、domain_fit、role_fit、penalty、score、missing_skills、excluded_reason、computed_at。每次 match 重算所有 active 候選職缺。

## 5. 篩選（`config/filters.yaml`）

**Prefilter（LLM 之前，只看職稱與地點，高召回）**：職稱符合任一職務類別且不含排除詞（sales、recruiter、director、VP、principal…）；地點規則從寬；比對不分大小寫、用 word boundary。

| 類別 | 職稱關鍵字（例） |
|---|---|
| ds | data scientist、applied scientist、research scientist、quantitative analyst |
| mle | machine learning engineer、ML engineer、MLOps engineer |
| ai_engineer | AI engineer、LLM engineer、generative AI engineer |
| swe | software engineer、backend / frontend / full stack engineer、member of technical staff |
| de | data engineer、analytics engineer、data platform engineer |
| da | data analyst、business intelligence analyst、product analyst |

SWE 職缺量是 DS 的好幾倍：靠層級與地點規則控制，每個類別可單獨開關。

**硬性條件（LLM 之後）**：seniority、年資上限、visa_sponsorship = no（可開關）、role_type / workplace_type 白名單。被排除的仍算分但標記 `excluded_reason`，不進每日 Top N。層級交給 LLM 判斷，比職稱關鍵字準。

## 6. LLM 抽取

- 範圍：通過 prefilter、active、content_hash 沒有抽取紀錄的職缺（`--reextract` 重抽舊 prompt 版本）。
- 模型 `LLM_MODEL`（預設 `claude-haiku-5-5`，effort `low`），structured outputs；`domains` 的 enum 由 taxonomy.yaml 動態產生。Pydantic 再檢查語意；檢查 `stop_reason`（max_tokens、refusal）；失敗重試一次，仍失敗寫入 extraction_errors。
- JD 截斷到 `max_jd_chars`（12,000）；Ashby 的平台欄位優先於 LLM 結果。
- Prompt `prompts/extract_v{N}.md`：附 taxonomy 定義、domains 只選核心工作（最多 3 個）、技能用 `config/skills.yaml` 的正規名稱。改版時用 eval 集比較。
- 技能正規化在讀取時做（別名表一改就套用到所有歷史資料）；對不到的列在週報「待歸類」。
- 成本：`claude-haiku-5-5` 在 prompt ≤ 10 萬 tokens 時輸入 $0.10、輸出 $0.50 / 百萬 tokens，一筆 JD 約 $0.001；最小可快取長度 512 tokens，system prompt（含 taxonomy）放固定前綴加 `cache_control`；Haiku 5.5 被拒時沒有 server-side fallback。首次回補或全面重抽用 Message Batches（半價）。

## 7. 匹配與評分（`config/scoring.yaml`）

```
score = w_sim·similarity + w_skill·skill_overlap + w_domain·domain_fit + w_role·role_fit − penalty
```

- similarity：summary + 職稱 + domains + 必備技能的 embedding（fastembed，`BAAI/bge-small-en-v1.5`）對履歷分段的前 k 塊平均；在當次候選集合內轉成百分位數再加權（原始 cosine 擠在 0.3–0.7）。
- skill_overlap：必備技能中 `profile/skills.yaml` 已具備的比例；為空時不計，其餘權重等比例放大。
- domain_fit / role_fit：偏好表中的值（0–1）。penalty：例如年資要求每超過一年扣固定值。
- 起始值：`weights {similarity: 0.45, skill_overlap: 0.25, domain_fit: 0.15, role_fit: 0.15}`；`preferred_roles {modeling_ds: 1.0, mle: 1.0, ai_engineer: 0.9, analytics_ds: 0.8, data_engineer: 0.7, swe: 0.6, data_analyst: 0.6}`。

## 8. 報告

- **每日摘要**：今日新增候選數（不含 baseline）；Top N（排除申請中職缺，可依職務類別分組）：公司、職稱、類別、地點、primary domain、總分與分項、sponsorship、缺少的技能、連結，可直接加入申請助手；新加入來源的既有職缺 Top N；已追蹤職缺的 JD 更新；已下架（只列申請過或進過 Top N 的）；系統狀態（失敗或 suspect 的來源、抽取錯誤、LLM 成本）。
- **每週趨勢**（同 content_hash 只算一次，依職務類別分開）：各領域新增數、active 數與週變化；必備技能 Top 20；技能缺口（高頻但我沒有，依出現在高匹配職缺的次數加權）；sponsorship 比例；待歸類；本週成本。
- Markdown 產生（`render.py`）與寄送（notifier）分開，測試只驗 Markdown。

## 9. 排程與資料持久化

- **在哪裡跑**：LinkedIn、Indeed 封鎖雲端主機 IP，爬取要在 Mac 上用 launchd 跑（住宅 IP）；ATS API 不受影響。最單純是整個雷達在本機跑、R2 只當備份（待決定事項 1）。
- **R2**（已決定）：私有 bucket（例如 `job-radar`），主檔 `jobs.duckdb`；只限該 bucket 的 Object Read & Write token；boto3 S3 client，`endpoint_url = https://<ACCOUNT_ID>.r2.cloudflarestorage.com`、`region_name = "auto"`；每次上傳另存 `backups/jobs-YYYY-MM-DD.duckdb`，lifecycle rule 刪除 30 天前備份；上傳前確認 DB 能開、`jobs` 筆數沒有驟減，否則只存 `backups/failed-<run_id>.duckdb` 並報錯。
- 遠端存取只在 `storage.py`（`DB_REMOTE` 留空 = 只用本地）；`job-radar db pull|push` 手動同步；一個檔案只有一個寫入者。申請助手的 `applications.duckdb` 之後同步到 R2，雷達只讀。
- 若部分放 GitHub Actions：`schedule` + `workflow_dispatch`、`concurrency` 一次一個、setup-uv 快取；排程可能延遲，查詢用時間區間；私有 repo 的免費分鐘數足夠。

## 10. 環境變數（`.env`）

```
ANTHROPIC_API_KEY=          # 我自己的金鑰；.env 會蓋過 shell 的同名變數
TAILOR_MODEL=claude-sonnet-5-5
LLM_MODEL=claude-haiku-5-5  # 雷達
DB_REMOTE=                  # s3://job-radar/jobs.duckdb；留空 = 只用本地
S3_ENDPOINT_URL=            # https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_ACCESS_KEY_ID=
S3_SECRET_ACCESS_KEY=
SMTP_HOST= SMTP_PORT= SMTP_USER= SMTP_PASSWORD= REPORT_EMAIL_TO=   # Email 摘要
```

---

# 三、進度

## Phase 1：申請助手 MVP（2026-10-22 完成）

- [x] 專案骨架、設定載入、logging、CLI
- [x] 職缺網址解析（ATS、LinkedIn、Indeed、Glassdoor、Jobright、其他），ATS 公開 API 取 JD
- [x] profile 格式與 `init-profile`；已放入我的履歷 `cv.pdf` 與由履歷整理的 highlights
- [x] 表單掃描、欄位分類、SafePage 填寫與送出防護
- [x] Claude 草稿、成本記錄、重新掃描沿用草稿
- [x] 本機操作頁面、申請狀態、`track`
- [x] Dock App（`install-app`）、單一執行個體、在受控 Chrome 開主頁、關閉即結束
- [x] 申請頁旁的側邊欄（Chrome 擴充功能）；沒有金鑰時只填答案庫
- [x] 等 React 接手再填（修 Greenhouse 下拉選單全失敗，含快取是空的情況）；區塊標示；工作經歷／學歷自動填；demographic 選項與同義選項對應；`inspect` 除錯指令
- [x] 自動勾目前在職、按「Add another」補填多筆經歷與學歷、科系備選、學校名稱完全比對；「我已送出」改成按兩下、靜態檔不再被快取；168 個自動測試
- [x] 介面重新設計：推薦／我的申請兩個分頁、四步進度與「下一步」卡片、推薦列表的分數環與職務篩選、側邊欄底部固定按鈕、深色模式
- [x] 分頁關掉後一鍵恢復（帶回按 ③ 確認過的答案）；推薦頁預先計算、記住答案不再讓推薦重算；171 個自動測試
- [x] 日曆型日期欄位（填完整日期、點日期關掉日曆）、Ashby 多行選項、點擊／勾選後以頁面實際狀態判斷成敗；174 個自動測試
- [x] 錯過的每日抓取在登入／開助手時補抓；「新職缺」改為近 3 天；抓完回報結果；176 個自動測試
- [x] 拿掉助手裡的作答框與 ③：沒填到的題目列成清單到申請頁自己填，② 之後直接「待送出」、出現「我已送出」
- [ ] 驗收：用 3 個真實職缺跑完整流程（先不接模型），修正抓錯或分類不對的欄位；之後放金鑰再驗草稿

## Phase 2：履歷客製化

- [ ] JD 關鍵字對照：必備／加分條件對照履歷與 highlights，列出可改用 JD 原詞之處與補不了的缺口
- [ ] 履歷修改建議：逐條 bullet，標註依據的 highlight id
- [ ] 履歷檢查：PDF 抽得出文字、數字都在素材庫、關鍵字覆蓋率前後比較
- [ ] 操作頁面的「關鍵字與履歷」區塊；職缺專用 resume.pdf 的選擇

完成標準：每條建議都有 highlight id；resume.pdf 放一個素材庫沒有的數字，檢查會擋下。

## Phase 3：職缺來源，開始每日累積（越早累積，趨勢越有料）

- [x] `radar/fetchers/base.py` 與 Greenhouse、Lever、Ashby fetcher；68 家公司
- [x] LinkedIn、Jobright 搜尋，對到 ATS 職缺、自動找新公司的職缺板
- [x] Simplify 的 GitHub 職缺清單（New Grad，可加實習）；README 給朋友的安裝與使用說明
- [x] 其他方向（例如硬體）：`only_roles`、內建 hardware / embedded 類別與硬體技能、職務標籤由設定決定
- [x] 共用 config 統整成軟體／資料／硬體三大類、預設中立；搜尋關鍵字跟著職務類別；約 20 家硬體公司；50 州地點；ITAR 排除
- [ ] 改成安裝工具：`uv tool install` 安裝與更新，`profile/`、`data/`、`.env` 搬到 repo 外（`~/Library/Application Support/Job Radar/`），共用預設跟著程式發布；使用者的 Claude Code 讀資料夾裡給使用者的說明，不讀這份開發文件
- [ ] Indeed、Glassdoor（Glassdoor 試過，對到 ATS 的比例太低，先不做）
- [x] 正規化、upsert、migration；fetch_results、runs、下架、suspect、baseline（跨來源去重等有第二種來源再做）
- [x] 職務類別 prefilter；`fetch`、`check-companies`
- [x] 每天 08:30 在 Mac 用 launchd 抓取
- [x] 個人設定放 `profile/` 同名檔、蓋過共用的 `config/`，朋友 clone 後 `git pull` 不衝突；178 個自動測試
- [x] 每日抓取改成「最近一個排程時間點之後沒抓過就抓」（修 11/02 早上被略過）
- [ ] R2 pull / push / 備份
- [x] 提前做的 Phase 5 部分：規則評分、`radar` 指令、主頁「推薦職缺」與「加入並開啟」

完成標準：連跑兩次 fetch 第二次新增 0；單一來源失敗不影響其他來源也不觸發下架；連續兩天自動執行成功。

## Phase 4：結構化

- [ ] skills.yaml、抽取 schema、`extract`（claude-haiku-5-5、prompt caching、extraction_errors、成本記錄）
- [ ] eval 集：人工標註 30 筆 JD，涵蓋六種職務類別；`job-radar eval`

完成標準：role_type 準確率與 domains F1 ≥ 80%（記在 `tests/eval/RESULTS.md`）；重跑 extract 不產生 API 呼叫。

## Phase 5：匹配與每日摘要

- [ ] `profile/skills.yaml`、embedding、硬性條件、評分；`match`、`report --daily`、`run`
- [ ] 第一個 notifier（待決定事項 2）；摘要職缺可直接加入申請助手並排除申請中職缺

完成標準：連續一週每天收到摘要，Top 10 裡想點開的過半；改 scoring.yaml 排名立即改變。

## Phase 6：擴大覆蓋與每週趨勢

- [ ] 50 家以上公司、各來源每日成功率 ≥ 95%；`report --weekly`；依「待歸類」擴充 taxonomy 與 skills

## 選做

- [ ] 答案庫：每次確認的答案存檔，草稿時附上過去的相關答案作參考（資料量小時直接放進 prompt，不需要 RAG）
- [ ] Streamlit dashboard（趨勢、申請漏斗）；申請紀錄同步到 Notion；H-1B LCA 公司 sponsorship 歷史；偵測送出成功頁

## 已決定

| 日期 | 決定 |
|---|---|
| 2026-10-05 | 雷達資料庫存 Cloudflare R2 |
| 2026-10-22 | 私人專案，不公開；先完成申請助手再做雷達 |
| 2026-10-22 | 可以爬 LinkedIn、Indeed、Glassdoor、Jobright，不遵守 robots.txt |
| 2026-10-22 | 職務範圍：DS、MLE、AI engineer、SWE、DE、DA |
| 2026-10-23 | 文件合併為這一份 CLAUDE.md |
| 2026-10-23 | 申請助手先不接模型試用；操作介面是 Dock App 加 Chrome 側邊欄，不部署到雲端 |
| 2026-10-23 | 雷達先只抓 ATS 公開 API（申請不用登入），規則評分不用 LLM；整個在 Mac 上用 launchd 每天 08:30 跑（原待決定 1） |
| 2026-10-23 | 初始公司清單：驗證過的 68 家（原待決定 3，之後自己增減）；地點：美國與 US remote（原待決定 4）；我需要 sponsorship，JD 寫明不提供的排除 |
| 2026-10-24 | 職缺網站先做 LinkedIn 與 Jobright（只抓搜尋結果、不登入），Glassdoor 先不做；關鍵字：AI engineer、data scientist、MLE、data engineer、data analyst（各加一組 new grad） |
| 2026-10-24 | 我 2027 年 5 月畢業：以 new grad / entry level 為主，實習只看 co-op / off-cycle，要求超過 2 年經驗的排除 |
| 2026-10-25 | 表單答案：政府官員／親屬在政府任職一律 No、Hispanic/Latino 一律 No（寫在 `applicant.yaml`）；科系沒有 Data Science 就選 Computer Science |
| 2026-11-01 | 助手不提供作答框：沒填到的題目只列出來，我到申請頁自己填；② 之後直接進入檢查並送出 |
| 2026-11-02 | 分享給朋友（都用 Mac、會用終端機）：clone 私人 repo 在自己的 Mac 跑，不部署（助手要控制本機的 Chrome）；雷達的個人設定放 `profile/` 同名檔 |
| 2026-11-02 | 加 Simplify 的 GitHub 清單當來源；README 寫給朋友的安裝與使用說明（規格仍只在 CLAUDE.md） |
| 2026-11-03 | 共用預設維持資料／AI／軟體；其他方向在 `profile/filters.yaml` 用 `only_roles`，hardware / embedded 內建但預設關閉（11/04 改成下一列） |
| 2026-11-04 | 使用者是 5–10 位會用終端機的朋友，方向是軟體（含 DS、DA、BA）與硬體：共用 config 涵蓋這些方向、預設全開且不偏向我，個人方向寫在各自的 `profile/`；下一步改用 `uv tool install`、資料搬出 repo（不做雲端、不做 Mac App 打包） |

## 待決定事項

| # | 問題 | 建議 | 時間點 |
|---|---|---|---|
| 2 | 報告輸出管道 | 先 Email，之後要可瀏覽的介面再加 Notion；推薦頁已經能看每日結果，可能不需要 | Phase 5 |
| 5 | 履歷版本 | 目前一份 `cv.pdf`；之後依類別分 ds、mle（兼 AI engineer）、swe、de、da | 需要時 |
| 6 | 履歷修改建議怎麼套用 | 履歷是 LaTeX：Phase 2 的建議可以直接改成 `cv.tex` 的 diff，再編譯成職缺專用 PDF | Phase 2 |
| 7 | 權重是否依職務類別分開 | 先共用一組，用 role_fit 表達偏好；累積約 30 筆申請結果後再評估 | 有結果後 |

## 成本估算

申請草稿每個職缺約 $0.05（只在按 ② 時產生）；雷達抽取每筆 JD 約 $0.001，首次回補約 5,000 筆約 $5，之後每月約 $1–3；GitHub Actions、R2 在免費額度內。實際花費看 log 與 `llm_cost_usd`。
