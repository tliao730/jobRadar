# Job Radar

在自己的 Mac 上跑的求職小幫手，有兩個功能：

- **推薦職缺**：每天早上自動抓新職缺，依你的條件排序。職缺來自 Greenhouse、Lever、Ashby 上約 70 家公司的公開職缺板、Simplify 的 New Grad 清單、LinkedIn。
- **申請助手**：替你打開申請頁、自動填好基本資料、經歷和常見題目，再列出還要你自己填的題目。**送出永遠是你自己按**，助手不會替你送出。

你的資料（個人資料、履歷、申請紀錄）都只存在你自己的電腦上，不會上傳到 git。

---

## 安裝（約 15 分鐘，只要做一次）

需要：macOS、[Google Chrome](https://www.google.com/chrome/)。

**1. 安裝 uv**（管理 Python 的工具；已經有了可以跳過）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

裝完關掉終端機再重新打開。

**2. 下載專案**

```bash
git clone https://github.com/tliao730/jobRadar.git "Job Radar"
cd "Job Radar"
uv sync
```

**3. 建立你的個人資料夾**

```bash
uv run job-radar init-profile
```

這會建立 `profile/` 資料夾和幾個範本檔，已經存在的檔案不會被覆蓋。

**4. 填資料**（細節見[補充 A](#a-個人資料怎麼填)）

- `profile/applicant.yaml`：姓名、email、電話、學歷、工作經歷、常見題目的答案。
- `profile/resumes/`：把履歷 PDF 放進去。
- `profile/highlights.yaml`：經歷素材，選填，但填了推薦會比較準。

**5. 放到 Dock、開啟每日抓取**

```bash
uv run job-radar install-app
uv run job-radar install-schedule
```

**6. 打開來用**

點 Dock 上的 **Job Radar**。第一次開會先抓一次職缺，大約 2–4 分鐘。

到這裡就設定好了。想調整推薦條件，或讓助手幫你寫開放題的建議答案，請看下面的補充說明。

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

共用的預設在 `config/` 資料夾，那是大家共用、放在 git 裡的檔案，**不要改**。你個人的設定寫在 `profile/` 裡同名的三個檔案，**只寫跟預設不一樣的部分**，其他照預設。這樣 `git pull` 更新時永遠不會衝突。

- **`profile/filters.yaml`**：要找的層級、職務、地點、sponsorship。預設是以 New Grad / Entry Level 為主、實習只看 co-op / off-cycle、要求超過 2 年經驗的排除、JD 寫明不提供 sponsorship 的排除、地點限美國。

  ```yaml
  levels:
    want: [intern, new_grad]        # 也想看實習
  sponsorship:
    exclude_no_sponsorship: false   # 不需要 sponsorship
  roles:
    - {id: swe, weight: 1.0}        # 主要找 SWE（weight 0–1，越高越前面）
    - {id: da, enabled: false}      # 不看 data analyst
  ```

  職務類別有 `ds`、`mle`、`ai_engineer`、`swe`、`de`（data engineer）、`da`（data analyst），定義在 `config/filters.yaml`。

- **`profile/companies.yaml`**：要多抓或不抓的公司。推薦頁上方「找到的公司」按 **＋ 加入** 也會寫進這裡。

  ```yaml
  companies:
    - {name: "Stripe", platform: greenhouse, token: stripe}   # 多抓一家
    - {platform: ashby, token: openai, enabled: false}        # 不抓共用清單裡的某家
  ```

  `token` 是職缺板網址裡的代號，例如 `job-boards.greenhouse.io/stripe`、`jobs.lever.co/xxx`、`jobs.ashbyhq.com/xxx`。加完執行 `uv run job-radar check-companies` 確認代號正確。

- **`profile/sources.yaml`**：LinkedIn / Jobright 的搜尋關鍵字、要不要用某個網站、Simplify 要讀哪些清單。

  ```yaml
  queries:                          # 整個取代預設的關鍵字
    - software engineer new grad
    - software engineer
  jobright:
    enabled: false                  # 不用 Jobright
  ```

改完不用重開助手：`filters.yaml` 下次打開推薦頁就生效；`companies.yaml`、`sources.yaml` 在下次抓取時生效。

### C. 職缺從哪裡來、哪些能自動填

| 來源 | 怎麼抓 | 能自動填嗎 |
|---|---|---|
| Greenhouse / Lever / Ashby 職缺板 | 公司公開的 API（`config/companies.yaml` 約 70 家，加上你自己的） | 能 |
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

- 換時間：`uv run job-radar install-schedule --at 07:00`
- 取消：`uv run job-radar install-schedule --remove`
- 紀錄：`data/logs/fetch.log`
- 隨時都可以在推薦頁按 **重新抓取**。

### E. 讓 Claude 寫開放題的建議答案（選用）

不設定也能用：答案庫的題目照樣自動填，開放題就自己寫。

想要建議答案的話，把 `.env.example` 複製成 `.env`，填入你自己的 [Anthropic API key](https://console.anthropic.com/)：

```bash
cp .env.example .env
# 編輯 .env：ANTHROPIC_API_KEY=sk-ant-...
```

之後按 ② 時，沒填到的題目旁邊會附上建議答案，你再自己貼到申請頁。

- 建議只根據你 `profile/` 裡的履歷和經歷素材寫，素材裡沒有的內容會標成 `[補充：…]`，不會亂編。
- 每個職缺大約 US$0.05，只在按 ② 時花費，重按不會重複收費。
- 右上角的圓點會顯示資料是否齊全，包括基本資料、履歷、經歷素材、草稿模型。

### F. 更新到新版

```bash
cd "Job Radar"
git pull && uv sync
```

然後關掉助手的 Chrome 視窗，再點一次 Dock 圖示。你在 `profile/` 的資料和設定不受影響。

### G. 常見問題

- **某個欄位填錯或沒填到**：助手會把它列在「要你自己填」的清單裡，直接在申請頁改就好。常遇到的題目可以加進答案庫（[補充 A](#a-個人資料怎麼填)）。
- **申請頁要登入或註冊**（例如 Workday）：助手會停下來，你在那個 Chrome 視窗手動登入一次就好，之後會記住。多頁式的表單每一頁按一次 ②。
- **遇到 CAPTCHA 或「確認你是真人」**：助手會停下，交給你處理。
- **不小心關掉填好的分頁**：「我的申請」會標「分頁已關」，按 **恢復申請頁** 會重新打開並再填一次。直接在頁面上打的字救不回來。
- **點 Dock 圖示沒反應**：看 `data/logs/ui.log`。如果搬動過專案資料夾，要重跑 `uv run job-radar install-app`。
- **推薦太少或太多**：用 `uv run job-radar radar --excluded` 看每個職缺被排除的原因，再照[補充 B](#b-調整推薦條件) 調整。

### H. 常用指令

| 指令 | 用途 |
|---|---|
| `uv run job-radar ui` | 打開助手（等於點 Dock 圖示） |
| `uv run job-radar fetch` | 立刻抓一次職缺 |
| `uv run job-radar radar` | 在終端機列出推薦（加 `--excluded` 會列出排除原因） |
| `uv run job-radar check-companies` | 檢查公司代號是否正確 |
| `uv run job-radar apply add <網址>` | 加入職缺（也可以在主頁貼網址） |
| `uv run job-radar inspect <網址> --fill` | 在暫時的 Chrome 試填一個表單、列出每題的結果（不會送出） |

開發規格、設計細節與進度在 [CLAUDE.md](CLAUDE.md)。
