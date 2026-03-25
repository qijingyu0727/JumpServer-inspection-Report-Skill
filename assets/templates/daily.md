# JumpServer 每日巡检报告（{{ report_date }}）

**统计区间：** {{ report_range }}
**环境 Profile：** {{ profile_name }}
**组织范围：** {{ scope_name }}
**风险等级：** {{ risk_level }}

## 一、巡检概览
{{ executive_summary }}

## 二、系统命令巡检
{{ command_summary }}

## 三、登录情况
{{ today_login_logs }}

## 四、活跃会话
{{ active_sessions }}

## 五、资产状态
{{ asset_status }}

## 六、操作审计
{{ operate_logs }}

## 七、安全风险摘要
{{ security_risk_summary }}

## 八、处置建议
{{ recommendations }}

## 九、巡检说明
{{ report_notices }}
