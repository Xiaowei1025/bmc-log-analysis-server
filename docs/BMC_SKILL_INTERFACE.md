# 公司内网 BMC Skill 接口

## 目标

本接口让公司内部的 BMC 日志读取规则与网页现有的“问题特征库”并行工作：上传日志后，系统先完成基础压缩包读取，再调用内部 Skill，并把返回的确定性结论、证据和处置建议保存到分析报告中。

它不是联网 Agent，也不会主动访问公司内网。后续拥有公司 Skill 说明和权限的 AI Agent，应将规则实现为一个受控的本地 Python 模块，再由本接口加载。

## 配置

在部署环境 `.env` 中配置受信任模块：

```ini
BMC_SKILL_ADAPTER=app.skills.company_bmc:analyze_log_bundle
```

未配置时，平台照常运行既有特征库比对；报告会明确显示未启用公司 Skill。

## 函数签名

```python
def analyze_log_bundle(*, files: dict[str, str], archive_path: Path) -> dict:
    ...
```

- `files`：平台已在内存中安全读取的日志文本，键为压缩包内相对路径。
- `archive_path`：受控上传区内的原始归档路径，仅供本地解析器使用。
- Skill 不得执行归档中的任何文件，不得将日志发送到未经批准的外部服务。

返回值：

```python
{
  "skill_name": "company-bmc-parser",
  "skill_version": "2026.07",
  "warning": "可选，非致命提示",
  "findings": [
    {
      "rule_id": "fan.failure.v1",
      "title": "风扇故障",
      "severity": "critical|high|medium|low",
      "summary": "现象与结论摘要",
      "diagnosis": "确定性诊断",
      "solution": "建议处置",
      "evidence": [
        {"file": "归档内路径", "line": 42, "excerpt": "可核对的原文片段"}
      ],
      "metadata": {"model": "R220", "bmc_version": "1.9.0.23"}
    }
  ]
}
```

平台会限制返回数量、证据数量和片段长度；无效结果不会中断已有特征比对。每项结论应至少提供一条可核对证据。

## 移交流程

1. 将脱敏的命中/不命中样本放入受控测试目录，不提交到交付包。
2. 先把简单“文件路径 + 关键字/正则”规则录入网页特征库。
3. 将错误码、时间关联、阈值、多文件上下文等复杂规则实现为 `app.skills.company_bmc`。
4. 每条内部规则至少新增一条命中和一条不命中自动化测试。
5. 更新 `docs/HANDOFF.md`：Skill 版本、规则来源、支持机型、样本位置、已知误报与回滚方式。
