# Job Radar

在自己的 Mac 上跑的求職小幫手，有兩個功能：

- **推薦職缺**：每天早上自動抓新職缺，依你的條件排序。職缺來自 Greenhouse、Lever、Ashby 上約 90 家公司（軟體、AI、硬體）的公開職缺板、Simplify 的 New Grad 清單、LinkedIn。涵蓋**軟體、資料（DS / DA / BA）、硬體**三大方向的 New Grad 職缺，在第 5 步選你要的方向。
- **申請助手**：替你打開申請頁、自動填好基本資料、經歷和常見題目，再列出還要你自己填的題目。**送出永遠是你自己按**，助手不會替你送出。

程式用 `uv tool install` 安裝；你的資料（個人資料、履歷、設定、申請紀錄、金鑰）都放在**你的資料夾** `~/Library/Application Support/Job Radar/`，只存在你自己的電腦上。下面說的 `profile/...`、`data/...` 都在這個資料夾裡。

---

## 安裝（約 15 分鐘，只要做一次）

需要：macOS、[Google Chrome](https://www.google.com/chrome/)、能讀這個私人 repo 的 GitHub 帳號。以前用 `git clone` 裝過的，請看[補充 F](#f-更新到新版從舊版換過來)。

**1. 安裝 uv**（管理 Python 的工具；已經有了可以跳過）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

裝完關掉終端機再重新打開。

**2. 安裝 Job Radar**

```bash
uv tool install git+https://github.com/tliao730/jobRadar.git
```

- 出現要密碼或 `Authentication failed`：這是私人 repo，先登入 GitHub（`brew install gh`、`gh auth login`），再裝一次。
- 裝完找不到 `job-radar` 指令：執行 `uv tool update-shell`，重開終端機。

**3. 建立你的資料夾**

```bash
job-radar init-profile
```

這會建立你的資料夾和裡面的範本檔，已經存在的檔案不會被覆蓋。`job-radar home --open` 會用 Finder 打開它（`~/Library` 在 Finder 裡預設是隱藏的），也可以用編輯器打開：`code "$(job-radar home --path)"`。

**4. 填資料**（細節見[補充 A](#a-個人資料怎麼填)）

- `profile/applicant.yaml`：姓名、email、電話、學歷、工作經歷、常見題目的答案。
- `profile/resumes/`：把履歷 PDF 放進去。
- `profile/highlights.yaml`：經歷素材，選填，但填了推薦會比較準。

**5. 選你要找的方向**

不設定的話，軟體、資料、硬體全部都會推薦。在 `profile/filters.yaml` 加一行 `only_roles`，只看你要的：

```yaml
only_roles: [hardware]          # 硬體：ASIC / FPGA、類比 / RF、電機 / 測試、嵌入式
```

```yaml
only_roles: [software]          # 軟體：SWE、MLE、AI engineer、data engineer、SRE / 資安
```

```yaml
only_roles: [ds, da, ba]        # 資料：data science、data analyst、business analyst
```

大類和細項可以混著寫，例如 `[software, ds]`。LinkedIn 的搜尋關鍵字會自動跟著你選的方向。所有類別見[補充 B](#b-調整推薦條件)。

**6. 放到 Dock、開啟每日抓取**

```bash
job-radar install-app
job-radar install-schedule
```

**7. 打開來用**

點 Dock 上的 **Job Radar**。第一次開會先抓一次職缺，大約 2–4 分鐘。

到這裡就設定好了。想再調整推薦條件，或讓助手幫你寫開放題的建議答案，請看下面的補充說明。

---

## 每天怎麼用

1. 點 Dock 的 Job Radar，會打開一個專用的 Chrome 視窗。
2. 在 **推薦職缺** 勾選想申請的職缺，按底部的 **加入並開啟**。
3. 助手會打開申請頁並自動填寫。也可以在 **我的申請** 對任一職缺按 **② 自動填寫**。
4. 畫面會列出「要你在申請頁自己填」的題目，例如開放題、人口統計題、沒有對到的選項。到申請頁把它們補上，整頁檢查一遍，**自己按送出**。
5. 回到助手按 **我已送出**（要連按兩下，避免按錯）。

**側邊欄**：在申請頁按 Chrome 右上角的 Job Radar 圖示（或 ⌘⇧Y），旁邊會出現同樣的清單和按鈕，不用切回主頁。第一次用時建議把圖示釘選在工具列。

關掉這個 Chrome 視窗（所有分頁），助手就會結束。

---

## 補充說明

### A. 個人資料怎麼填

所有檔案都在 `profile/`，每個檔案開頭都有註解和範例。

| 檔案 | 內容 | 必要嗎 |
|---|---|---|
| `applicant.yaml` | 基本資料、學歷 `education`、工作經歷 `employment`（最近的放最前面）、答案庫 `answers`、人口統計偏好 `eeo` | 必要 |
| `resumes/*.pdf` | 履歷，檔名就是版本名稱。只有一份時一律用它 | 必要 |
| `highlights.yaml` | 經歷素材：情境、做了什麼、結果與數字、用到的技能 | 建議 |
| `skills.yaml` | 履歷沒寫到但你會的技能，例如 `skills: [Spark, dbt]`。只用來排序推薦 | 選填 |

**答案庫**（`applicant.yaml` 的 `answers`）：題目文字符合 `match` 時就自動填 `answer`。範本已經列好最常見的幾題，例如工作許可、sponsorship、怎麼知道這個職缺，填上答案就會生效。常遇到的新題目可以自己加一條：

```yaml
answers:
  - match: "(require|need).*sponsorship"
    answer: "Yes"
  - match: "earliest start date"
    answer: "June 2027"
```

**人口統計題**（性別、族裔、退伍軍人等）：預設全部留給你自己選。想自動填的話寫在 `eeo`，例如 `gender: "Decline to self-identify"`。

### B. 調整推薦條件

共用的預設跟著程式一起安裝（`job-radar home` 會列出位置），更新時會被新版取代，所以**不要改**。你個人的設定寫在你資料夾 `profile/` 裡的同名檔案，**只寫跟預設不一樣的部分**，其他照預設，更新也不會動到。

也可以請 Claude Code 幫你調：在你的資料夾裡開 Claude Code（`cd "$(job-radar home --path)" && claude`），它會讀資料夾裡的 `CLAUDE.md`，知道該改哪個檔案、怎麼確認結果。

- **`profile/filters.yaml`**：要找的職務、層級、地點、sponsorship。預設是全部職務、以 New Grad / Entry Level 為主、實習只看 co-op / off-cycle、要求超過 2 年經驗的排除、JD 寫明不提供 sponsorship 或只收美國公民（ITAR）的排除、地點限美國。

  **職務**：職稱符合某個「職務類別」的才會推薦。`only_roles` 可以寫大類，也可以寫類別 id：

  | 大類 | id | 推薦頁顯示 | 包含的職稱（例） |
  |---|---|---|---|
  | `software` | `swe` | SWE | software engineer / developer、SDE、frontend、backend、full stack、iOS / Android |
  | | `mle` | MLE | machine learning engineer、applied scientist |
  | | `ai_engineer` | AI Engineer | AI engineer、LLM、generative AI |
  | | `de` | Data Eng | data engineer、analytics engineer |
  | | `infra` | Infra / Security | SRE、DevOps、cloud / platform engineer、security engineer |
  | `data` | `ds` | Data Science | data scientist、research scientist、quant |
  | | `da` | Data Analyst | data analyst、BI analyst、product analyst |
  | | `ba` | Business Analyst | business analyst、business operations、strategy & operations、technology analyst |
  | `hardware` | `digital` | Digital / ASIC | ASIC、FPGA、RTL、SoC、design verification、physical design、DFT |
  | | `analog` | Analog / RF | analog、mixed-signal、RF、circuit design、power electronics、photonics |
  | | `electrical` | Hardware / Electrical | hardware engineer、electrical engineer、PCB、avionics、test engineer |
  | | `embedded` | Embedded / Firmware | embedded software、firmware、device drivers |

  大類裡有一類不想看，就把它關掉：

  ```yaml
  only_roles: [hardware]
  roles:
    - {id: analog, enabled: false}
  ```

  內建沒有的方向可以自己加一類：`titles` 是職稱的 regex（不分大小寫），`queries` 是 LinkedIn 的搜尋關鍵字，記得也加進 `only_roles`：

  ```yaml
  only_roles: [hardware, mech]
  roles:
    - {id: mech, name: Mechanical, titles: ['mechanical', 'mechatronics'], queries: [mechanical engineer new grad]}
  ```

  每一類的定義在共用預設的 [`filters.yaml`](https://github.com/tliao730/jobRadar/blob/main/src/job_radar/defaults/filters.yaml) 的 `roles`。覺得哪種職稱被漏掉或分錯類，對大家都適用的請發 issue 或 PR（見[補充 I](#i-改程式或共用預設發-pr)）。

  **其他常改的設定**：

  ```yaml
  levels:
    want: [intern, new_grad]        # 也想看實習（co-op / off-cycle）
  sponsorship:
    exclude_no_sponsorship: false   # 不需要 sponsorship（只收美國公民的職缺也會留下）
  roles:
    - {id: swe, weight: 0.5}        # SWE 排後面一點（weight 0–1，預設 1）
  ```

  **找暑期實習**：預設只留 co-op / off-cycle 實習。要找一般的暑期實習：

  ```yaml
  levels:
    want: [intern]
    intern_requires: []
    intern_requires_in_jd: []
  ```

  再照[補充 C](#c-職缺從哪裡來哪些能自動填) 加上 Simplify 的實習清單。

- **`profile/companies.yaml`**：要多抓或不抓的公司。推薦頁上方「找到的公司」按 **＋ 加入** 也會寫進這裡。

  ```yaml
  companies:
    - {name: "Stripe", platform: greenhouse, token: stripe}   # 多抓一家
    - {platform: ashby, token: openai, enabled: false}        # 不抓共用清單裡的某家
  ```

  `token` 是職缺板網址裡的代號，例如 `job-boards.greenhouse.io/stripe`、`jobs.lever.co/xxx`、`jobs.ashbyhq.com/xxx`。加完執行 `job-radar check-companies` 確認代號正確。

  共用清單有約 70 家軟體／AI 公司，和約 20 家硬體公司（SpaceX、Anduril、Rocket Lab、Astera Labs、Tenstorrent、Samsung Semiconductor…）。

  NVIDIA、Apple、AMD、Intel、Qualcomm 這類大公司用 Workday 或自己的系統，沒辦法加進來。它們的職缺會從 Simplify 和 LinkedIn 進來，列在「需要自己開啟」。

- **`profile/sources.yaml`**：要不要用某個網站、Simplify 要讀哪些清單、自己指定搜尋關鍵字。關鍵字預設跟著 `only_roles` 選的類別走，通常不用改。

  ```yaml
  queries:                          # 自己指定（整個取代自動產生的關鍵字）
    - FPGA engineer new grad
  jobright:
    enabled: false                  # 不用 Jobright
  ```

- **`profile/settings.yaml`**：申請助手本身的設定，例如埠號（8765 被佔用時）、依職稱建議用哪一份履歷。範本裡有範例。

改完不用重開助手：`filters.yaml` 下次打開推薦頁就生效，已經抓到的職缺會照新設定重新篩選；`companies.yaml`、`sources.yaml` 在下次抓取時生效，想馬上看到就按 **重新抓取**。`settings.yaml` 要重開助手。

### C. 職缺從哪裡來、哪些能自動填

| 來源 | 怎麼抓 | 能自動填嗎 |
|---|---|---|
| Greenhouse / Lever / Ashby 職缺板 | 公司公開的 API（共用清單約 90 家，加上你自己的） | 能 |
| Simplify | 讀 Simplify 在 GitHub 公開的 [New Grad 清單](https://github.com/SimplifyJobs/New-Grad-Positions)，每天下載整份 | 連結是 Greenhouse / Lever / Ashby 的能；Workday 等其他系統列在「需要自己開啟」 |
| LinkedIn | 不登入的職缺搜尋，只看搜尋結果 | 能對到上面職缺板的就能；對不到的要自己開 |
| Jobright | 不登入的搜尋頁 | 同上（目前常被真人驗證擋下） |

- Simplify 的資料沒有 JD，所以推薦分數只看職稱和層級。年資和 sponsorship 的篩選要等 JD 有寫才擋得掉，加入前還是要自己看一下 JD。
- 也想看 Simplify 的實習清單，在 `profile/sources.yaml` 加上：

  ```yaml
  simplify:
    repos:                          # 會取代預設，所以要兩個都列
      - SimplifyJobs/New-Grad-Positions
      - SimplifyJobs/Summer2026-Internships
  ```

- LinkedIn 和 Jobright 很容易限流或要求真人驗證。遇到時助手會停下這個來源、保留其他來源的結果，並在推薦頁顯示「N 個來源失敗」。這是正常的，隔天再試就好。
- 助手**永遠不會登入你的 LinkedIn 或其他帳號**，以免帳號被封。

### D. 每日自動抓取

`install-schedule` 會在每天 08:30 自動抓一次。Mac 當時關機或睡眠的話，會在開機登入或打開助手時補抓。

- 換時間：`job-radar install-schedule --at 07:00`
- 取消：`job-radar install-schedule --remove`
- 紀錄：你資料夾裡的 `data/logs/fetch.log`
- 隨時都可以在推薦頁按 **重新抓取**。

### E. 讓 Claude 寫開放題的建議答案（選用）

不設定也能用：答案庫的題目照樣自動填，開放題就自己寫。

想要建議答案的話，在你資料夾的 `.env`（`init-profile` 建好了）填入你自己的 [Anthropic API key](https://console.anthropic.com/)：

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

之後按 ② 時，沒填到的題目旁邊會附上建議答案，你再自己貼到申請頁。

- 建議只根據你 `profile/` 裡的履歷和經歷素材寫，素材裡沒有的內容會標成 `[補充：…]`，不會亂編。
- 每個職缺大約 US$0.05，只在按 ② 時花費，重按不會重複收費。
- 右上角的圓點會顯示資料是否齊全，包括基本資料、履歷、經歷素材、草稿模型。

### F. 更新到新版、從舊版換過來

**更新**：

```bash
uv tool upgrade job-radar
```

然後關掉助手的 Chrome 視窗，再點一次 Dock 圖示。你資料夾裡的資料和設定不受影響。

**以前用 `git clone` 裝的**（資料在專案資料夾的 `profile/`、`data/`、`.env`）：先關掉助手的 Chrome 視窗，然後：

```bash
uv tool install git+https://github.com/tliao730/jobRadar.git
cd "Job Radar"          # 舊的專案資料夾
job-radar migrate
```

`migrate` 會把 `profile/`、`data/`、`.env` 搬到你的資料夾，並把 Dock App 和每日抓取改成用新裝的版本。搬完之後舊的專案資料夾就用不到了，可以刪掉。**不要先跑 `init-profile`**：那會先建好空的範本，`migrate` 為了不覆蓋就不會搬。還沒搬之前，舊的資料夾照樣能用（`git pull` 之後也是）。

### G. 常見問題

- **某個欄位填錯或沒填到**：助手會把它列在「要你自己填」的清單裡，直接在申請頁改就好。常遇到的題目可以加進答案庫（[補充 A](#a-個人資料怎麼填)）。
- **申請頁要登入或註冊**（例如 Workday）：助手會停下來，你在那個 Chrome 視窗手動登入一次就好，之後會記住。多頁式的表單每一頁按一次 ②。
- **遇到 CAPTCHA 或「確認你是真人」**：助手會停下，交給你處理。
- **不小心關掉填好的分頁**：「我的申請」會標「分頁已關」，按 **恢復申請頁** 會重新打開並再填一次。直接在頁面上打的字救不回來。
- **點 Dock 圖示沒反應**：看你資料夾裡的 `data/logs/ui.log`。重裝過 uv 或 Job Radar 的話，重跑 `job-radar install-app`。
- **推薦混了不是我要的方向**：預設全部方向都推薦。照安裝第 5 步在 `profile/filters.yaml` 寫 `only_roles`，打開推薦頁就會重新篩選；按 **重新抓取** 會用新方向的關鍵字搜 LinkedIn。
- **推薦太少或太多**：用 `job-radar radar --excluded` 看每個職缺被排除的原因，再照[補充 B](#b-調整推薦條件) 調整。

### H. 常用指令

| 指令 | 用途 |
|---|---|
| `job-radar ui` | 打開助手（等於點 Dock 圖示） |
| `job-radar home` | 顯示你的資料夾和共用預設的位置（`--open` 用 Finder 打開，`--path` 只印路徑） |
| `job-radar fetch` | 立刻抓一次職缺 |
| `job-radar radar` | 在終端機列出推薦（加 `--excluded` 會列出排除原因） |
| `job-radar check-companies` | 檢查公司代號是否正確 |
| `job-radar apply add <網址>` | 加入職缺（也可以在主頁貼網址） |
| `job-radar inspect <網址> --fill` | 在暫時的 Chrome 試填一個表單、列出每題的結果（不會送出） |
| `uv tool upgrade job-radar` | 更新到新版 |

### I. 改程式或共用預設、發 PR

共用預設（職務類別、技能詞彙、公司清單）在 repo 的 `src/job_radar/defaults/`。改了會影響每個人，所以走 PR：

```bash
git clone https://github.com/tliao730/jobRadar.git && cd jobRadar
uv sync
uv tool install --editable .    # 選用：讓 Dock App 和每日抓取直接跑這份程式碼
```

在 clone 裡用 `uv run job-radar ...` 執行，讀寫的是同一個你的資料夾。改完開一個分支，確認 `uv run ruff check . && uv run ruff format . && uv run pytest` 全部通過再發 PR（`gh pr create`）。只對你自己有用的調整（方向、層級、公司）請放在你的 `profile/`，不要改共用預設。開發規格、設計細節與進度在 [CLAUDE.md](CLAUDE.md)。
