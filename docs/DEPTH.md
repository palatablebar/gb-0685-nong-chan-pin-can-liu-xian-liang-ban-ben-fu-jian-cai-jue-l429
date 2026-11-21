# 深度登记 农产品残留限量版本与复检裁决

规模：中型。核心规则：按采样日期选择有效限量，低于检出限保留区间；复检不得越过样本关联与方法适用范围。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 报告采信 | 查看并复算报告采信 | `/api/m1_ingest` | `app/modules/m1_ingest/reader.py` | `tests/test_ingest.py` |
| M2 项目映射 | 查看并复算项目映射 | `/api/m2_mapping` | `app/modules/m2_mapping/rules.py` | `tests/test_mapping.py` |
| M3 限量选版 | 查看并复算限量选版 | `/api/m3_versions` | `app/modules/m3_versions/rules.py` | `tests/test_versions.py` |
| M4 检出量换算 | 查看并复算检出量换算 | `/api/m4_segments` | `app/modules/m4_segments/rules.py` | `tests/test_segments.py` |
| M5 复检裁决 | 查看并复算复检裁决 | `/api/m5_calculate` | `app/modules/m5_calculate/rules.py` | `tests/test_calculate.py` |
| M6 批次判级 | 查看并复算批次判级 | `/api/m6_reconcile` | `app/modules/m6_reconcile/compare.py` | `tests/test_reconcile.py` |
| M7 报告归档 | 查看并复算报告归档 | `/api/m7_archive` | `app/modules/m7_archive/export_out.py` | `tests/test_archive.py` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | GB18030中文 | 固定UTF-8失败 | 按编码链回退 | `app/modules/m1_ingest/decode.py` | `tests/test_ingest.py::test_legacy_encoding` |
| TRAP-02 | 表头BOM | 首列键失配 | 去除BOM | `app/modules/m1_ingest/decode.py` | `tests/test_ingest.py::test_bom` |
| TRAP-03 | 引号内换行 | 分行误计 | csv逻辑记录 | `app/modules/m1_ingest/reader.py` | `tests/test_ingest.py::test_preserves_multiline_note` |
| TRAP-05 | 列数错位 | 静默补列 | WIDTH隔离 | `app/modules/m1_ingest/reader.py` | `tests/test_ingest.py::test_width_isolation` |
| TRAP-06 | 全角千分位 | float失败 | NFKC与Decimal | `app/modules/m2_mapping/coerce.py` | `tests/test_mapping.py::test_thousands` |
| TRAP-07 | 空值哨兵 | 空值当零 | MISSING隔离 | `app/modules/m2_mapping/coerce.py` | `tests/test_mapping.py::test_missing_numeric` |
| TRAP-08 | 前导零ID | 编码失真 | 字符串保形 | `app/modules/m2_mapping/rules.py` | `tests/test_mapping.py::test_identifier_zeroes` |
| TRAP-10 | 浮点误差 | 累计失准 | Decimal求和 | `app/modules/m2_mapping/coerce.py` | `tests/test_mapping.py::test_decimal_precision` |
| TRAP-14 | 同版冲突 | 最后覆盖 | 整组隔离 | `app/modules/m2_mapping/rules.py` | `tests/test_mapping.py::test_real_conflict_quarantine` |
| TRAP-18 | 三种空态 | 除零或伪成功 | 三个错误码 | `app/modules/m1_ingest/reader.py` | `tests/test_ingest.py::test_empty_three_states` |
| TRAP-26 | 旧版本复核 | 覆盖新结论 | 事务条件更新 | `app/store.py` | `tests/test_archive.py::test_stale_review` |
| TRAP-15 | ug/kg与mg/kg | 差1000倍 | 浓度统一mg/kg | `app/modules/m4_segments/rules.py` | `tests/test_segments.py::test_unit_conversion` |
| TRAP-25 | 标准时间边界 | 双版或错版 | 采样日半开区间选版 | `app/modules/m3_versions/standards.py` | `tests/test_versions.py::test_halfopen_effective` |
| TRAP-20 | 复检引用环 | 遍历无法结束 | 引用路径检测 | `app/modules/m5_calculate/rules.py` | `tests/test_calculate.py::test_cycle_rejected` |
| TRAP-27 | 目录两版生效重叠 | 静默选版或整批退回 | 裁决随目录版本登记，重叠日按裁决出证，未裁决隔离 | `app/catalog.py`、`app/modules/m3_versions/standards.py` | `tests/test_catalog.py::test_overlap_without_ruling_quarantined` |
| TRAP-28 | 目录切换中断 | 新旧目录混用 | 版本登记与生效指针同事务，中断回滚留旧版 | `app/catalog.py` | `tests/test_catalog.py::test_switch_interruption_keeps_old` |
| TRAP-29 | 换目录重算 | 覆盖旧批次或重复建批 | 运行幂等键纳入目录身份，同目录复用批次，换目录新批次并存 | `app/manifest.py`、`app/workflow.py` | `tests/test_catalog.py::test_catalog_switch_creates_new_batch_and_keeps_records` |

## 目录版本与重叠裁决

限量目录按版本登记（内容+裁决哈希寻址），原始目录始终保留为首个版本。同产品同残留项目生效期重叠时，裁决以 `产品|项目→标准号` 登记在目录版本上：重叠日采样的在途批次按裁决版本出证，重叠日之外新版全面适用。未登记裁决的重叠行按 VERSION 隔离，不静默选版。目录切换为单事务：版本登记与生效指针同生同灭，中断即回滚留旧版。运行幂等键=输入字节+参数+规则版本+目录身份，同目录重跑复用批次，换目录生成新批次且旧批次原样保留。项目结论、批次等级、封存标记由同一次运行派生，共用同一目录身份与裁决记录。

## 对账规则

输入行数=采纳+隔离+空行+重复表头+完全重复；业务总数与计算证据独立求和。隔离行保留来源行、ID、原因码与原值。

## 已知不覆盖

不做多租户权限和外部服务联调。行业规则以项目数据字典为准。文件上限2MB，逐行解析后在上限内完成分组计算。
