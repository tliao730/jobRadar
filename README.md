# Job Radar

在自己的 Mac 上跑的求職小幫手，有兩個功能：

- **推薦職缺**：每天早上自動抓新職缺，依你的條件排序。職缺來自 Greenhouse、Lever、Ashby 上約 70 家公司的公開職缺板、Simplify 的 New Grad 清單、LinkedIn。預設找的是**資料／AI／軟體**方向的 New Grad 職缺，其他方向（例如硬體）照第 5 步改一下設定就好。
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

**5. 選你要找的方向**（找資料／AI／軟體職缺的可以跳過）

預設只推薦 data science、ML、AI engineer、data engineer、data analyst、SWE。找別的方向時，改 `profile/` 裡的兩個檔案。以硬體為例：

`profile/filters.yaml`：只看硬體和嵌入式

```yaml
only_roles: [hardware, embedded]
```

`profile/sources.yaml`：LinkedIn 的搜尋關鍵字

```yaml
queries:
  - hardware engineer new grad
  - electrical engineer new grad
  - embedded software engineer new grad
```

其他方向、多抓哪些公司，見[補充 B](#b-調整推薦條件)。

**6. 放到 Dock、開啟每日抓取**

```bash
uv run job-radar install-app
uv run job-radar install-schedule
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

共用的預設在 `config/` 資料夾，那是大家共用、放在 git 裡的檔案，**不要改**。你個人的設定寫在 `profile/` 裡同名的三個檔案，**只寫跟預設不一樣的部分**，其他照預設。這樣 `git pull` 更新時永遠不會衝突。

- **`profile/filters.yaml`**：要找的職務、層級、地點、sponsorship。預設是資料／AI／軟體職務、以 New Grad / Entry Level 為主、實習只看 co-op / off-cycle、要求超過 2 年經驗的排除、JD 寫明不提供 sponsorship 的排除、地點限美國。

  **職務**：職稱符合某個「職務類別」的才會推薦。內建的類別：

  | id | 推薦頁顯示 | 預設 |
  |---|---|---|
  | `mle` | MLE | 開 |
  | `ai_engineer` | AI Engineer | 開 |
  | `ds` | Data Science | 開 |
  | `de` | Data Eng | 開 |
  | `da` | Analyst | 開 |
  | `swe` | SWE | 開 |
  | `hardware` | Hardware（electrical、ASIC、FPGA、RTL、verification、analog、PCB…） | 關 |
  | `embedded` | Embedded（embedded、firmware） | 關 |

  用 `only_roles` 指定只看哪幾類，沒列到的都不看。內建沒有的方向可以自己加一類，職稱符合 `titles` 任一條就算（regex、不分大小寫），記得也加進 `only_roles`：

  ```yaml
  only_roles: [hardware, embedded, mech]
  roles:
    - {id: mech, name: Mechanical, titles: ['mechanical', 'mechatronics']}
  ```

  每一類的關鍵字定義在 `config/filters.yaml` 的 `roles`。覺得有職缺被漏掉，可以在自己的檔案裡補（同一個 id 會蓋過共用的，`titles` 要列出全部）。

  **其他常改的設定**：

  ```yaml
  levels:
    want: [intern, new_grad]        # 也想看實習
  sponsorship:
    exclude_no_sponsorship: false   # 不需要 sponsorship
  roles:
    - {id: swe, weight: 1.0}        # 主要找 SWE（weight 0–1，越高越前面）
    - {id: da, enabled: false}      # 不看 data analyst
  ```

- **`profile/companies.yaml`**：要多抓或不抓的公司。推薦頁上方「找到的公司」按 **＋ 加入** 也會寫進這裡。

  ```yaml
  companies:
    - {name: "Stripe", platform: greenhouse, token: stripe}   # 多抓一家
    - {platform: ashby, token: openai, enabled: false}        # 不抓共用清單裡的某家
  ```

  `token` 是職缺板網址裡的代號，例如 `job-boards.greenhouse.io/stripe`、`jobs.lever.co/xxx`、`jobs.ashbyhq.com/xxx`。加完執行 `uv run job-radar check-companies` 確認代號正確。

  共用清單大多是 AI／軟體公司。找硬體的話，可以先加這幾家（都驗證過，New Grad 硬體職缺多）：

  ```yaml
  companies:
    - {name: "SpaceX", platform: greenhouse, token: spacex}
    - {name: "Anduril", platform: greenhouse, token: andurilindustries}
    - {name: "Rocket Lab", platform: greenhouse, token: rocketlab}
    - {name: "Astranis", platform: greenhouse, token: astranis}
    - {name: "Astera Labs", platform: greenhouse, token: asteralabs}
    - {name: "Shield AI", platform: lever, token: shieldai}
  ```

  NVIDIA、Apple、AMD、Intel、Qualcomm 這類大公司用 Workday 或自己的系統，沒辦法加進來。它們的職缺會從 Simplify 和 LinkedIn 進來，列在「需要自己開啟」。

- **`profile/sources.yaml`**：LinkedIn / Jobright 的搜尋關鍵字、要不要用某個網站、Simplify 要讀哪些清單。預設的關鍵字是資料／AI 職缺，方向不同就一定要改。

  ```yaml
  queries:                          # 整個取代預設的關鍵字
    - software engineer new grad
    - software engineer
  jobright:
    enabled: false                  # 不用 Jobright
  ```

改完不用重開助手：`filters.yaml` 下次打開推薦頁就生效，已經抓到的職缺會照新設定重新篩選；`companies.yaml`、`sources.yaml` 在下次抓取時生效，想馬上看到就按 **重新抓取**。

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
- **推薦的都不是我要的方向**（例如找硬體，卻全是軟體職缺）：預設只看資料／AI／軟體。照安裝第 5 步在 `profile/filters.yaml` 寫 `only_roles`、在 `profile/sources.yaml` 改關鍵字，再按 **重新抓取**。
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
