# Job Radar：我的資料夾

這是 Job Radar（求職小幫手）的個人資料夾。程式本身是用 `uv tool install` 裝的，不在這裡；這裡只有我的資料和設定。

## 檔案

- `profile/applicant.yaml`：基本資料、學歷、工作經歷、答案庫（`answers`）、人口統計偏好（`eeo`）
- `profile/highlights.yaml`：經歷素材。申請草稿只引用這裡、履歷和 applicant.yaml 的事實
- `profile/resumes/*.pdf`：履歷，檔名就是版本名稱
- `profile/skills.yaml`：履歷沒寫到但我會的技能，格式 `skills: [Spark, dbt]`，只用來排序推薦
- `profile/filters.yaml`、`sources.yaml`、`companies.yaml`、`settings.yaml`：我的設定，只寫跟共用預設不一樣的部分
- `data/`：資料庫、紀錄（`data/logs/`）、瀏覽器設定檔。不要手動改
- `.env`：Anthropic 金鑰。不要印出來，也不要貼到任何地方

## 調整推薦

1. 先看結果和排除原因：`job-radar radar --limit 40`、`job-radar radar --excluded`。
2. 共用預設在 `job-radar home` 列出的 defaults 資料夾，唯讀，更新程式時會被取代：
   - `filters.yaml`：職務類別（`roles` 的 id、group、titles、queries）、層級、地點、sponsorship
   - `skills.yaml`：技能詞彙
   - `companies.yaml`：共用的公司清單
3. 只改 `profile/` 裡的同名檔，只寫要改的設定：寫了的設定蓋過共用的，清單整個取代，`roles` 依 id 合併，公司依 platform + token 合併。
   - 選方向：`only_roles: [hardware]`。可以寫大類（software、data、hardware）或類別 id
   - 共用預設沒有的職務：在 `roles` 加一類（id、name、titles 是職稱的 regex、queries 是搜尋關鍵字），並加進 `only_roles`
   - 多抓一家公司：在 `profile/companies.yaml` 加 `{name, platform, token}`，再跑 `job-radar check-companies`
4. 改完再跑一次 `job-radar radar` 確認。`companies.yaml`、`sources.yaml` 要等 `job-radar fetch` 之後才生效。

覺得共用預設本身有問題（例如某種職稱被分錯類）的話，那是大家都會遇到的，到 GitHub repo 發 issue 或 PR，不要改 defaults 資料夾。

## 規則

- 申請表單永遠由我自己按送出，不要寫任何會自動送出的東西。
- 申請素材只用 `profile/` 裡的事實，不編造經歷、技能或數字。
- 更新程式：`uv tool upgrade job-radar`，再重開助手。
