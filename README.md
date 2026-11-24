# proofmarket

离线合规评审的证据图判定、证据采购与方案复核工具。仅使用 Python 3.12 标准库，
不需要网络、数据库或第三方包。

- `judge CASE EVIDENCE`：判定版本证据图，输出每个控制项的精确时间并集、
  最小可核验反例和首个不能证明的依赖。
- `buy CASE EVIDENCE`：穷举最多 18 个采购动作，按
  **全期费用 → 后续人工复核天数 → 采购条数 → 升序 ID** 选唯一方案。
- `check CASE EVIDENCE SOLUTION`：独立重算可行性与最优性，拒绝虚假独立性和
  “同费用但人工复核天数更大”的方案。

所有 JSON 均为 UTF-8；时间端点为 Python 整数，区间统一是左闭右开 `[start,end)`。
宿主时轴可以跨越 `10^9`，算法只处理输入中的少量端点，不逐时刻遍历。

## 运行

在仓库根目录：

```bash
python -m proofmarket judge fixtures/01_basic_graph/case.json fixtures/01_basic_graph/evidence.json
python -m proofmarket buy   fixtures/03_trap_alpha/case.json fixtures/03_trap_alpha/evidence.json
python -m proofmarket check fixtures/03_trap_alpha/case.json fixtures/03_trap_alpha/evidence.json fixtures/03_trap_alpha/solution-good.json
```

也可以使用根目录包装器或直接入口：

```bash
python proofmarket.py buy CASE.json EVIDENCE.json
python judge.py CASE.json EVIDENCE.json
python buy.py CASE.json EVIDENCE.json
python check.py CASE.json EVIDENCE.json SOLUTION.json
```

处理不受信任的输入路径时，可用隔离模式运行包装器；包装器只加入自身代码目录，
不把当前数据目录加入 `sys.path`：

```bash
python -I proofmarket.py judge CASE.json EVIDENCE.json
```

`check` 接受解决方案文件，也接受之前 `buy` 输出的 JSON（读取其中的
`selected_actions` / `plan.selected_actions`）。复核拒绝时 stdout 仍是 UTF-8
JSON，进程退出码为 `1`；输入格式错误退出码为 `2`。

## 输入格式

### 1. CASE

```jsonc
{
  "schema": "proofmarket.case.v1",
  "case_id": "example",
  "decision_time": 100,          // 可选；known_at 更晚的证据不可知
  "controls": [ /* Control */ ],
  "ownership_intervals": [ /* Ownership */ ],
  "pricing_batches": [ /* BatchPrice */ ],
  "actions": [ /* PurchaseAction，最多 18 个 */ ]
}
```

#### Control

```jsonc
{
  "id": "C1",
  "risk_class": "payments",
  "independence_group": "payments-group", // 仅作分组说明/输出
  "required_intervals": [[0, 1000000000]],
  "required_regions": ["CN"],             // 可省略，默认 ["*"]
  "rule": {
    "alternatives": [
      {"id": "annual", "kinds": ["annual_report"], "quorum": 1},
      {
        "id": "two-labs",
        "kinds": ["lab_report"],
        "quorum": 2,
        "independent": true,
        "coverage_policy": "at_each_time"
      }
    ]
  }
}
```

`coverage_policy`：

- `at_each_time`（独立证据默认）：在每个由区间端点切出的基本单元上，都要有
  `quorum` 份覆盖该单元且满足独立性的证据。不同时间段允许换一对证据。
- `same_pair_full_span`、`same_pair` 或 `shared_period`：除局部单元外，还要求
  同一对证据在整个必需区间内都覆盖且独立。临时母公司合并会使该固定证据对失效，
  即使合并区间两侧各有一段非相邻的局部独立区间，也不能拼成同一份“完整年报替代”。

#### Ownership：按实际所有权，而不是法律标签

```jsonc
{"entity": "LAB_A_LEGAL_1", "owner": "ACTUAL_GROUP_A", "start": 0, "end": 100}
```

也支持：

```jsonc
{"entity": "LAB_X", "owner": "PARENT", "intervals": [[0, 40], [60, 100]]}
```

两个法律单位若在同一时间有相同 `owner`，不算独立来源。所有权时间线的相邻不同
owner 段不会被错误合并。

#### PurchaseAction

```jsonc
{
  "id": "act_buy_a",
  "grants": ["EVIDENCE_ID"],
  "full_period_cost": 3,
  "review_days": 1,
  "line_count": 1,
  "batch": "lab_batch"
}
```

`cost`/`price` 是 `full_period_cost` 的别名；`manual_review_days` 是
`review_days` 的别名。未指定 `line_count` 时，一个动作算一条采购条数。

动作上的 `quoted_controls`、`quoted_regions`、`quoted_intervals` 等报价范围字段
只用于合成夹具说明，**完全不参与证明**。能否复用只看证据节点的真实 coverage 与
批准区域交集。

#### 分段合并包价格

```jsonc
{
  "id": "lab_batch",
  "count_basis": "action",       // action(默认) | line_count | evidence_count
  "tiers": [
    {"min_count": 1, "max_count": 2, "unit_cost": 6},
    {"min_count": 3, "max_count": 18, "unit_cost": 4}
  ]
}
```

tier 也可使用 `min`/`max`/`min_actions`，总价模式可用
`total_cost` 或 `package_cost`。绑定 batch 后，该 batch 内动作按匹配 tier 统一
计价，不再累加动作自身的 `cost`；未绑定 batch 的动作使用自身 `full_period_cost`。

### 2. EVIDENCE：版本证据图

```jsonc
{
  "schema": "proofmarket.evidence.v1",
  "nodes": [
    {
      "id": "E1",                 // 必需，建议把版本写进 ID 或同时给 version
      "version": 3,
      "kind": "lab_report",
      "type": "leaf",             // leaf/signoff 或 composite/commitment
      "source": "LAB_A",          // 法律实验室 ID，用于查实际 owner
      "signed": true,
      "revoked": false,
      "known_at": 90,
      "available": false,         // buy 目录中待购证据设 false，由 action.grants 激活
      "prerequisites": ["E0"],    // composite 使用
      "approved_regions": ["CN"],
      "coverage": [
        {
          "controls": ["C1", "C2"], // 或 "*"，一份证据可覆盖几十个控制项
          "regions": ["CN"],
          "intervals": [[100, 900]]
        }
      ]
    }
  ]
}
```

也接受裸数组或 `{"evidence": [...]}` / `{"items": [...]}` / ID 到节点的对象。

复合承诺仅在自身未撤销/可知且 **所有** `prerequisites` 都有效时才覆盖声明区域。
任一前置缺失、撤销、未购买、不可知或陷入环，都会使该复合承诺无效；判定结果给出
稳定的 `dependency_path`。

真实有效覆盖按以下交集计算：

```text
claim.intervals
∩ claim.regions
∩ evidence.approved_regions
∩ control.required_regions
∩ control.required_intervals
```

`"*"` 是区域/控制项通配符。报价单声称覆盖多少控制项或区域均不影响该交集。

### 3. SOLUTION

```jsonc
{
  "selected_actions": ["act_a", "act_b"],
  "independence_claims": [
    {
      "control": "C1",
      "upstreams": ["E_UP1", "E_UP2"],
      "interval": [0, 100]
    }
  ]
}
```

`independence_claims` 也可命名为 `source_claims`、`independent_pairs` 或
`source_assignments`。若两个 ID 只是同一控制项/同一复合承诺的不同上游，`check`
会返回 `UPSTREAM_SOURCES_NOT_INDEPENDENT`；若实际 owner 相同，会返回
`COMMON_OWNERSHIP`。

## 输出要点

### judge

```jsonc
{
  "schema": "proofmarket.judgement.v1",
  "proven": false,
  "first_unprovable_dependency": { /* 全局首个 */ },
  "minimal_verifiable_counterexample": { /* 全局首个 */ },
  "controls": [
    {
      "id": "C1",
      "proven": false,
      "required_union": [[0, 1000000000]],
      "covered_union": [[0, 400000000], [600000000, 1000000000]],
      "certified_union": [],
      "actual_valid_evidence_union": [ /* 所有图有效证据的真实覆盖并集 */ ],
      "gaps": [[400000000, 600000000]],
      "counterexample": {
        "kind": "uncovered_time",
        "at": 400000000,
        "minimum_witness": {"time": 400000000, "half_open_cell": [400000000, 600000000]},
        "maximal_gap": [400000000, 600000000],
        "reason": "common_owner:TEMP_PARENT,TEMP_PARENT",
        "diagnostic": { /* 候选证据、各证据 owner 等可重算信息 */ },
        "verification": [ /* 可复核断言 */ ]
      },
      "first_unprovable_dependency": {
        "evidence_id": "E_COMP",
        "dependency_id": "E_MISSING",
        "reason": "prerequisite_invalid:missing_evidence",
        "dependency_path": ["E_COMP", "E_MISSING"]
      },
      "alternatives": [ /* 每种证明模式的精确并集、见证、稳定证据对 */ ]
    }
  ]
}
```

反例选择规则是稳定的：在所有证明路径中取最小的失败端点；同一位置输出由所有区间
和所有权端点切成的基本单元，以及该单元上的候选/owner 诊断，因此可用少量端点算术
复核，不需要扫描 `10^9` 个时刻。

`covered_union` 是端点单元上满足局部 quorum/独立性的精确并集；`certified_union`
是按策略真正可签发的并集。对 `same_pair_full_span`，若不存在一对证据覆盖并独立于
整个必需区间，`certified_union` 为空，即使 `covered_union` 仍显示合并期两侧的
两个非相邻局部区间。

### buy

目标键为：

```text
(full_period_cost, review_days, purchase_count, tuple(ascending_action_ids))
```

由于最后一项是完整 ID 序列，每个子集都有唯一决胜键。实现会把“动作 mask 下某证据
节点是否有效”编译成 Python 大整数 bitset，再用区间单元的 AND/OR 得到所有可行
mask；18 个动作共有 `2^18 = 262144` 个子集，普通 CPU 可在约 1 秒量级完成
（40 个控制项的压力测试也包含在 unittest 中）。

### check

常见违规码：

- `FALSE_INDEPENDENCE` / `UPSTREAM_SOURCES_NOT_INDEPENDENT`
- `UPSTREAM_COMMITMENT_CLAIMED_AS_LAB`
- `DEPENDENT_EVIDENCE_GRAPH`
- `COMMON_OWNERSHIP` / `UNKNOWN_ACTUAL_OWNERSHIP`
- `REVIEW_DAYS_NOT_MINIMAL`
- `PURCHASE_COUNT_NOT_MINIMAL` / `ID_TIE_BREAK_LOSS`
- `NOT_MINIMAL_FULL_PERIOD_COST`
- `INFEASIBLE_SOLUTION`

## 合成夹具

| 目录 | 手算场景 |
|---|---|
| `fixtures/01_basic_graph/` | 年报直接证明；复合承诺引用缺失前置，输出首个依赖链。 |
| `fixtures/02_legal_split/` | 同一实际集团拆成两个法律实验室 ID，不能形成两份独立来源。 |
| `fixtures/03_trap_alpha/` | **第一个“两个便宜单买但失去独立阈值”的例子**：支付组的 `act_p_a1_cheap`、`act_p_a2_cheap` 各收费 1，却同属 `P_ACTUAL_GROUP`；唯一最优是 A1 + 独立 B。另含同费用但复核天数更大的坏方案。 |
| `fixtures/04_trap_beta/` | **第二个不同组的例子**：客户数据组的两个便宜动作给出 ID 不同的上游承诺 `E_Q_U1/E_Q_U2`，但同属 `Q_COMMON_PARENT`，且上游承诺本身不能冒充两个独立实验室；`check` 明确拒绝。 |
| `fixtures/05_merger_huge/` | 时轴 `[0,10^9)`；两个实验室在 `[4e8,6e8)` 临时同属 `TEMP_PARENT`。局部独立并集恰为两个非相邻区间 `[0,4e8) ∪ [6e8,1e9)`，固定一对覆盖全年的年报替代失败。 |
| `fixtures/06_bundle_reuse/` | 32 个控制项复用一份真实 broad coverage；实验室批量包按 1–2 件单价 6、3+ 件单价 4 分段；便宜动作的报价范围写为 `"*"`，真实覆盖只有 `C_01`，不能复用。 |

重新生成 32 控制项夹具：

```bash
python fixtures/06_bundle_reuse/generate_fixture.py
```

## 题目指定反例对照

1. **便宜单买 A：支付组独立性阈值丢失**  
   `fixtures/03_trap_alpha/` 中 `act_p_a1_cheap` 与 `act_p_a2_cheap` 各收费 1，
   但两个实验室的实际 owner 都是 `P_ACTUAL_GROUP`。只买这两个动作不能满足
   `C_PAYMENTS_DUAL_LAB`；规范解是 `act_p_a1_cheap + act_p_b_fast`，全期费用 4、
   复核 2 天。`solution-bad-review.json` 与规范解同费 4，但复核 6 天，`check`
   返回 `REVIEW_DAYS_NOT_MINIMAL`。

2. **便宜单买 B：客户数据组/上游来源阈值丢失**  
   `fixtures/04_trap_beta/` 中 `act_q_u1_cheap`、`act_q_u2_cheap` 各收费 1，
   但 `E_Q_U1/E_Q_U2` 是同一控制项依赖的两个不同上游承诺，且实际 owner 同为
   `Q_COMMON_PARENT`。`solution-false-upstreams.json` 会被
   `check` 以 `FALSE_INDEPENDENCE` 拒绝；即使动作本身买了正确实验室
   （`solution-false-claim-good-actions.json`），虚假来源声明仍被拒绝。

3. **临时母公司合并与 `10^9` 时轴**  
   `fixtures/05_merger_huge/` 只有 `0`、`4×10^8`、`6×10^8`、`10^9` 等少量端点。
   两个实验室在中间区间同属 `TEMP_PARENT`，精确局部并集为
   `[0,4×10^8) ∪ [6×10^8,10^9)`；在 `same_pair_full_span` 模式下
   `certified_union=[]`，因为同一对证据不能证明完整年报区间。

对应断言位于 `tests/test_judge_fixtures.py`、`tests/test_buy_and_check.py` 和
`tests/test_semantics.py`。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖：

- 大跨度端点并集、交集、差集和邻接区间；
- 缺失依赖路径、法律单位拆分、临时母公司合并；
- 两个采购陷阱、同费用更高复核天数、虚假上游独立性；
- 分段报价、32 控制项复用、报价范围无效；
- bitset 穷举编译器与完整 `JudgeEngine` 对每个小子集的一致性；
- 18 动作 / 40 控制项的 `2^18` 穷举性能；
- 真实子进程 CLI 的 UTF-8 JSON 和 `check` 非零退出码。

## 设计约束

- 纯 Python 3.12 标准库；无网络调用。
- 不按时刻遍历；只排序少量区间/所有权端点。
- 所有采购子集穷举，不使用可能漏掉决胜方案的贪心。
- `buy` 的快速 bitset 与详细 `judge` 共用同一套区域、所有权和图独立性规则；
  小规模测试逐 mask 对拍。
