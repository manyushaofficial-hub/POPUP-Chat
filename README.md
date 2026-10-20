# 快閃店現場助理 LINE Bot

現場工作人員在 LINE 上描述客人的問題或現場狀況，機器人會：

1. **FAQ 有答案的** → 顯示官方 FAQ **原文**（不改寫），確保現場說法和官方公告一致
2. **FAQ 沒涵蓋的臨場狀況** → 依你設定的「應變框架」判斷，給出處理步驟和建議對客人說的話
3. **需要升級的**（安全、規則例外、客訴升高）→ 標示 🚨 並附上該通知的窗口與聯絡方式

```
工作人員：客人沒預約，但說他從高雄特地上來，一直拜託讓他進去

🧭 現場判斷建議
狀況：未預約客人要求例外入場

【相關官方 FAQ】
〔R02〕沒有預約可以現場入場嗎？
每日保留少量現場名額，於開店時在入口處發放號碼牌，發完為止。…

【你可以這樣做】
1. 先同理客人遠道而來的辛苦
2. 確認今日現場號碼牌是否還有，有的話協助領取
3. 已發完則說明規則對所有人一致，建議改約其他時段
…
【建議對客人說】
真的很謝謝您特地從高雄過來！…
依據規則：EXCEPTION
```
（以上為示意，實際內容由 Claude 依你的設定產生）

---

## 你要設定的兩個檔案

| 檔案 | 內容 | 修改後 |
|---|---|---|
| `config/faq.yaml` | 官方已公布的 FAQ（id / 問題 / 答案 / 關鍵字） | 存檔即生效 |
| `config/playbook.yaml` | 店家資訊、判斷優先順序、原則、情境規則、升級窗口、禁止事項、回覆語氣 | 存檔即生效 |

**FAQ 也可以放 Google 試算表**：欄位為 `id, category, question, answer, keywords`，
「檔案 → 共用 → 發布到網路 → 選 CSV」，把網址填到 `.env` 的 `FAQ_SHEET_CSV_URL`。
每 5 分鐘自動更新，或由管理員在 LINE 輸入 `/reload` 立即更新。

### 怎麼寫好情境規則（playbook.yaml → scenarios）
```yaml
- id: ANGRY                 # 簡短代號，回覆最後會顯示「依據規則：ANGRY」
  when: 客訴、情緒激動…       # 什麼情況適用（寫越多種說法越容易被判斷到）
  do:                        # 工作人員該做的事，依順序
    - 先引導到旁邊…
  escalate: 現場主管          # 什麼時候、找誰
```
`priorities`（優先順序）決定規則衝突時怎麼取捨，`principles` 是所有判斷都要遵守的底線。

---

## LINE 上的指令

| 指令 | 用途 |
|---|---|
| 直接打字 | 問問題／描述狀況（可以追問，機器人記得前幾輪） |
| `新狀況` | 清除上下文，換問別的事 |
| `/faq` | 列出官方 FAQ |
| `/myid` | 顯示自己的 userId（用來開權限） |
| `/reload` | （管理員）立即重新載入 FAQ |
| `/gaps` | （管理員）列出 FAQ 沒涵蓋的問題，拿來補下一版 FAQ |

在**群組**中，訊息要以 `?` 開頭機器人才會回應（例如 `?客人問可以刷卡嗎`），避免干擾一般聊天。
所有問答都會記錄在 `logs/questions.jsonl`。

---

## 安裝與上線

### 1. 建立 LINE 官方帳號 Messaging API
1. 到 [LINE Developers Console](https://developers.line.biz/console/) 建立 Provider → 建立 **Messaging API** channel
2. 在 **Basic settings** 複製 `Channel secret`
3. 在 **Messaging API** 分頁發行 `Channel access token (long-lived)`
4. 在 LINE Official Account Manager 關閉「自動回應訊息」、開啟「Webhook」

### 2. 取得 Claude API Key
到 [Claude Console](https://platform.claude.com/) 建立 API key。

### 3. 本機測試（不用接 LINE）
```bash
pip install -r requirements.txt
cp .env.example .env        # 填入 ANTHROPIC_API_KEY
export $(grep -v '^#' .env | xargs)
python cli.py               # 在終端機模擬工作人員提問
python -m pytest -q         # 離線測試（不呼叫 API）
```

### 4. 部署
任何能跑 Python 或 Docker、有 HTTPS 網址的平台都可以（Render、Railway、Google Cloud Run、Fly.io…）：
```bash
docker build -t popup-bot .
docker run -p 8000:8000 --env-file .env popup-bot
```
部署完成後，在 LINE Developers Console → Messaging API → **Webhook URL** 填入
`https://你的網域/callback`，按 **Verify**，並開啟 **Use webhook**。

> 本機開發可用 `ngrok http 8000` 取得臨時 HTTPS 網址測試。

### 5. 限制只有工作人員能用
請工作人員加好友後輸入 `/myid`，把 ID 填到 `.env`：
```
ALLOWED_USER_IDS=Uxxxx,Uyyyy
ADMIN_USER_IDS=Uzzzz
```

---

## 運作方式

```
LINE 訊息 → app.py (webhook，驗證簽章)
          → bot/service.py   指令處理、權限、對話記憶
          → bot/faq_search.py 關鍵字找出可能相關的 FAQ
          → bot/brain.py      Claude 依「FAQ 優先 → 應變框架 → 升級」判斷，輸出結構化結果
          → bot/formatter.py  FAQ 以原文顯示；判斷結果排成步驟＋建議話術
```

- **一致性保證**：Claude 只回傳「要引用哪幾筆 FAQ 的 id」，答案文字由程式直接從 `faq.yaml` 取出原文；引用不存在的 id 會被剔除並標示「信心偏低」。
- **模型**：預設 `claude-opus-5-5`，`CLAUDE_EFFORT` 可調 `low`（較快）/ `medium` / `high`（較細）。
- **成本**：FAQ 與框架放在 system prompt 並啟用 prompt caching，同一段時間內重複提問只需付少量快取讀取費用。
- **對話記憶**存在記憶體中，重啟後會清空（不影響 FAQ 與設定）。若部署多台機器，記憶不會共用。
