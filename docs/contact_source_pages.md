# 申请条件的逐页来源状态

B56：个人页、实验室页、申请页独立更新。一个页面允许邮件，不能覆盖另一个页面的禁令。

## 保存格式

- `contact_instruction_sources`：仍是有效原文数组，最多 8 个完整来源块。
- `contact_instruction_capture`：保留最后一次尝试，兼容原有采集代码。它不代表所有页面都已检查。
- `contact_instruction_pages`：内部账本，`version: 1`，最多 32 页。每页保存原请求地址、记录绑定、身份、最后尝试 `receipt`、真实成功 `last_success` 和可选删除屏障 `last_clear`。
- 容量拒绝记录 `merge_issue: source_limit | page_limit`；格式或绑定无效为 `invalid_input`。不截断数组，也不借拒绝把原来源清空。

页身份由 `requested_source_url` 与 `record_source_url` 组成。原文的 `source_url` 是实际最终地址。尾斜杠和正常 HTTP 升级可视为同页；不同主机、路径和查询仍是不同页面。页面路径保留大小写。

`capture_from_html`、`capture_from_sections`、`capture_failure` 接受可选 `requested_source_url`。省略时兼容原来的 `source_url`。旧的错误跳转 receipt 没有请求地址时，只能在唯一现存页就是记录个人页的情况下识别该页；多页时拒绝猜测。

## 更新和撤回

- `captured`：只替换同一页的来源块，其他页原文及日期不动。
- `empty`：只删除同一页原文；保留成功检查为空的时间。
- 普通 `failed` / `unsupported`：不替换该页原文，也不更新旧 `checked_at`。
- 明确撤回、身份不符、错误跳转或项目范围不明：只停用对应请求页，保留删除屏障。
- 较旧或等时的相反材料不能越过删除屏障。更晚的合法成功观察可以恢复该页。
- 记录 ID、主 URL 集合、身份、组织或记录类型改变，不继承旧记录的任何页面。
- 完整多页快照进入合并时按整个账本处理，不能被兼容用的单个 `capture` 缩成一页。

多页来源按原有条件规则合并：来源冲突仍返回冲突；未知、过期和推断内容不会自动成为明确要求。

## 刷新查询

`contact_instruction_pages(record)` 只返回通过绑定和日期校验的页，每页包含：

- `requested_source_url`、`source_url`、`record_source_url`、可选 `identity_name`。
- `receipt`：最后尝试，可为空；失败可含 `next_retry_at`。
- `sources`：该页当前完整有效原文。
- `last_success_at`：有效原文原日期或成功 empty 的时间；已撤回且没有有效资料时为空。

`next_retry_at` 必须带时区且不早于尝试时间，只允许失败/unsupported，不能提高资料新鲜度。成功后不继续携带旧失败调度信息。

新增第 9 个有效来源时，保留原 8 个；有页槽则保存无来源的拒绝尝试供排队。32 页已满时，不驱逐旧删除记录，getter 可额外显示最后一个被拒尝试供调度；刷新器应将无页槽的新目标标为容量受阻。

## 兼容和公开接口

- 旧来源数组按实际来源页分组，不制造新日期。
- 旧单 receipt 只约束它自己的页面，不能清掉另一个页面。
- 显式坏账本不能退回原始数组绕过删除记录。
- Contact rules 与 target conditions 共同使用经过账本过滤的来源。公开详情不暴露内部页账本或重试状态；写作版本仍根据真实公开内容变化。

本轮测试使用合成网页、临时文件和本地 HTTP 请求。没有抓取真实网站，没有回填历史语料，也没有运行生产调度。
