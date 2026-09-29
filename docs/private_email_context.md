# 私有邮件首次联系上下文

本模块为现有邮件编辑器提供当前账号的私有目标和本地联系限制回执。只支持 `first_contact`；不会将导入记录发布为公开机会，也不调用模型。

## 读取与写作版本

`GET /api/private-import-targets/{id}/email-context?expected_owner_id=<uuid>` 返回当前版本。必须有有效 Bearer 身份；沿用 B60/B61 的当前账号、会话、归属、删除检查。只允许这个 query 键，拒绝重复和未知键。

`resolve_private_email_context(target_id, *, authorization, expected_owner_id, expected_writing_version=None)` 供写作路由调用。写作路由必须提供本次审阅的 pwt1；每次重新读取当前私有记录，版本不一致返回 `409 private_target_changed`。GET不携带旧版本约束，用户可以明确刷新取得新版本。

回执固定字段：

- `version:1`, `target_scope:'private_import'`, `verification:'unverified'`, `purpose:'first_contact'`。
- `id`, `owner_id`, `revision`, `source_version:'pit1:…'`。
- `projection_version:1`, `policy_version:1`, `writing_version:'pwt1:…'`。
- 完整 `title`、`organization`（可为 null）、经过已有纯语法检查的 `source_url`（可为 null），以及保守的 B59 `import_source`（可为 null）。
- `contact_policy:{state,reason,quotes}` 和 `provider_allowed:false`。

pwt1 是回执除 `writing_version` 本身以外所有字段的 SHA-256，UTF-8、递归键排序、紧凑 JSON、不转义非 ASCII。字段值只含字符串、安全整数、布尔、null和数组/对象。pit1绑定完整私有记录的账号、ID、revision；pwt1再绑定用途、投影和政策版本、实际显示值及规则结果。投影或规则语义变化时必须提升对应版本。

原文仍保存在私有目标中，由 B61 的账号读取接口展示；本回执不重复返回全文。写作版本只证明绑定哪份记录和规则，不是来源真实性或模型传输授权。

## 联系限制

`private_contact_policy` 在本地遍历完整已保存原文，没有前缀截断。原文上限沿用私有存储的 5 × 1024 × 1024 Unicode codepoints；超过上限明确拒绝。

- `state='blocked'`：有限英文或中文规则检测到明确禁发邮件/仅表单申请；用户复选框不能覆盖这个结果。
- `state='unknown'`：没有得到可直接采用的限制结论。仍需用户核对原文，绝不表示允许联系。
- `reason` 只允许 `unverified_import`、`no_email`、`form_only`、`multiple_restrictions`、`policy_review_required`。
- `quotes` 每项为 `{start,end,quote,restriction}`；`restriction` 为 `no_email|form_only`。位置采用保存原文的 Unicode codepoint，`text[start:end]` 必须等于完整 quote。不是 HTML位置、字节或浏览器 UTF-16位置。
- 每条引句最多2000 codepoints、最多20条。发现限制后引句超过容量仍为 blocked，并明确 `policy_review_required`；不能因引句未完整列出而降成 unknown。扫描不会在第20条停止。

规则保守处理条件句、例子、历史叙述、其他申请人范围和部分否定表达。它不理解所有自然语言，也不还原网页全部层级：长段、混合人群、复杂跨句条件、未覆盖措辞仍需人工核查。不能把通过这些例子称为完整政策理解。

没有合成 source checked_at、官方 contact_instructions 或公开资格。原始 extra_fields 中的联系允许、收件人、教授身份、论文、lab、技能要求和 capability均不进入这个合同。保存日期不是官网核对日期。

## 消费边界

模板和人工校验走独立私有上下文。不要传入 `prepare_writing_snapshot`、公开 actionability或公共机会 `_common_parts`来伪造公开来源。`provider_allowed:false`不能由客户端修改开启；本模块没有 provider投影函数。

写作路由负责拒绝 blocked，并对 unknown保留需要核查的提示。收件人必须由用户另行提供/确认，不能从来源链接或 raw extra获得已验证身份。现有草稿和个人历史可以保留；没有发送回执就不能记录为自动发送。

所有接口回包 `private, no-store`；错误只含固定 code。没有修改私有存储、实际语料或数据库迁移。完整简历的私有 AI与全文 provider授权仍未接入。

## 验证

受控 GoTrue/PostgREST MockTransport 测试覆盖真实 FastAPI route→owner读取→当前记录→上下文/版本路径；单独用禁用函数确认不会读取公开语料或调用模型。另有后段限制、Unicode精确偏移、条件/否定/人群反例、引用上限、非法Unicode、删除和版本失效等回归。此证据不表示真实托管认证、数据库或部署已验收。
