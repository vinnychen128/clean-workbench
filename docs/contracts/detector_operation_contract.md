# 检测器 / 操作 三件套契约

> 本文件是**机制清单**：每个 `Detector` 与每个 `Operation` 必须有
> ① **能力声明**（能干什么 + **不能干什么**）② **必测样例**（正例 / 反例 / 边界）③ **真实数据对账入口**
> （在「脏点模式表」里对应哪几行 / 对应哪个洗后指标键）。
>
> 机器闸门：`backend/tests/test_detector_operation_contract.py` —— 新增检测器/操作却不登记本文件、
> 或本文件指向的测试用例被删除时，**CI 直接红**。
> 计数以注册表为准：**检测器 9 个 / 操作 16 个**（`DetectorRegistry._registry` / `OperationRegistry._registry`）。

## 0. 对账入口口径

- `mode:<脏点模式表行名>` → 该行名必须在 `scripts/check_residual_dirt.py` 的「脏点模式表」里存在（脚本是入仓的对账证据）。
- `metrics:<键名>` → 必须是 `/api/verify` 指标键（既有 `rows / columns / empty_ratio / dup_ratio`，另有下列五键
  `amount_dirty_ratio / date_nonstandard_ratio / date_invalid_count / unit_dirty_ratio / numeric_dirty_ratio`）。
- `无对应脏点模式（说明原因）` → 该能力当前**不被对账脚本直接计行**，原因必须写清（不许留空）。

## 1. 检测器（9）

| 名称 | 能干什么 | 不能干什么 | 必测样例（正 / 反 / 边界） | 测试落点 | 真实数据对账入口 |
|---|---|---|---|---|---|
| `amount` | 金额列：货币符号 / 英文代码 / 中文后缀混用、千分位写法不一致、全角数字 | 不检测日期、手机号（归 `date` / `format`） | 正：`RMB4055.14`、`2099元` 命中列；反：已规范的 `1349.73` 不报；边界：疑似金额列但全规范 → 只给提示不计分 | `backend/tests/test_unit_detectors.py::test_amount_detector` | `mode:货币符号(￥/¥/$/€)`、`mode:中文货币后缀(元/角/分/万元)`、`mode:英文货币前后缀(RMB/CNY/USD)`；`metrics:amount_dirty_ratio` |
| `date` | 日期列：格式混用（`YYYY-MM-DD` / `YYYY/MM/DD` / 中文年月日 / `YYYYMMDD`）或非法日期 | 不检测非日期列；不做时区换算 | 正：`20240808`、`2024/5/6` 命中；反：全列 ISO 不报；边界：`2024-13-99`（形态合法语义非法）必须命中且不可被当作已修复 | `backend/tests/test_unit_detectors.py::test_date_detector` | `mode:中文日期`、`mode:点/斜杠分隔`、`mode:基础格式 YYYYMMDD`、`mode:语义非法(日期不存在,不可清洗)`；`metrics:date_nonstandard_ratio`、`metrics:date_invalid_count` |
| `null` | 空值：空串 / `None` / 纯空白视为缺失 | 不做填充（填充是 `cell_fill_missing`） | 正：含空单元格命中；反：无空值不报；边界：全空列也照报，不崩 | `backend/tests/test_unit_detectors.py::test_null_detector` | `metrics:empty_ratio` |
| `duplicate` | 完全重复行 | 不做"业务主键重复"判断（那是 `identifier_column`） | 正：整行重复命中；反：仅相似不报；边界：两行数据量大时按行号上限截断 | `backend/tests/test_unit_detectors.py::test_duplicate_detector` | `metrics:dup_ratio` |
| `outlier` | 数值列 IQR 1.5 倍距 + Z-Score 阈值 3 | 不判断业务合理性（`99999` 是否异常由人判断） | 正：极端值命中；反：正常分布不报；边界：样本量过小时不强行判定 | `backend/tests/test_unit_detectors.py::test_outlier_detector` | `无对应脏点模式（人工判断项，不进"应清零"行；只进报告未处理项）` |
| `format` | 同列内日期/电话/邮编格式混用、前后空白、全角半角混用 | 不做格式统一（统一由 `cell_trim` / `cell_fullwidth` / `cell_case` 承担） | 正：同列混用命中；反：单一样式不报；边界：空白差异单独成子项 | `backend/tests/test_unit_detectors.py::test_format_detector` | `mode:全角字符/全角数字`、`mode:首尾空格`；无独立洗后指标（表现为其他指标） |
| `identifier_column` | 疑似主键列含空值 / 重复值（唯一性约束风险） | 不自动决定保留哪一条 | 正：ID 列重复命中；反：唯一 ID 不报；边界：空列跳过 | `backend/tests/test_unit_detectors.py::test_identifier_column_detector` | `metrics:dup_ratio`（唯一性风险由重复率与未处理项共同承担） |
| `mojibake` | 编码乱码：替换符 `\uFFFD`、控制字符、孤立代理、典型 mojibake 序列 | 不区分原始编码来源（GBK/UTF-8 判定在解析层） | 正：含 `��` 命中；反：正常中文不报；边界：单字符乱码也报 | `backend/tests/test_unit_detectors.py::test_mojibake_detector` | `无对应脏点模式（乱码需人工判断改写，脚本不猜）` |
| `unit` | 只判**物理量单位**：同列带单位值与裸数字混用、或 ≥2 种物理量单位；未知单位为独立子项；**计数单位/量词**（件/台/pcs，单一来源 `operations/data/quantity_units.py`）与裸数字混用、或同列 ≥2 种量词时单列子项，并给「剥离为纯数值」建议（`suggest_op=cell_unit_convert` / `to=纯数值`）；货币单位只给「疑似金额列」低优先级提示且 `counted:false` | **不检测货币单位与货币符号**（归金额清洗）；不判单位换算是否合理；不判跨列单位一致性；**全列单一量词粘连（整列都是 `3件`）不报**（反例，避免噪声） | 正：`数量` 列 `3件`+裸数字混用命中（实测 211 行，带 `suggest_op`）；反：全列单一只含 `3件` 不报、纯数字列（`5`+`12`）不报；边界：金额列（`100元`+裸数字）**不得**进"单位混用"命中、同列 ≥2 种量词（`3件`+`2个`）按混用命中 | `backend/tests/test_unit_detectors.py::test_unit_detector`、`backend/tests/test_unit_detectors.py::test_unit_quantity_mixed_reports`、`backend/tests/test_unit_detectors.py::test_unit_single_quantity_unit_only_not_reported`、`backend/tests/test_unit_detectors.py::test_unit_quantity_unit_mixed_bare_gives_suggest`、`backend/tests/test_unit_detectors.py::test_unit_currency_column_not_counted_as_mixed` | `mode:数字与单位粘连`；`metrics:unit_dirty_ratio`、`metrics:numeric_dirty_ratio` |

## 2. 操作（16）

| 名称 | 层 | 能干什么 | 不能干什么 | 必测样例（正 / 反 / 边界） | 测试落点 | 真实数据对账入口 |
|---|---|---|---|---|---|---|
| `row_dedupe` | row | 按指定列子集（默认全列）去重复行 | 不合并"近似重复" | 正：同键重复行只留一条；反：不同键不去；边界：无 `subset` → 作用面记「全表」 | `backend/tests/test_unit_operations.py::test_row_dedupe` | `无对应脏点模式（去重不属"应清零"三类；结果进报告行数变化）` |
| `row_delete` | row | 删除满足条件的行（`where` 单元格值精确匹配，支持空值） | 不做模糊/正则匹配 | 正：命中条件删行；反：不匹配不删；边界：列名不存在 → `validate` 报错 | `backend/tests/test_unit_operations.py::test_row_delete` | `无对应脏点模式（人工删行）` |
| `row_keep` | row | 仅保留满足条件的行 | 同 `row_delete` 的边界 | 正：保留命中行；反：不匹配全删；边界：`where` 空值合法 | `backend/tests/test_unit_operations.py::test_row_keep` | `无对应脏点模式（人工保行）` |
| `column_rename` | column | 重命名一列 | 不改数据值 | 正：改名生效；反：原列名仍存在 → 校验报错；边界：同名改名不报错但需显式 | `backend/tests/test_unit_operations.py::test_column_rename` | `无对应脏点模式（结构操作，不涉脏点计数）` |
| `column_delete` | column | 删除一列或多列 | 不校验删后是否仍满足配方下游依赖 | 正：删列生效；反：不存在列 → `validate` 报错；边界：删全部列后行宽为 0 不崩 | `backend/tests/test_unit_operations.py::test_column_delete` | `无对应脏点模式（结构操作）` |
| `column_split` | column | 按分隔符 / 正则 / 定宽拆分一列为多列 | 不猜测拆分后的列语义 | 正：按 `-` 拆出多列；反：无分隔符保持原值；边界：正则无命中不报错 | `backend/tests/test_unit_operations.py::test_column_split_separator` | `无对应脏点模式（结构操作）` |
| `column_merge` | column | 多列按分隔符合并为一列 | 不做类型推断 | 正：合并产出新列；反：缺列 → 报错；边界：空值参与合并保留分隔符 | `backend/tests/test_unit_operations.py::test_column_merge` | `无对应脏点模式（结构操作）` |
| `column_derive` | column | 基于表达式新建一列（支持 `{col}` 引用与算术） | 不执行任意代码 | 正：算术派生；反：非数值原样保留（不抛异常）；边界：依赖列缺失 → `validate` 报错 | `backend/tests/test_unit_operations.py::test_column_derive` | `无对应脏点模式（结构操作）` |
| `cell_trim` | cell | 去除单元格首尾空白（可选去内部多余空白） | 不删中间的必要空格（未开启内部清理时） | 正：`" 张三 "`→`"张三"`；反：无空白不变；边界：纯空白 → 空串 | `backend/tests/test_unit_operations.py::test_cell_trim` | `mode:首尾空格` |
| `cell_fullwidth` | cell | 全角字符转半角（数字 / 字母 / 标点） | 不转换全角中文标点的语义判断（只做码位映射） | 正：`１２３４`→`1234`；反：半角不变；边界：中文汉字不受影响 | `backend/tests/test_unit_operations.py::test_cell_fullwidth` | `mode:全角字符/全角数字` |
| `cell_case` | cell | 文本转大写 / 小写 / 首字母大写 | 不改数字与非字母字符 | 正：`ab`→`AB`；反：已是目标形态不变；边界：空值不动 | `backend/tests/test_unit_operations.py::test_cell_case` | `无对应脏点模式（大小写不属三类应清零脏点）` |
| `cell_amount_clean` | cell | 去空白 / 全角转半角 / 去货币前后缀（前后缀可叠加，清单单一来源 `operations/data/currency_affixes.py`）/ 去千分位 / 括号负数转负号 | **不把无法解析的值置空**（保留原值并进未处理项）；不猜汇率、不做币种换算 | 正：`1,299.00元`→`1299.00`、`RMB 4055.14`→`4055.14`、`(1200)`→`-1200`；反：`1234.5` 已是数值不动；边界：`待补` / `N/A` 保留原值并登记 | `backend/tests/test_unit_operations.py::test_cell_amount_clean` | `mode:货币符号(￥/¥/$/€)`、`mode:中文货币后缀(元/角/分/万元)`、`mode:英文货币前后缀(RMB/CNY/USD)`、`mode:千分位逗号`、`mode:首尾空格`、`mode:全角字符/全角数字`；`metrics:amount_dirty_ratio` |
| `cell_date_normalize` | cell | 多格式日期统一为 `YYYY-MM-DD`（`YYYYMMDD` / 分隔符 / 中文年月日；`dateutil` 语义解析） | 不修复不存在的日期（非法值保留原值 + 登记未处理）；不做时区换算 | 正：`20240808`→`2024-08-08`、`2024年5月6日`→`2024-05-06`；反：已是 ISO 走快路径不动；边界：`2024-13-99`、`2024.02.30` 保留原值并进未处理项 | `backend/tests/test_unit_operations.py::test_cell_date_normalize` | `mode:中文日期`、`mode:点/斜杠分隔`、`mode:基础格式 YYYYMMDD`、`mode:语义非法(日期不存在,不可清洗)`；`metrics:date_nonstandard_ratio`、`metrics:date_invalid_count` |
| `cell_text_replace` | cell | 整词 / 正则文本替换 | 不做跨列/条件替换 | 正：把 `件` 去掉（`3件`→`3`）；反：无命中不改；边界：正则特殊字符需转义，非法正则由 `validate`/执行期报错 | `backend/tests/test_unit_operations.py::test_cell_text_replace` | `mode:数字与单位粘连`；`metrics:unit_dirty_ratio`、`metrics:numeric_dirty_ratio` |
| `cell_unit_convert` | cell | 数值列单位换算（内置换算表，含 `元↔万元`；未知单位不猜、标记）；目标单位填 `纯数值`（或 `数值`/`number`/`numeric`）→ 「剥离单位」模式，取单元格前导数值（`3件`→3、`5台`→5），量词判据复用 `operations/data/quantity_units.py` 单一来源；同单位（`元→元`）= 恒等换算放行 | 不跨量纲换算；未知单位的换算法不猜（给原因与可用换算范围）；剥离模式**不校验 `from` 是否真出现在单元格内**、也不做换算，非数字开头（如 `N/A`）原样保留 | 正：`1000 元`→`0.1 万元`；反：未知单位对（如 `件→kg`）→ 可读错误文案（含可用换算范围）；边界：`3件`→ 纯数值剥离、同单位 `元→元` 恒等放行且 `describe` 标注「（同单位，恒等换算）」 | `backend/tests/test_unit_operations.py::test_cell_unit_convert`、`backend/tests/test_unit_operations.py::test_cell_unit_convert_identity`、`backend/tests/test_unit_operations.py::test_cell_unit_convert_strip_units`、`backend/tests/test_unit_operations.py::test_cell_unit_convert_unsupported_validate` | `无对应脏点模式（换算是主动加工，不是"洗掉脏点"）` |
| `cell_fill_missing` | cell | 按常量 / 前值 / 后值 / 列均值填充空值 | 不判断"该不该填"（`fill_ratio` 上限由配方侧把关） | 正：常量填充空单元格；反：无空值不变；边界：全空列按均值填充 → 明确报错或标记 | `backend/tests/test_unit_operations.py::test_cell_fill_missing_constant` | `metrics:empty_ratio` |

## 3. 维护约定（新增检测器 / 操作时）

1. 实现类必须写 `description`（声明**能干什么 + 不能干什么**）；
2. 到本文件按表结构补一行（注册表里出现、本文件没有 → CI 红）；
3. 必测样例（正 / 反 / 边界）至少落在两个测试文件之一：`test_unit_detectors.py` / `test_unit_operations.py`，
   并在本文件「测试落点」列写出**真实用例名**（用例被删 → CI 红）；
4. 「真实数据对账入口」必须写明（无对应模式要显式写 `无对应脏点模式（原因）`）。
